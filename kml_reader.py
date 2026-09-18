"""
kml_reader.py - Read KML/KMZ from a file, NAS path, or portal URL, repair common
corruption, and return a flat list of Placemark records.

Pure standard-library Python (works in ArcGIS Pro's Python and plain Python).

Repairs applied before parsing:
  * Bytes that are not valid UTF-8 (stray Windows-1252 characters such as
    non-breaking spaces or curly quotes) are converted to proper characters.
  * Namespace prefixes that are used but never declared (e.g. <gx:drawOrder>)
    get a declaration added.
  * Control characters that are illegal in XML are removed.
  * Bare '&' characters outside CDATA blocks are escaped.
"""
import codecs
import io
import os
import re
import zipfile
import xml.etree.ElementTree as ET

# ----------------------------------------------------------------------------
# Byte-level repair
# ----------------------------------------------------------------------------
def _cp1252_fallback(err):
    bad = err.object[err.start:err.end]
    return bad.decode("cp1252", errors="replace"), err.end

codecs.register_error("cp1252_fallback", _cp1252_fallback)

_CTRL_RX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_CDATA_RX = re.compile(r"(<!\[CDATA\[.*?\]\]>)", re.S)
_BARE_AMP_RX = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)")


def repair_kml_bytes(raw):
    """Return (clean_utf8_bytes, list_of_repairs_made)."""
    repairs = []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="cp1252_fallback")
        repairs.append("invalid UTF-8 bytes converted from Windows-1252")
    if text.startswith("﻿"):
        text = text[1:]

    n_ctrl = len(_CTRL_RX.findall(text))
    if n_ctrl:
        text = _CTRL_RX.sub("", text)
        repairs.append(f"{n_ctrl} illegal control characters removed")

    # Escape bare ampersands outside CDATA sections
    parts = _CDATA_RX.split(text)
    amp_fixes = 0
    for i in range(0, len(parts), 2):          # even indexes are outside CDATA
        new, n = _BARE_AMP_RX.subn("&amp;", parts[i])
        parts[i], amp_fixes = new, amp_fixes + n
    if amp_fixes:
        text = "".join(parts)
        repairs.append(f"{amp_fixes} bare '&' escaped")

    # Declare any namespace prefixes that are used but not declared
    head_end = text.find(">", text.find("<kml"))
    if head_end > 0:
        head = text[: head_end + 1]
        declared = set(re.findall(r"xmlns:(\w+)=", head))
        used = set(re.findall(r"</?([A-Za-z_]\w*):\w", text)) - {"xml"}
        known = {"gx": "http://www.google.com/kml/ext/2.2",
                 "atom": "http://www.w3.org/2005/Atom",
                 "kml": "http://www.opengis.net/kml/2.2",
                 "xal": "urn:oasis:names:tc:ciq:xsdschema:xAL:2.0"}
        missing = sorted(used - declared)
        if missing:
            decl = "".join(f' xmlns:{p}="{known.get(p, "urn:undeclared:" + p)}"'
                           for p in missing)
            kml_open_end = head.rfind(">")
            text = text[:kml_open_end] + decl + text[kml_open_end:]
            repairs.append("declared missing namespace prefix(es): " + ", ".join(missing))

    # Drop the XML declaration (we hand the parser clean UTF-8 bytes anyway)
    text = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    return text.encode("utf-8"), repairs


