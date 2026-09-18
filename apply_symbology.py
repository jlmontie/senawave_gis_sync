r"""
apply_symbology.py - Symbolize the synced layers in the active ArcGIS Pro map.

Scheme
  COLOR says what a feature is.  Every feature type gets its own hue, drawn from
  a colorblind-safe palette (Okabe-Ito), so the layers separate at a glance and
  still separate for the ~8% of men with red-green color vision deficiency.
  LINE PATTERN says whether it exists yet: solid = built or existing,
  dashed = planned or in design, fine dots + gray = abandoned.
  Third-party plant is muted on purpose so it recedes; review layers are loud
  magenta on purpose so misfiled features stand out.

Run it in ArcGIS Pro's Python window after add_layers_to_map.py:

    exec(open(r"C:\Users\jessem\Code\senawave_sync\apply_symbology.py").read())

Then save the project. Symbology lives in the project, not in the data, so the
nightly sync never disturbs it.

Everything is driven by the tables below - edit a number, run it again.
"""
import os
import arcpy

# ---------------------------------------------------------------------------
# Palette (R, G, B) - colorblind-safe hues, one per feature type
# ---------------------------------------------------------------------------
VERMILLION  = [213,  94,   0]     # conduit / underground fiber - the main line
TEAL        = [  0, 158, 115]     # drops
ULTRA_BLUE  = [  0,  77, 168]     # aerial fiber
SKY         = [ 86, 180, 233]     # customer leads
AMBER       = [230, 159,   0]     # vaults / handholes
PURPLE      = [204, 121, 167]     # splice cases
WHITE       = [255, 255, 255]     # sites / MDUs - reads on any basemap
GRAY        = [110, 110, 110]     # poles
GRAY_LIGHT  = [190, 190, 190]     # abandoned, inactive
SLATE       = [138, 146, 160]     # coverage outlines
SLATE_DARK  = [ 95, 105, 120]     # project area outlines
MUTED_LILAC = [150, 130, 175]     # third-party (Syringa) - deliberately recessive
MAGENTA     = [230,   0, 169]     # needs review - deliberately loud
GREEN       = [ 46, 158,  79]
GREEN_DARK  = [ 27, 120,  55]
GOLD        = [230, 167,   0]
OUTLINE     = [ 40,  40,  40]     # marker outlines: near-black reads on any basemap

# Dash patterns by StatusHint. Keyword match, first hit wins.
STATUS_STYLE = [
    ("Abandoned",   {"dash": [2, 3], "color": GRAY_LIGHT}),
    ("Planned",     {"dash": [6, 4]}),
    ("Design",      {"dash": [6, 4]}),
    ("Constructed", {"dash": None}),
    ("Existing",    {"dash": None}),
]
DEFAULT_STATUS = {"dash": None}

