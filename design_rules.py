"""
design_rules.py - How features in the Q-NETWORK LINK design KMZ are sorted into
feature classes.  THIS IS THE FILE YOU EDIT when the drafters add a new folder
name or the review report shows something landing in the wrong place.

How a feature is classified (first step that succeeds wins):
  1. FOLDER_RULES  - folder names, checked from the feature's own folder upward.
                     Rules marked leaf_only=True only look at the feature's own
                     folder (used for vague words like "FIBER" or "BACKBONE").
  2. NAME_RULES    - the placemark's own name (e.g. crews label points "small box").
  3. Style         - features drawn with the same icon/line style as features that
                     were classified by folder (e.g. yellow open-diamond icon = small
                     vault).  Learned automatically on every run.
  4. Fallback      - OtherPoints / OtherLines / OtherPolygons, flagged for review.

Regular expressions are case-insensitive.  Tip: test a pattern at regex101.com.
"""
import re

# Top-level folders that hold another company's data. Everything under them goes
# to its own feature classes (<Prefix>_Points / _Lines / _Polygons) and keeps all
# of that company's ExtendedData attributes as real fields.
THIRD_PARTY_FOLDERS = {
    "SYRINGA": "Syringa",
}

# Folders to skip entirely (reference images, scratch folders, etc.)
SKIP_FOLDER_RX = re.compile(r"^(OVERLAYS?)$", re.I)

# (pattern, geometry, feature class, subtype, leaf_only)
#   geometry: 'point' | 'line' | 'polygon' | 'any'
FOLDER_RULES = [
    # ---------------- Polygons
    (r"DROP.*POLY|CASE.*POLY|DROP POLYGON|CASE COVERAGE|LIU PORT",   "polygon", "ServiceAreas", "Drop/case coverage", False),
    (r"PHASE|WORK ASSIGN|HOA|AREA|FOREST SERVICE|BACKBONE POLY|EXCLUSION", "polygon", "ProjectAreas", "", False),
    (r"BUILDING|HOMES|MDU",                                          "polygon", "ProjectAreas", "Building", False),
    (r"ACCESS.?POINT",                                              "polygon", "OtherPolygons", "Access point footprint", False),

    # ---------------- Vaults / handholes (points)
    (r"SPLICE CASES?/ ?MV|MV/ ?SPLICE|MED(IUM)? VAULTS?/ ?(SPLICE )?CASES?|MEDIUM VAULT/ ?SPLICE",
                                                                     "point", "Vaults", "Medium w/ splice case", False),
    (r"SMALL (HDPE )?VAULTS?|SMALL QUAZITES?|SMALL BOX|PULL POINT",  "point", "Vaults", "Small", False),
    (r"MED(IUM)? (HDPE )?VAULTS?|MEDIUM QUAZITES?",                  "point", "Vaults", "Medium", False),
    (r"BIG .*VAULTS?|LARGE VAULTS?",                                 "point", "Vaults", "Large", False),
    (r"DROP VAULTS?",                                                "point", "Vaults", "Drop vault", False),
    (r"QUAZITES?|VAULTS?|HANDHOLES?|HAND HOLES?|\bBOXES\b",          "point", "Vaults", "", False),

    # ---------------- Splice cases / enclosures (points)
    (r"AERIAL (SPLICE )?CASE",                                       "point", "SpliceCases", "Aerial", False),
    (r"SPLICE|\bCASES?\b|CASESS|SLACK|DMARC|CABINETS?|ENCLOSURE",    "point", "SpliceCases", "", False),

    # ---------------- Poles (points)
    (r"POLES?\b|POLE SURVEY|SUBMISSION",                             "point", "Poles", "", False),
    (r"RMP STUBB?S",                                                 "point", "OtherPoints", "RMP stub", False),
    (r"MDU|APPART|APARTMENT|HOMES|NETPOWER|TOWER",                   "point", "Sites", "", False),

    # ---------------- Lines
    (r"DROP|U\.G\.? DROPS",                                          "line", "Drops", "", False),
    (r"AERIAL|STRAND|POLE LINES?|SUBMISSION LINES",                  "line", "AerialFiber", "", False),
    (r"RMP PATHS?|POWER TRENCH|IRRIGA|WATER LINE|PRIVATE ROADS?|CROSSINGS?", "line", "OtherLines", "Utility/reference", False),
    (r"PRODUCTION|UNDERGROUND WORK",                                 "line", "Conduit", "Crew production", False),
    (r"CO?U?N?DUI?T|MICRODUCT|\d*\.?\d+(/\d+)?\s*\"",                 "line", "Conduit", "", False),
    (r"FIBER|BACKBONE|LONG ?HAUL|ROUTE|PATHS?\b|UNDERGROUND|MAINLINE|FEED|SPUR|EXT\b|EXP|CABLE",
                                                                     "line", "Conduit", "", True),
]