# ----------------------------------------------------------------------------
# Loading from file / KMZ / URL
# ----------------------------------------------------------------------------
def _unzip_kmz(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = [n for n in z.namelist() if n.lower().endswith(".kml")]
        if not names:
            raise ValueError("KMZ contains no .kml file")
        main = "doc.kml" if "doc.kml" in names else names[0]
        return z.read(main)


def load_bytes_from_path(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"PK":            # KMZ is a zip file
        raw = _unzip_kmz(raw)
    return raw


def load_bytes_from_url(url, session):
    """Download a KML/KMZ with a requests.Session that is already logged in."""
    r = session.get(url, timeout=300)
    if r.status_code in (401, 403):
        raise ValueError(f"{url} refused the login (HTTP {r.status_code}). Check "
                         "SENAWAVE_PORTAL_USER / SENAWAVE_PORTAL_PASSWORD and the "
                         "[portal] auth setting in config.ini.")
    r.raise_for_status()
    raw = r.content
    if raw[:2] == b"PK":
        raw = _unzip_kmz(raw)
    head = raw[:2000].lower()
    if b"<kml" not in head:
        # Most likely the portal handed back its login page instead of data
        raise ValueError(f"{url} did not return KML (login failed or session expired?)")
    return raw


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------
def _local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.split(":")[-1]


def _child(el, name):
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _child_text(el, name):
    c = _child(el, name)
    return (c.text or "").strip() if c is not None and c.text else ""


def _find_path(el, *names):
    cur = el
    for n in names:
        if cur is None:
            return None
        cur = _child(cur, n)
    return cur


def _parse_coords(text):
    pts = []
    for tok in (text or "").split():
        vals = tok.split(",")
        if len(vals) >= 2:
            try:
                pts.append((float(vals[0]), float(vals[1])))
            except ValueError:
                pass
    return pts


def _collect_geoms(el, out):
    """Walk a geometry element; append ('point'|'line'|'polygon', data)."""
    name = _local(el.tag)
    if name == "Point":
        c = _child(el, "coordinates")
        pts = _parse_coords(c.text if c is not None else "")
        if pts:
            out.append(("point", pts[0]))
    elif name == "LineString":
        c = _child(el, "coordinates")
        pts = _parse_coords(c.text if c is not None else "")
        if len(pts) >= 2:
            out.append(("line", pts))
    elif name == "Polygon":
        rings = []
        outer = _find_path(el, "outerBoundaryIs", "LinearRing", "coordinates")
        if outer is not None:
            rings.append(_parse_coords(outer.text))
        for ib in el:
            if _local(ib.tag) == "innerBoundaryIs":
                c = _find_path(ib, "LinearRing", "coordinates")
                if c is not None:
                    rings.append(_parse_coords(c.text))
        rings = [r for r in rings if len(r) >= 3]
        if rings:
            for r in rings:                      # close rings
                if r[0] != r[-1]:
                    r.append(r[0])
            out.append(("polygon", rings))
    elif name == "MultiGeometry":
        for c in el:
            _collect_geoms(c, out)


def _fmt(pt):
    return f"{pt[0]:.8f} {pt[1]:.8f}"


def geoms_to_wkt(geoms):
    """Return (kind, wkt). Mixed MultiGeometry keeps the most common kind."""
    if not geoms:
        return None, None
    kinds = [g[0] for g in geoms]
    kind = max(set(kinds), key=kinds.count)
    parts = [g[1] for g in geoms if g[0] == kind]
    if kind == "point":
        if len(parts) == 1:
            return kind, f"POINT ({_fmt(parts[0])})"
        return kind, "MULTIPOINT (" + ", ".join(f"({_fmt(p)})" for p in parts) + ")"
    if kind == "line":
        segs = ["(" + ", ".join(_fmt(p) for p in line) + ")" for line in parts]
        return kind, ("LINESTRING " + segs[0]) if len(segs) == 1 else "MULTILINESTRING (" + ", ".join(segs) + ")"
    polys = ["(" + ", ".join("(" + ", ".join(_fmt(p) for p in ring) + ")" for ring in rings) + ")"
             for rings in parts]
    return kind, ("POLYGON " + polys[0]) if len(polys) == 1 else "MULTIPOLYGON (" + ", ".join(polys) + ")"


_TAG_RX = re.compile(r"<[^>]+>")
def html_to_text(html, sep=" | "):
    if not html:
        return ""
    t = re.sub(r"<br\s*/?>|</p>|</h\d>|</div>|</tr>", "\n", html, flags=re.I)
    t = _TAG_RX.sub("", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in t.split("\n")]
    return sep.join(ln for ln in lines if ln)


def _style_info(style_el):
    d = {}
    if style_el is None:
        return d
    href = _find_path(style_el, "IconStyle", "Icon", "href")
    if href is not None and href.text:
        d["icon"] = href.text.strip().split("/")[-1].split("?")[0][:60]
    for key, path in (("icolor", ("IconStyle", "color")), ("lcolor", ("LineStyle", "color")),
                      ("lwidth", ("LineStyle", "width")), ("pcolor", ("PolyStyle", "color"))):
        el = _find_path(style_el, *path)
        if el is not None and el.text:
            d[key] = el.text.strip()
    return d


def parse_kml(clean_bytes):
    """
    Parse repaired KML bytes into a list of dicts:
      path        list of folder names from the top Document down to the placemark
      name        placemark name
      kind        'point' | 'line' | 'polygon'
      wkt         geometry as WKT (WGS84 lon/lat)
      description raw description HTML
      extdata     dict of ExtendedData values
      style_url   styleUrl id (without '#')
      inline_style dict from an inline <Style>, if any
    Also returns styles dict {id: info} and a list of skipped-item notes.
    """
    styles, stylemaps, records, skipped = {}, {}, [], []
    stack = []            # [element, name] for Document/Folder containers

    for event, el in ET.iterparse(io.BytesIO(clean_bytes), events=("start", "end")):
        tag = _local(el.tag)
        if event == "start":
            if tag in ("Document", "Folder"):
                stack.append([el, None])
            continue

        # ----- end events
        if tag == "name" and stack:
            # a <name> that is a direct child of the current container
            cont = stack[-1]
            if cont[1] is None and any(c is el for c in cont[0]):
                cont[1] = (el.text or "").strip()
        elif tag == "Style" and el.get("id"):
            styles[el.get("id")] = _style_info(el)
        elif tag == "StyleMap" and el.get("id"):
            for pair in el:
                if _local(pair.tag) == "Pair" and _child_text(pair, "key") == "normal":
                    stylemaps[el.get("id")] = _child_text(pair, "styleUrl").lstrip("#")
                    break
        elif tag == "Placemark":
            geoms = []
            for c in el:
                if _local(c.tag) in ("Point", "LineString", "Polygon", "MultiGeometry"):
                    _collect_geoms(c, geoms)
            kind, wkt = geoms_to_wkt(geoms)
            path = [s[1] or "" for s in stack]
            name = _child_text(el, "name")
            if wkt is None:
                skipped.append(" > ".join(path + [name or "(unnamed)"]))
            else:
                ext = {}
                ed = _child(el, "ExtendedData")
                if ed is not None:
                    for d in ed.iter():
                        lt = _local(d.tag)
                        if lt == "Data" and d.get("name"):
                            ext[d.get("name")] = _child_text(d, "value")
                        elif lt == "SimpleData" and d.get("name"):
                            ext[d.get("name")] = (d.text or "").strip()
                desc_el = _child(el, "description")
                records.append({
                    "path": path, "name": name, "kind": kind, "wkt": wkt,
                    "description": desc_el.text if desc_el is not None and desc_el.text else "",
                    "extdata": ext,
                    "style_url": _child_text(el, "styleUrl").lstrip("#"),
                    "inline_style": _style_info(_child(el, "Style")),
                    "kml_id": el.get("id") or "",
                })
            el.clear()
        elif tag in ("Document", "Folder"):
            if stack:
                stack.pop()
            el.clear()

    # Resolve styles
    for r in records:
        sid = stylemaps.get(r["style_url"], r["style_url"])
        info = dict(styles.get(sid, {}))
        info.update(r.pop("inline_style"))
        r["style"] = info
    return records, skipped


def style_key(rec):
    """A short signature of how the feature is drawn, used for classification."""
    s = rec.get("style", {})
    if rec["kind"] == "point":
        return f"icon={s.get('icon')}|color={s.get('icolor')}" if s.get("icon") else ""
    if rec["kind"] == "line":
        return f"line={s.get('lcolor')}|w={s.get('lwidth')}" if (s.get("lcolor") or s.get("lwidth")) else ""
    return f"fill={s.get('pcolor')}" if s.get("pcolor") else ""


def read_kml(source, session=None):
    """Load + repair + parse. `source` is a file path/UNC path or an http(s) URL."""
    if re.match(r"https?://", source, re.I):
        if session is None:
            raise ValueError("A logged-in session is required for URLs")
        raw = load_bytes_from_url(source, session)
    else:
        raw = load_bytes_from_path(source)
    clean, repairs = repair_kml_bytes(raw)
    records, skipped = parse_kml(clean)
    return records, repairs, skipped