# ---------------------------------------------------------------------------
# What each layer gets.  Layer names must match add_layers_to_map.py.
#   line   : color, width, and dashes driven by StatusHint
#   point  : per-value shape/color/size on a field, plus a default
#   polygon: hollow with a colored outline
# ---------------------------------------------------------------------------
LAYERS = {
    "Conduit / UG Fiber": {
        "kind": "line", "color": VERMILLION, "width": 2.0, "status_field": "StatusHint"},
    "Drops": {
        "kind": "line", "color": TEAL, "width": 1.2, "status_field": "StatusHint",
        "min_scale": 15000},           # only draw when zoomed in past 1:15,000
    "Aerial Fiber": {
        "kind": "line", "color": ULTRA_BLUE, "width": 1.8, "status_field": "StatusHint"},
    "Other Lines (review)": {
        "kind": "line", "color": MAGENTA, "width": 1.5, "status_field": None},

    "Vaults / Handholes": {
        "kind": "point", "field": "Subtype", "default": ("Square 1", AMBER, 5),
        "values": {
            "Small":                 ("Square 1",  AMBER,       4),
            "Medium":                ("Square 1",  AMBER,       6),
            "Medium w/ splice case": ("Square 1",  PURPLE,      7),
            "Big box":               ("Square 1",  AMBER,       7),
            "Large":                 ("Square 1",  AMBER,       9),
            "Drop vault":            ("Circle 1",  AMBER,       4),
        },
        "outline": OUTLINE, "min_scale": 30000},
    "Splice Cases": {
        "kind": "point", "field": "Subtype", "default": ("Diamond 1", PURPLE, 7),
        "values": {"Aerial": ("Triangle 1", ULTRA_BLUE, 8)},
        "outline": OUTLINE, "min_scale": 30000},
    "Poles": {
        "kind": "point", "field": None, "default": ("Circle 1", GRAY, 5),
        "outline": OUTLINE, "min_scale": 30000},
    "Sites / MDUs": {
        "kind": "point", "field": None, "default": ("Star 1", WHITE, 12),
        "outline": OUTLINE},
    "Other Points (review)": {
        "kind": "point", "field": None, "default": ("Circle 1", MAGENTA, 5),
        "outline": OUTLINE},

    "Drop / Case Coverage": {"kind": "polygon", "outline": SLATE, "width": 0.7},
    "Project Areas":        {"kind": "polygon", "outline": SLATE_DARK, "width": 1.5},
    "Other Polygons (review)": {"kind": "polygon", "outline": MAGENTA, "width": 1.0},

    "Syringa Fiber":              {"kind": "line", "color": MUTED_LILAC, "width": 1.0, "status_field": None},
    "Syringa Splice Points":      {"kind": "point", "field": None,
                                   "default": ("Circle 1", MUTED_LILAC, 4), "outline": OUTLINE},
    "Syringa Access Pts / Bldgs": {"kind": "polygon", "outline": MUTED_LILAC, "width": 0.7},

    "Address IDs": {
        "kind": "point", "field": "FiberStatus", "default": ("Circle 1", GRAY_LIGHT, 3),
        "values": {
            "Complete to AID":                 ("Circle 1", GREEN,      4),
            "Ready at Servicing Splice Case":  ("Circle 1", GOLD,       4),
            "Servicing Splice Case Not Ready": ("Circle 1", GRAY_LIGHT, 3),
        },
        "outline": OUTLINE, "min_scale": 30000},
    "AutoBill Customers": {
        "kind": "point", "field": "Category", "default": ("Circle 1", GRAY_LIGHT, 4),
        "values": {
            "Active Customers": ("Circle 1", GREEN_DARK, 5),
            "Leads":            ("Circle 1", SKY,        4),
            "Closed Accounts":  ("Circle 1", GRAY_LIGHT, 3),
        },
        "outline": OUTLINE, "min_scale": 50000},
}

LYRX_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__))
                           if "__file__" in globals() else os.getcwd(), "layers")


# ---------------------------------------------------------------------------
def rgb(color, alpha=100):
    return {"RGB": list(color) + [alpha]}


def status_style(value):
    v = (value or "")
    for keyword, style in STATUS_STYLE:
        if keyword.lower() in v.lower():
            return style
    return DEFAULT_STATUS


def set_dashes(lyr, value_to_dash):
    """
    Apply dash patterns through the CIM, which is the only place they live.
    value_to_dash maps a renderer value ("Planned", or None for every class)
    to a dash template like [6, 4], or None for a solid line.
    """
    cim = lyr.getDefinition("V3")
    renderer = getattr(cim, "renderer", None)
    if renderer is None:
        return
    classes = []
    if hasattr(renderer, "groups") and renderer.groups:
        for grp in renderer.groups:
            for cls in grp.classes:
                vals = []
                for v in getattr(cls, "values", []) or []:
                    vals.extend(getattr(v, "fieldValues", []) or [])
                classes.append((vals[0] if vals else "", cls.symbol.symbol))
    elif hasattr(renderer, "symbol"):
        classes.append((None, renderer.symbol.symbol))

    for value, symbol in classes:
        dash = value_to_dash(value)
        for layer in getattr(symbol, "symbolLayers", []) or []:
            if layer.__class__.__name__ != "CIMSolidStroke":
                continue
            if not dash:
                layer.effects = None
                continue
            effect = arcpy.cim.CreateCIMObjectFromClassName("CIMGeometricEffectDashes", "V3")
            effect.dashTemplate = list(dash)
            effect.lineDashEnding = "NoConstraint"
            effect.controlPointEnding = "NoConstraint"
            layer.effects = [effect]
    lyr.setDefinition(cim)


