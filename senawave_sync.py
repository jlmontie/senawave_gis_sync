"""
senawave_sync.py - Keep a file geodatabase in sync with Senawave's KML/KMZ data.

  Settings live in config.ini next to this script (copy config.example.ini
  the first time - config.ini is git-ignored so paths and URLs stay local).

  Sources (see config.ini):
    design       Q-NETWORK LINK.kmz on the NAS  -> Design_* feature classes
    address_ids  portal generate_kml.php feed   -> Cust_AddressIDs
    autobill     portal AutoBill customers feed -> Cust_AutoBillCustomers

Usage (from the ArcGIS Pro Python command prompt, or run_sync.bat):
    propy senawave_sync.py                      sync every source that changed
    propy senawave_sync.py --source design      one source only
    propy senawave_sync.py --force              reload even if unchanged / row-count check fails
    propy senawave_sync.py --dry-run            no ArcGIS needed: write CSVs + review report only
    propy senawave_sync.py --test-login         check the portal username/password work
"""
import argparse
import configparser
import csv
import datetime as dt
import hashlib
import json
import logging
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import kml_reader
import parsers
import schema
import design_rules

csv.field_size_limit(10_000_000)
log = logging.getLogger("senawave_sync")


# ----------------------------------------------------------------------------
# Config / logging
# ----------------------------------------------------------------------------
DEFAULT_CONFIG = os.environ.get("SENAWAVE_SYNC_CONFIG") or os.path.join(HERE, "config.ini")


def load_config(path):
    cfg = configparser.ConfigParser(interpolation=None)
    if not cfg.read(path, encoding="utf-8"):
        example = os.path.join(HERE, "config.example.ini")
        hint = ""
        if os.path.abspath(path) == os.path.join(HERE, "config.ini") and os.path.exists(example):
            hint = ("\n\nThis repo ships config.example.ini instead, so local paths and URLs "
                    "never get committed. Create your copy with:\n"
                    f'    copy "{example}" "{path}"\n'
                    "then edit it.")
        sys.exit(f"Config file not found: {path}{hint}")
    # Relative paths in the config are resolved against the script folder
    g = cfg["general"]
    for key in ("gdb", "work_folder"):
        if g.get(key) and not os.path.isabs(g[key]):
            g[key] = os.path.normpath(os.path.join(HERE, g[key]))
    return cfg