# (pattern on placemark name, geometry, feature class, subtype)
NAME_RULES = [
    (r"^\s*(ex\.?\s+)?small( box)?\s*$|^\s*small box",               "point", "Vaults", "Small"),
    (r"^\s*(ex\.?\s+)?big box",                                       "point", "Vaults", "Big box"),
    (r"^Access Structure:",                                           "point", "Vaults", ""),
    (r"^Pole\b|^POLE #",                                              "point", "Poles", ""),
    (r"conduit (start|end)|(start|end) conduit",                      "point", "OtherPoints", "Conduit start/end"),
    (r"^Fiber Cable:",                                                "line",  "Conduit", "Fiber cable"),
    (r"^DROP CONDUIT",                                                "line",  "Drops", ""),
]

# Style learning thresholds: a style is trusted when at least STYLE_MIN_COUNT
# folder-classified features use it and STYLE_MIN_SHARE of them agree.
STYLE_MIN_COUNT = 20
STYLE_MIN_SHARE = 0.90

# Icons/styles that are Google Earth defaults and say nothing about what the
# feature is - never learn from these.
STYLE_IGNORE_RX = re.compile(r"icon=ylw-pushpin\.png|^line=None\|w=None$", re.I)

# Feature classes the design data can land in, by geometry
DESIGN_CLASSES = {
    "point":   ["Vaults", "SpliceCases", "Poles", "Sites", "OtherPoints"],
    "line":    ["Conduit", "Drops", "AerialFiber", "OtherLines"],
    "polygon": ["ServiceAreas", "ProjectAreas", "OtherPolygons"],
}
FALLBACK = {"point": "OtherPoints", "line": "OtherLines", "polygon": "OtherPolygons"}

# ============================================================================
# Helpers (normally no need to edit below)
# ============================================================================
_FOLDER_RULES = [(re.compile(p, re.I), g, fc, st, lo) for p, g, fc, st, lo in FOLDER_RULES]
_NAME_RULES = [(re.compile(p, re.I), g, fc, st) for p, g, fc, st in NAME_RULES]

def match_folder(path, kind):
    """path excludes the Document name. Returns (fc, subtype, folder) or None."""
    for depth, folder in enumerate(reversed(path)):
        for rx, g, fc, st, leaf_only in _FOLDER_RULES:
            if leaf_only and depth > 0:
                continue
            if g in (kind, "any") and rx.search(folder):
                if fc in DESIGN_CLASSES[kind]:
                    return fc, st, folder
    return None

def match_name(name, kind):
    for rx, g, fc, st in _NAME_RULES:
        if g in (kind, "any") and rx.search(name or ""):
            return fc, st
    return None

_SIZE_RX = re.compile(r'(\d*\.?\d+(?:/\d+)?)\s*"')
def conduit_size(path, name=""):
    for text in [name] + list(reversed(path)):
        m = _SIZE_RX.search(text or "")
        if m:
            return m.group(1).replace("//", "/") + '"'
    if any(re.search(r"MICRODUCT", f, re.I) for f in path):
        return "Microduct"
    return ""

def status_hint(path):
    s = " > ".join(path).upper()
    if "ABANDON" in s:
        return "Abandoned"
    if re.search(r"NOT CONSTRUCTED|TO BE BUILT|NEEDED|PROPOSED|FUTURE|\bTBD\b|\?\?", s):
        return "Planned"
    if re.search(r"PRODUCTION|AS.?BUILT|COMPLETED?\b", s):
        return "Constructed (crew production)"
    if re.search(r"\bEXISTING\b", s):
        return "Existing"
    if re.search(r"DESIGN|APPROVED|PLAN\b", s):
        return "Design"
    return ""

def placement(path, fc, subtype, name=""):
    s = (" > ".join(path) + " " + (name or "")).upper()
    if fc == "AerialFiber" or subtype == "Aerial" or "AERIAL" in s:
        return "Aerial"
    if fc in ("Vaults", "Conduit") or re.search(r"UNDERGROUND|U\.G|CONDUIT|VAULT|QUAZITE|BORE", s):
        return "Underground"
    return ""

_PHASE_RX = re.compile(r"\b(?:PHASE|P)\s*(\d{1,2}\s?[A-Z]?\b|\?\?)", re.I)
def phase(path):
    for f in reversed(path):
        m = _PHASE_RX.search(f)
        if m:
            return m.group(1).replace(" ", "").upper()
    return ""

def job_number(path):
    for f in reversed(path):
        m = re.search(r"#\s?(\d{5})\b", f)
        if m:
            return m.group(1)
    return ""
