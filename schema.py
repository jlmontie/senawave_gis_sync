"""
schema.py - Field definitions for every feature class the sync creates.
(name, type, length)   type: TEXT | LONG | DOUBLE | DATE
"""
DESIGN_FIELDS = [
    ("FeatureType", "TEXT", 40), ("Subtype", "TEXT", 100), ("Name", "TEXT", 255),
    ("Folder1", "TEXT", 150), ("Folder2", "TEXT", 150), ("Folder3", "TEXT", 150),
    ("LeafFolder", "TEXT", 150), ("FolderPath", "TEXT", 500),
    ("Phase", "TEXT", 20), ("JobNumber", "TEXT", 20), ("StatusHint", "TEXT", 50),
    ("Placement", "TEXT", 20), ("ConduitSize", "TEXT", 20),
    ("ClassMethod", "TEXT", 200), ("StyleKey", "TEXT", 120),
    ("Description", "TEXT", 4000), ("ExtraAttributes", "TEXT", 4000),
    ("SourceFile", "TEXT", 255),
]

THIRD_PARTY_FIELDS = [
    ("Layer", "TEXT", 255), ("FolderPath", "TEXT", 500), ("Name", "TEXT", 255),
    ("Description", "TEXT", 4000), ("SourceFile", "TEXT", 255),
]

ADDRESS_ID_FIELDS = [
    ("SWAID", "LONG", None), ("HouseNumber", "TEXT", 20), ("Serviceable", "TEXT", 10),
    ("FiberStatus", "TEXT", 100), ("Street", "TEXT", 150), ("City", "TEXT", 80),
    ("State", "TEXT", 2), ("Zip", "TEXT", 10), ("County", "TEXT", 60),
    ("AddressType", "TEXT", 50), ("Parcel", "TEXT", 50), ("Footprint", "TEXT", 30),
    ("FPSubGroup", "TEXT", 30), ("Development", "TEXT", 150), ("Subdivision", "TEXT", 150),
    ("Lot", "TEXT", 30), ("ParentNode", "LONG", None), ("AutoBillID", "LONG", None),
    ("AutoBillName", "TEXT", 150), ("StyleClass", "TEXT", 50), ("SourceFile", "TEXT", 255),
]

AUTOBILL_FIELDS = [
    ("CusID", "LONG", None), ("CustomerName", "TEXT", 150), ("AccountType", "TEXT", 100),
    ("AccountStatus", "TEXT", 150), ("SubStatus", "TEXT", 150), ("Street", "TEXT", 150),
    ("City", "TEXT", 80), ("State", "TEXT", 2), ("Zip", "TEXT", 10),
    ("ConnectionType", "TEXT", 50), ("NodeID", "LONG", None), ("NodeName", "TEXT", 150),
    ("Category", "TEXT", 50), ("StyleClass", "TEXT", 50), ("SourceFile", "TEXT", 255),
]

GEOM_BY_SUFFIX = {"Points": "POINT", "Lines": "POLYLINE", "Polygons": "POLYGON"}
DESIGN_GEOM = {
    "Vaults": "POINT", "SpliceCases": "POINT", "Poles": "POINT", "Sites": "POINT", "OtherPoints": "POINT",
    "Conduit": "POLYLINE", "Drops": "POLYLINE", "AerialFiber": "POLYLINE", "OtherLines": "POLYLINE",
    "ServiceAreas": "POLYGON", "ProjectAreas": "POLYGON", "OtherPolygons": "POLYGON",
}


def fields_for(parser, fc_base):
    """Return (geometry_type, base_fields) for a feature class produced by a parser."""
    if parser == "address_ids":
        return "POINT", ADDRESS_ID_FIELDS
    if parser == "autobill":
        return "POINT", AUTOBILL_FIELDS
    if fc_base in DESIGN_GEOM:
        return DESIGN_GEOM[fc_base], DESIGN_FIELDS
    suffix = fc_base.rsplit("_", 1)[-1]
    return GEOM_BY_SUFFIX[suffix], THIRD_PARTY_FIELDS