def setup_logging(work_folder):
    os.makedirs(work_folder, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    log.setLevel(logging.INFO)
    fh = logging.FileHandler(os.path.join(work_folder, "sync.log"), encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)


# ----------------------------------------------------------------------------
# Portal login
# ----------------------------------------------------------------------------
def portal_session(cfg):
    import requests
    p = cfg["portal"]
    user = os.environ.get(p.get("username_env", "SENAWAVE_PORTAL_USER"))
    pwd = os.environ.get(p.get("password_env", "SENAWAVE_PORTAL_PASSWORD"))
    if not user or not pwd:
        raise RuntimeError("Portal username/password environment variables are not set "
                           "(see README: SENAWAVE_PORTAL_USER / SENAWAVE_PORTAL_PASSWORD).")
    s = requests.Session()
    s.headers["User-Agent"] = "Senawave-GIS-Sync/1.0"
    login_url = p["login_url"]
    # Pick up hidden form fields (CSRF tokens etc.) from the login page
    form = {}
    page = s.get(login_url, timeout=60)
    for m in re.finditer(r"<input[^>]+>", page.text, re.I):
        tag = m.group(0)
        if re.search(r"type=['\"]?hidden", tag, re.I):
            n = re.search(r"name=['\"]([^'\"]+)", tag)
            v = re.search(r"value=['\"]([^'\"]*)", tag)
            if n:
                form[n.group(1)] = v.group(1) if v else ""
    form[p.get("username_field", "username")] = user
    form[p.get("password_field", "password")] = pwd
    for k, v in p.items():
        if k.startswith("extra_field."):
            form[k.split(".", 1)[1]] = v
    post_url = p.get("post_url", login_url)
    r = s.post(post_url, data=form, timeout=60, allow_redirects=True)
    r.raise_for_status()
    return s


# ----------------------------------------------------------------------------
# Change detection
# ----------------------------------------------------------------------------
def load_state(work_folder):
    fp = os.path.join(work_folder, "sync_state.json")
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(work_folder, state):
    with open(os.path.join(work_folder, "sync_state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def fetch_source(name, sec, session_getter):
    """Return (raw_bytes, fingerprint, label)."""
    if sec.get("url"):
        raw = kml_reader.load_bytes_from_url(sec["url"], session_getter())
        label = sec["url"]
    else:
        path = sec["path"]
        raw = kml_reader.load_bytes_from_path(path)
        label = os.path.basename(path)
    return raw, hashlib.sha1(raw).hexdigest(), label


# ----------------------------------------------------------------------------
# Outputs that don't need ArcGIS
# ----------------------------------------------------------------------------
def write_review_report(work_folder, source, out):
    """One row per (folder path, geometry, result) so rules can be checked quickly."""
    rows = Counter()
    for fc, recs in out.items():
        for r in recs:
            rows[(r.get("FolderPath", ""), fc, r.get("Subtype", ""), r.get("ClassMethod", ""),
                  r.get("StyleKey", ""))] += 1
    fp = os.path.join(work_folder, f"review_{source}.csv")
    with open(fp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["NeedsReview", "Count", "FolderPath", "FeatureClass", "Subtype", "ClassMethod", "StyleKey"])
        for (path, fc, sub, meth, sk), n in sorted(rows.items(),
                                                   key=lambda kv: (not kv[0][3].startswith("UNCLASS"), kv[0][0])):
            w.writerow(["YES" if meth.startswith(("UNCLASS", "style")) else "", n, path, fc, sub, meth, sk])
    return fp


def write_csvs(work_folder, source, out):
    folder = os.path.join(work_folder, f"dryrun_{source}")
    os.makedirs(folder, exist_ok=True)
    for fc, recs in out.items():
        keys = sorted({k for r in recs for k in r}, key=lambda k: (k == "SHAPE@WKT", k))
        with open(os.path.join(folder, f"{fc}.csv"), "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in recs:
                w.writerow(r)
    return folder


# ----------------------------------------------------------------------------
# Geodatabase writer (ArcGIS Pro)
# ----------------------------------------------------------------------------
def _safe_field_name(name, taken):
    base = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_") or "Field"
    if base[0].isdigit():
        base = "F_" + base
    base = base[:60]
    cand, i = base, 2
    while cand.upper() in taken:
        cand, i = f"{base}_{i}", i + 1
    taken.add(cand.upper())
    return cand


class GdbWriter:
    def __init__(self, cfg):
        import arcpy
        self.arcpy = arcpy
        g = cfg["general"]
        self.gdb = g["gdb"]
        self.min_ratio = g.getfloat("min_row_ratio", 0.5)
        self.out_sr = arcpy.SpatialReference(g.getint("output_wkid", 4326))
        self.wgs84 = arcpy.SpatialReference(4326)
        if g.get("geographic_transformation"):
            arcpy.env.geographicTransformations = g["geographic_transformation"]
        arcpy.env.overwriteOutput = True
        if not arcpy.Exists(self.gdb):
            folder, name = os.path.split(self.gdb)
            os.makedirs(folder, exist_ok=True)
            arcpy.management.CreateFileGDB(folder, name)
            log.info("Created geodatabase %s", self.gdb)
        self._ensure_log_table()

    # -- sync log table ------------------------------------------------------
    def _ensure_log_table(self):
        a = self.arcpy
        self.log_table = os.path.join(self.gdb, "SyncLog")
        if not a.Exists(self.log_table):
            a.management.CreateTable(self.gdb, "SyncLog")
            for n, t, l in [("SyncTime", "DATE", None), ("Source", "TEXT", 50), ("FeatureClass", "TEXT", 100),
                            ("RowsLoaded", "LONG", None), ("Status", "TEXT", 20), ("Message", "TEXT", 1000)]:
                a.management.AddField(self.log_table, n, t, field_length=l)

    def log_row(self, source, fc, rows, status, msg=""):
        try:
            with self.arcpy.da.InsertCursor(self.log_table, ["SyncTime", "Source", "FeatureClass",
                                                             "RowsLoaded", "Status", "Message"]) as c:
                c.insertRow([dt.datetime.now(), source, fc, rows, status, msg[:1000]])
        except Exception as e:                       # never fail a sync because of logging
            log.warning("Could not write SyncLog row: %s", e)

    # -- feature classes -----------------------------------------------------
    def _create_fc(self, workspace, name, geom, fields, sr):
        a = self.arcpy
        fc = a.management.CreateFeatureclass(workspace, name, geom, spatial_reference=sr)[0]
        a.management.AddFields(fc, [[n, t, n, l] if l else [n, t] for n, t, l in fields])
        if geom == "POLYLINE":
            a.management.AddField(fc, "Length_ft", "DOUBLE")
        elif geom == "POLYGON":
            a.management.AddField(fc, "Area_acres", "DOUBLE")
        return fc

    def replace(self, source, parser_name, fc_name, fc_base, recs, force=False):
        a = self.arcpy
        geom, base_fields = schema.fields_for(parser_name, fc_base)

        # Dynamic "ED:" attributes (third-party ExtendedData) become TEXT fields
        taken = {n.upper() for n, _, _ in base_fields} | {"OBJECTID", "SHAPE", "LENGTH_FT", "AREA_ACRES",
                                                          "SHAPE_LENGTH", "SHAPE_AREA"}
        ed_map = {}
        for r in recs:
            for k in r:
                if k.startswith("ED:") and k not in ed_map:
                    ed_map[k] = _safe_field_name(k[3:], taken)
        fields = list(base_fields) + [(fn, "TEXT", 255) for fn in ed_map.values()]
        names = [n for n, _, _ in fields]
        source_key = {v: k for k, v in ed_map.items()}      # field name -> row key

        live = os.path.join(self.gdb, fc_name)
        if not a.Exists(live):
            self._create_fc(self.gdb, fc_name, geom, fields, self.out_sr)
            log.info("  created %s", fc_name)
        else:
            existing = {f.name.upper() for f in a.ListFields(live)}
            for n, t, l in fields:
                if n.upper() not in existing:
                    try:
                        a.management.AddField(live, n, t, field_length=l)
                        log.info("  added field %s.%s", fc_name, n)
                    except Exception:
                        log.warning("  could not add field %s.%s (layer open in Pro?) - skipped this run",
                                    fc_name, n)

        # Safety check: refuse to wipe a layer with a suspiciously small load
        old_count = int(a.management.GetCount(live)[0])
        if old_count and len(recs) < old_count * self.min_ratio and not force:
            msg = (f"new load has {len(recs)} rows vs {old_count} existing "
                   f"(< {self.min_ratio:.0%}); kept existing data. Use --force to override.")
            log.warning("  %s: %s", fc_name, msg)
            self.log_row(source, fc_name, 0, "SKIPPED", msg)
            return

        # 1) Build a staging copy in memory (live data untouched if this fails)
        stage_name = "stage_" + re.sub(r"\W", "_", fc_name)
        stage = self._create_fc("memory", stage_name, geom, fields, self.wgs84)
        bad = 0
        with a.da.InsertCursor(stage, names + ["SHAPE@WKT"]) as cur:
            for r in recs:
                vals = []
                for n, t, l in fields:
                    v = r.get(source_key.get(n, n))
                    if t == "TEXT":
                        v = "" if v is None else str(v)[: (l or 255)]
                    vals.append(v)
                for wkt in _explode_for(geom, r["SHAPE@WKT"]):
                    try:
                        cur.insertRow(vals + [wkt])
                    except Exception:
                        bad += 1
        if bad:
            log.warning("  %s: %d feature(s) had geometry that could not be stored", fc_name, bad)
        if geom == "POLYGON":
            a.management.RepairGeometry(stage, "DELETE_NULL")
            a.management.CalculateGeometryAttributes(stage, [["Area_acres", "AREA_GEODESIC"]],
                                                     area_unit="ACRES")
        elif geom == "POLYLINE":
            a.management.CalculateGeometryAttributes(stage, [["Length_ft", "LENGTH_GEODESIC"]],
                                                     length_unit="FEET_US")
        new_count = int(a.management.GetCount(stage)[0])

        # 2) Swap: delete live rows, append staging (keeps layers/symbology in Pro intact)
        a.management.DeleteRows(live)
        a.management.Append(stage, live, "NO_TEST")
        a.management.Delete(stage)
        log.info("  %-28s %6d rows (was %d)", fc_name, new_count, old_count)
        self.log_row(source, fc_name, new_count, "OK", f"was {old_count}" + (f"; {bad} bad geometries" if bad else ""))


def _explode_for(geom, wkt):
    """Point feature classes can't hold MULTIPOINT - split them."""
    if geom == "POINT" and wkt.startswith("MULTIPOINT"):
        return ["POINT " + m for m in re.findall(r"\([^()]+\)", wkt[len("MULTIPOINT"):])]
    return [wkt]


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def fc_names_for(parser_name, sec, out):
    prefix = sec.get("prefix", "")
    names = {}
    for fc in out:
        is_third_party = any(fc.startswith(p + "_") for p in design_rules.THIRD_PARTY_FOLDERS.values())
        names[fc] = fc if is_third_party else prefix + fc
    return names


def run(args):
    cfg = load_config(args.config)
    work = cfg["general"]["work_folder"]
    setup_logging(work)
    state = load_state(work)

    session = {}
    def get_session():
        if "s" not in session:
            session["s"] = portal_session(cfg)
        return session["s"]

    if args.test_login:
        s = get_session()
        for name in [n.split(":", 1)[1] for n in cfg.sections() if n.startswith("source:")]:
            sec = cfg["source:" + name]
            if sec.get("url"):
                try:
                    raw = kml_reader.load_bytes_from_url(sec["url"], s)
                    log.info("LOGIN OK - %s returned %.1f MB of KML", name, len(raw) / 1e6)
                except Exception as e:
                    log.error("LOGIN/DOWNLOAD FAILED for %s: %s", name, e)
        return 0

    sources = [n.split(":", 1)[1] for n in cfg.sections() if n.startswith("source:")]
    if args.source:
        sources = [s for s in sources if s in args.source]
    writer = None
    exit_code = 0

    for name in sources:
        sec = cfg["source:" + name]
        if not sec.getboolean("enabled", True):
            continue
        parser_name = sec["parser"]
        log.info("=== %s", name)
        try:
            raw, fingerprint, label = fetch_source(name, sec, get_session)
            if not args.force and not args.dry_run and state.get(name, {}).get("sha1") == fingerprint:
                log.info("  unchanged since last sync - skipping")
                continue
            clean, repairs = kml_reader.repair_kml_bytes(raw)
            for rp in repairs:
                log.info("  repaired: %s", rp)
            records, skipped = kml_reader.parse_kml(clean)
            if skipped:
                log.info("  %d placemark(s) without usable geometry skipped", len(skipped))
            out, info = parsers.PARSERS[parser_name](records, label if not sec.get("url") else name)
            total = sum(len(v) for v in out.values())
            log.info("  parsed %d placemarks -> %d features in %d classes", len(records), total, len(out))
            min_rows = sec.getint("min_rows", 1)
            if total < min_rows:
                raise RuntimeError(f"only {total} features parsed (min_rows={min_rows}); not loading")

            if parser_name == "design":
                rp = write_review_report(work, name, out)
                n_review = sum(1 for recs in out.values() for r in recs
                               if r.get("ClassMethod", "").startswith("UNCLASS"))
                log.info("  %d features unclassified - see %s", n_review, rp)
                # make sure every design class exists, even if empty this run
                for kind_classes in design_rules.DESIGN_CLASSES.values():
                    for c in kind_classes:
                        out.setdefault(c, [])

            if args.dry_run:
                folder = write_csvs(work, name, out)
                for fc, recs in sorted(out.items()):
                    log.info("  %-28s %6d", fc, len(recs))
                log.info("  dry run: CSVs written to %s", folder)
                continue

            if writer is None:
                writer = GdbWriter(cfg)
            for fc, full_name in sorted(fc_names_for(parser_name, sec, out).items()):
                writer.replace(name, parser_name, full_name, fc, out[fc], force=args.force)
            state[name] = {"sha1": fingerprint, "synced": dt.datetime.now().isoformat(timespec="seconds")}
            save_state(work, state)
        except Exception as e:
            exit_code = 1
            log.exception("  FAILED: %s", e)
            if writer:
                writer.log_row(name, "", 0, "FAILED", str(e))
    log.info("Done.")
    return exit_code


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="path to config.ini (default: next to this script, or $SENAWAVE_SYNC_CONFIG)")
    ap.add_argument("--source", nargs="*", help="only these sources (names from config.ini)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--test-login", action="store_true")
    sys.exit(run(ap.parse_args()))


if __name__ == "__main__":
    main()