def apply_line(lyr, spec):
    sym = lyr.symbology
    field = spec.get("status_field")
    if field and field in {f.name for f in arcpy.ListFields(lyr.dataSource)}:
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = [field]
        lyr.symbology = sym
        sym = lyr.symbology
        for grp in sym.renderer.groups:
            for itm in grp.items:
                value = itm.values[0][0] if itm.values and itm.values[0] else ""
                style = status_style(value)
                itm.symbol.color = rgb(style.get("color", spec["color"]))
                itm.symbol.width = spec["width"]
                itm.label = value or "(not recorded)"
        lyr.symbology = sym
        set_dashes(lyr, lambda v: status_style(v).get("dash"))
    else:
        sym.updateRenderer("SimpleRenderer")
        sym.renderer.symbol.color = rgb(spec["color"])
        sym.renderer.symbol.width = spec["width"]
        lyr.symbology = sym


def _style_point(symbol, shape, color, size, outline):
    try:
        symbol.applySymbolFromGallery(shape)      # shape lives in the style gallery
    except Exception:
        pass                                      # keep the default shape
    symbol.color = rgb(color)
    symbol.size = size
    try:
        symbol.outlineColor = rgb(outline)
        symbol.outlineWidth = 0.4
    except Exception:
        pass


def apply_point(lyr, spec):
    sym = lyr.symbology
    field = spec.get("field")
    shape, color, size = spec["default"]
    outline = spec.get("outline", OUTLINE)
    if field and field in {f.name for f in arcpy.ListFields(lyr.dataSource)}:
        sym.updateRenderer("UniqueValueRenderer")
        sym.renderer.fields = [field]
        lyr.symbology = sym
        sym = lyr.symbology
        for grp in sym.renderer.groups:
            for itm in grp.items:
                value = itm.values[0][0] if itm.values and itm.values[0] else ""
                s, c, z = spec.get("values", {}).get(value, (shape, color, size))
                _style_point(itm.symbol, s, c, z, outline)
                itm.label = value or "(not recorded)"
        lyr.symbology = sym
    else:
        sym.updateRenderer("SimpleRenderer")
        _style_point(sym.renderer.symbol, shape, color, size, outline)
        lyr.symbology = sym


def apply_polygon(lyr, spec):
    sym = lyr.symbology
    sym.updateRenderer("SimpleRenderer")
    s = sym.renderer.symbol
    s.color = {"RGB": [0, 0, 0, 0]}               # hollow
    try:
        s.outlineColor = rgb(spec["outline"])
        s.outlineWidth = spec.get("width", 1.0)
    except Exception:
        pass
    lyr.symbology = sym


APPLIERS = {"line": apply_line, "point": apply_point, "polygon": apply_polygon}


def main(save_lyrx=True):
    aprx = arcpy.mp.ArcGISProject("CURRENT")
    m = aprx.activeMap
    if m is None:
        raise RuntimeError("Open a map view first, then run this again.")

    done, skipped, failed = [], [], []
    for lyr in m.listLayers():
        if lyr.isGroupLayer or not lyr.isFeatureLayer:
            continue
        spec = LAYERS.get(lyr.name)
        if not spec:
            skipped.append(lyr.name)
            continue
        try:
            APPLIERS[spec["kind"]](lyr, spec)
            if spec.get("min_scale"):
                cim = lyr.getDefinition("V3")
                cim.minScale = spec["min_scale"]   # hidden when zoomed further out
                lyr.setDefinition(cim)
            done.append(lyr.name)
        except Exception as e:
            failed.append((lyr.name, e))

    if save_lyrx and done:
        os.makedirs(LYRX_FOLDER, exist_ok=True)
        for lyr in m.listLayers():
            if lyr.name in done:
                try:
                    safe = "".join(ch if ch.isalnum() else "_" for ch in lyr.name)
                    arcpy.management.SaveToLayerFile(
                        lyr, os.path.join(LYRX_FOLDER, safe + ".lyrx"), "RELATIVE")
                except Exception:
                    pass

    print("Symbolized:", len(done))
    for n in done:
        print("   ", n)
    if skipped:
        print("Skipped (no entry in LAYERS):", ", ".join(skipped))
    for n, e in failed:
        print("FAILED", n, "->", e)
    print("\nReview the map, then SAVE THE PROJECT.")
    if save_lyrx and done:
        print("Layer files written to", LYRX_FOLDER)


main()
