"""
parsers.py - Turn parsed KML placemarks into feature-class rows.

Each parser returns a dict: {feature_class_name: [row, ...]}
where a row is a dict of field values plus "SHAPE@WKT".
"""
import json
import re
from collections import Counter, defaultdict

import design_rules as R
from kml_reader import html_to_text, style_key

TEXT_LIMIT = 4000


def _clip(v, n=255):
    v = "" if v is None else str(v)
    return v[:n]


# ============================================================================
# 1. Q-NETWORK LINK design KMZ
# ============================================================================
def parse_design(records, source_name):
    out = defaultdict(list)
    pending = []          # features not classified by folder/name -> try style
    style_votes = defaultdict(Counter)
    third_party = defaultdict(list)
    stats = Counter()

    for rec in records:
        path = rec["path"][1:]             # drop the Document name
        if any(R.SKIP_FOLDER_RX.search(f) for f in path):
            stats["skipped (folder rule)"] += 1
            continue
        top = path[0].upper() if path else ""
        if top in R.THIRD_PARTY_FOLDERS:
            third_party[R.THIRD_PARTY_FOLDERS[top]].append(rec)
            continue

        kind = rec["kind"]
        skey = style_key(rec)
        hit = R.match_folder(path, kind)
        if hit:
            fc, sub, matched = hit
            method = f"folder: {matched}"
            if skey and not R.STYLE_IGNORE_RX.search(skey):
                style_votes[(kind, skey)][(fc, sub)] += 1
        else:
            nh = R.match_name(rec["name"], kind)
            if nh:
                fc, sub = nh
                method = "name"
            else:
                pending.append((rec, path, skey))
                continue
        out[fc].append(_design_row(rec, path, fc, sub, method, skey, source_name))

    # --- learn styles -> class
    trusted = {}
    for key, votes in style_votes.items():
        total = sum(votes.values())
        by_fc = Counter()
        for (fc, sub), n in votes.items():
            by_fc[fc] += n
        fc, n = by_fc.most_common(1)[0]
        if total >= R.STYLE_MIN_COUNT and n / total >= R.STYLE_MIN_SHARE:
            subs = Counter({s: c for (f, s), c in votes.items() if f == fc})
            sub, sn = subs.most_common(1)[0]
            trusted[key] = (fc, sub if sn / n >= R.STYLE_MIN_SHARE else "")

    for rec, path, skey in pending:
        kind = rec["kind"]
        if skey and (kind, skey) in trusted:
            fc, sub = trusted[(kind, skey)]
            method = "style (inferred)"
        else:
            fc, sub, method = R.FALLBACK[kind], "", "UNCLASSIFIED - review"
        out[fc].append(_design_row(rec, path, fc, sub, method, skey, source_name))

    # --- third-party data
    for prefix, recs in third_party.items():
        for rec in recs:
            fc = f"{prefix}_{ {'point': 'Points', 'line': 'Lines', 'polygon': 'Polygons'}[rec['kind']] }"
            path = rec["path"][2:]
            row = {
                "Layer": _clip(path[-1] if path else ""),
                "FolderPath": _clip(" > ".join(path), 500),
                "Name": _clip(rec["name"]),
                "Description": _clip(html_to_text(rec["description"]), TEXT_LIMIT),
                "SourceFile": _clip(source_name),
                "SHAPE@WKT": rec["wkt"],
            }
            for k, v in rec["extdata"].items():
                row["ED:" + k] = v            # becomes a real field in the writer
            out[fc].append(row)

    return dict(out), {"trusted_styles": trusted, "stats": stats}


def _design_row(rec, path, fc, sub, method, skey, source_name):
    ext = rec["extdata"]
    return {
        "FeatureType": fc,
        "Subtype": _clip(sub, 100),
        "Name": _clip(rec["name"]),
        "Folder1": _clip(path[0] if len(path) > 0 else "", 150),
        "Folder2": _clip(path[1] if len(path) > 1 else "", 150),
        "Folder3": _clip(path[2] if len(path) > 2 else "", 150),
        "LeafFolder": _clip(path[-1] if path else "", 150),
        "FolderPath": _clip(" > ".join(path), 500),
        "Phase": R.phase(path),
        "JobNumber": R.job_number(path),
        "StatusHint": R.status_hint(path),
        "Placement": R.placement(path, fc, sub, rec["name"]),
        "ConduitSize": R.conduit_size(path, rec["name"]) if fc in ("Conduit", "Drops") else "",
        "ClassMethod": _clip(method, 200),
        "StyleKey": _clip(skey, 120),
        "Description": _clip(html_to_text(rec["description"]), TEXT_LIMIT),
        "ExtraAttributes": _clip(json.dumps({k: v for k, v in ext.items() if v not in (None, "")}), TEXT_LIMIT) if ext else "",
        "SourceFile": _clip(source_name),
        "SHAPE@WKT": rec["wkt"],
    }


# ============================================================================
# 2. AddressIDs feed (generate_kml.php)
# ============================================================================
_ADDR_KEYS = ["Serviceability", "Fiber Status", "Address", "County", "Address Type",
              "Parcel", "Footprint", "FPSubGroup", "Development", "Subdivision",
              "Lot", "ParentNode"]
_KEY_RX = re.compile(r"^(" + "|".join(re.escape(k) for k in _ADDR_KEYS) + r"):\s*(.*)$")


def _split_br(html):
    parts = re.split(r"<br\s*/?>", html or "", flags=re.I)
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", p)).strip() for p in parts]


