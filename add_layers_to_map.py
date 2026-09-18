"""
add_layers_to_map.py - Run ONCE inside ArcGIS Pro (Python window or a Notebook)
after the first sync. Adds the synced feature classes to the active map in
group layers, symbolized by type, then save your project. After that the
layers stay pointed at the geodatabase and update whenever the sync runs.

    exec(open(r"C:\GIS\Senawave\senawave_sync\add_layers_to_map.py").read())
"""
import os
import arcpy

GDB = r"C:\GIS\Senawave\Senawave_Network.gdb"      # same as config.ini [general] gdb

GROUPS = [
    # (group name, [(feature class, layer name, symbolize-by field)])   drawn top to bottom
    ("Senawave Design", [
        ("Design_Vaults",       "Vaults / Handholes",  "Subtype"),
        ("Design_SpliceCases",  "Splice Cases",        "Subtype"),
        ("Design_Poles",        "Poles",               None),
        ("Design_Sites",        "Sites / MDUs",        None),
        ("Design_OtherPoints",  "Other Points (review)", "ClassMethod"),
        ("Design_Conduit",      "Conduit / UG Fiber",  "StatusHint"),
        ("Design_AerialFiber",  "Aerial Fiber",        None),
        ("Design_Drops",        "Drops",               "Placement"),
        ("Design_OtherLines",   "Other Lines (review)", "ClassMethod"),
        ("Design_ServiceAreas", "Drop / Case Coverage", None),
        ("Design_ProjectAreas", "Project Areas",       None),
        ("Design_OtherPolygons", "Other Polygons (review)", None),
    ]),
    ("Customers", [
        ("Cust_AutoBillCustomers", "AutoBill Customers", "Category"),
        ("Cust_AddressIDs",        "Address IDs",        "FiberStatus"),
    ]),
    ("Syringa (3rd party)", [
        ("Syringa_Points",   "Syringa Splice Points", None),
        ("Syringa_Lines",    "Syringa Fiber",         "Layer"),
        ("Syringa_Polygons", "Syringa Access Pts / Bldgs", "Layer"),
    ]),
]

aprx = arcpy.mp.ArcGISProject("CURRENT")
m = aprx.activeMap
if m is None:
    raise RuntimeError("Open a map view first, then run this again.")

for group_name, layers in reversed(GROUPS):
    try:
        group = m.createGroupLayer(group_name)
    except Exception:
        group = None                                   # older Pro: add flat
    for fc, lyr_name, field in reversed(layers):
        path = os.path.join(GDB, fc)
        if not arcpy.Exists(path):
            print("  (skipping missing)", fc)
            continue
        lyr = m.addDataFromPath(path)
        lyr.name = lyr_name
        if field:
            try:
                sym = lyr.symbology
                sym.updateRenderer("UniqueValueRenderer")
                sym.renderer.fields = [field]
                lyr.symbology = sym
            except Exception as e:
                print("  could not symbolize", lyr_name, e)
        if "(review)" in lyr_name or fc.startswith("Syringa") or fc == "Cust_AddressIDs":
            lyr.visible = False
        if group is not None:
            m.addLayerToGroup(group, lyr)
            m.removeLayer(lyr)
    print("Added group:", group_name)

print("Done - review the layers, then Save the project.")