_CSZ_RX = re.compile(r"^(.*?),\s*([A-Z]{2})\s*([\d-]*)$")


def _to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def parse_address_ids(records, source_name):
    rows = []
    for rec in records:
        html = rec["description"]
        vals = {k: [] for k in _ADDR_KEYS}
        swaid, ab_id, ab_name, cur = None, None, "", None
        m = re.search(r"SWAID:\s*(\d+)", html)
        if m:
            swaid = int(m.group(1))
        for tok in _split_br(html):
            if not tok or tok.startswith("SWAID"):
                continue
            km = _KEY_RX.match(tok)
            if km:
                cur = km.group(1)
                if km.group(2):
                    vals[cur].append(km.group(2))
                continue
            am = re.match(r"^AB(\d+)\s*(.*)$", tok)
            if am:
                ab_id = _to_int(am.group(1)) or None     # AB0 means no account
                ab_name = am.group(2)
                cur = None
                continue
            if cur:
                vals[cur].append(tok)

        addr = vals["Address"]
        city = state = zipc = ""
        street_parts = list(addr)
        for i in range(len(addr) - 1, 0, -1):          # last "City, ST 12345" line
            cm = _CSZ_RX.match(addr[i])
            if cm:
                city, state, zipc = cm.groups()
                street_parts = addr[:i] + addr[i + 1:]
                break
        street = " ".join(street_parts)
        j = lambda k: " ".join(vals[k]).strip()
        rows.append({
            "SWAID": swaid if swaid is not None else _to_int(rec["kml_id"]),
            "HouseNumber": _clip(rec["name"], 20),
            "Serviceable": _clip(j("Serviceability"), 10),
            "FiberStatus": _clip(j("Fiber Status"), 100),
            "Street": _clip(street, 150), "City": _clip(city, 80),
            "State": _clip(state, 2), "Zip": _clip(zipc, 10),
            "County": _clip(j("County"), 60),
            "AddressType": _clip(j("Address Type"), 50),
            "Parcel": _clip(j("Parcel"), 50),
            "Footprint": _clip(j("Footprint"), 30),
            "FPSubGroup": _clip(j("FPSubGroup"), 30),
            "Development": _clip(j("Development"), 150),
            "Subdivision": _clip(j("Subdivision"), 150),
            "Lot": _clip(j("Lot"), 30),
            "ParentNode": _to_int(j("ParentNode")),
            "AutoBillID": ab_id,
            "AutoBillName": _clip(ab_name, 150),
            "StyleClass": _clip(rec["style_url"], 50),
            "SourceFile": _clip(source_name),
            "SHAPE@WKT": rec["wkt"],
        })
    return {"AddressIDs": rows}, {}


# ============================================================================
# 3. AutoBill customers feed (generate_kml.php)
# ============================================================================
def parse_autobill(records, source_name):
    rows = []
    for rec in records:
        html = rec["description"]
        name = re.search(r"<h3>(.*?)</h3>", html, re.S)
        cus = re.search(r"CusID:\s*<a[^>]*>(\d*)</a>\s*([^<]*)", html)
        toks = _split_br(re.sub(r"<h3>.*?</h3>", "", html, flags=re.S))
        while toks and not toks[0]:
            toks.pop(0)
        while toks and not toks[-1]:
            toks.pop()
        # toks[0] = "CusID: 1234 Residential"; then 1-2 status lines; street;
        # city/state/zip; country; "<type> to:"; node line
        body = toks[1:]
        node_line = body[-1] if body else ""
        conn = body[-2] if len(body) >= 2 else ""
        country = body[-3] if len(body) >= 3 else ""
        csz = body[-4] if len(body) >= 4 else ""
        street = body[-5] if len(body) >= 5 else ""
        statuses = body[:-5] if len(body) > 5 else []
        city = state = zipc = ""
        cm = _CSZ_RX.match(csz)
        if cm:
            city, state, zipc = cm.groups()
        node_id = re.search(r"mcusid=(\d+)#", html.split("to:")[-1]) if "to:" in html else None
        nm = re.match(r"^NODE(\d*)\s*(.*)$", node_line)
        acct_status = next((s for s in reversed(statuses) if s), "")
        rows.append({
            "CusID": _to_int(cus.group(1)) if cus else None,
            "CustomerName": _clip(re.sub(r"<[^>]+>", "", name.group(1)).strip() if name else "", 150),
            "AccountType": _clip(cus.group(2).strip() if cus else "", 100),
            "AccountStatus": _clip(acct_status, 150),
            "SubStatus": _clip("; ".join(s for s in statuses[:-1] if s), 150),
            "Street": _clip(street, 150), "City": _clip(city, 80),
            "State": _clip(state, 2), "Zip": _clip(zipc, 10),
            "ConnectionType": _clip(re.sub(r"\s*to:\s*$", "", conn), 50),
            "NodeID": _to_int(node_id.group(1)) if node_id else (_to_int(nm.group(1)) if nm else None),
            "NodeName": _clip(nm.group(2) if nm else "", 150),
            "Category": _clip(rec["path"][-1] if rec["path"] else "", 50),
            "StyleClass": _clip(rec["style_url"], 50),
            "SourceFile": _clip(source_name),
            "SHAPE@WKT": rec["wkt"],
        })
    return {"AutoBillCustomers": rows}, {}


PARSERS = {"design": parse_design, "address_ids": parse_address_ids, "autobill": parse_autobill}
