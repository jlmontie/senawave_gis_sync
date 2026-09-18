# Senawave GIS Sync

This tool keeps a file geodatabase up to date from Senawave's KML and KMZ sources. Your ArcGIS Pro project reads the geodatabase, so the layers stay current without re-adding KMZs.

| Source | Where it comes from | Becomes |
|---|---|---|
| `design` | `Q-NETWORK LINK.kmz` on the NAS | `Design_*` feature classes, split by **feature type** instead of by project folder |
| `address_ids` | portal `generate_kml.php` | `Cust_AddressIDs`, with each popup line (SWAID, Fiber Status, Footprint, ParentNode...) as a real field |
| `autobill` | portal AutoBill feed | `Cust_AutoBillCustomers`, with CusID, status, connection type and node as fields |

The tool also repairs the broken output from the portal: invalid UTF-8 characters and the undeclared `gx:` namespace.

## How the design KMZ is restructured

The project and phase folders don't disappear. They become **fields** (`Folder1`, `Folder2`, `Folder3`, `LeafFolder`, `FolderPath`, `Phase`, `JobNumber`), so you can still filter by project. Meanwhile every handhole sits in one layer.

| Feature class | Contents | Useful fields |
|---|---|---|
| `Design_Vaults` | small, medium and large vaults, quazites, HDPE, drop vaults, crew "small box"/"big box" | `Subtype` |
| `Design_SpliceCases` | aerial and underground splice cases, slack loops, cabinets | `Subtype` |
| `Design_Poles` | pole surveys, RMP submissions | |
| `Design_Conduit` | conduit, conduit/fiber, microduct, backbone, crew production | `ConduitSize`, `StatusHint` |
| `Design_Drops` | drop conduit and fiber, aerial and UG drops | `Placement` |
| `Design_AerialFiber` | aerial lines, strand, mainline | |
| `Design_ServiceAreas` | drop and case coverage polygons | |
| `Design_ProjectAreas` | phase, HOA and work-assignment polygons | |
| `Design_Other*` | items that couldn't be classified, plus RMP paths and roads | `ClassMethod` |
| `Syringa_Points/Lines/Polygons` | the SYRINGA folder (third-party data) with all its attributes | `Layer` |

Each feature records **how** it was classified in `ClassMethod`:

- `folder: <name>` means a folder name matched a rule.
- `name` means the placemark's own name matched.
- `style (inferred)` means it uses the same icon or line style as features already classified by folder.
- `UNCLASSIFIED - review` means nothing matched.

On the sample KMZ, 24,588 features were loaded and **489 (2%) are unclassified**. Most of those are lines in crew-production and phase folders that have no type folder.

`StatusHint` is a best guess from folder words such as TO BE BUILT, NOT CONSTRUCTED, PRODUCTION, EXISTING or ABANDONED. Treat it as a hint, not a verified status.

---

## Setup (one time)

**1. Copy the folder** to `C:\GIS\Senawave\senawave_sync\`.

**2. Edit `config.ini`:**

- `gdb`: where the geodatabase should live.
- `[source:design] path`: the NAS path to `Q-NETWORK LINK.kmz`, e.g. `\\NAS01\Engineering\Google Earth\Q-NETWORK LINK.kmz`.
- `[source:address_ids] url` and `[source:autobill] url`: the two portal links.
- `[portal]`: the login page URL and the form's field names. To find the field names in Chrome, open the login page, right-click the username box, choose **Inspect**, and copy its `name="..."` value. Do the same for the password box.

**3. Store your portal login** as Windows user environment variables. Open **Command Prompt** and run:

```
setx SENAWAVE_PORTAL_USER "your-username"
setx SENAWAVE_PORTAL_PASSWORD "your-password"
```

Close and reopen the prompt afterwards. The password is never written to a file.

**4. Test without touching ArcGIS.** Open the **Python Command Prompt** (Start menu > ArcGIS) and run:

```
cd C:\GIS\Senawave\senawave_sync
python senawave_sync.py --test-login
python senawave_sync.py --dry-run
```

Then open `C:\GIS\Senawave\sync_work\review_design.csv` in Excel. Rows marked `NeedsReview = YES` are the ones to check.

If the login fails, use `path =` instead of `url =` with hand-downloaded files for now. Everything else still works.

**5. Run the first real sync with ArcGIS Pro closed**, since it creates the feature classes:

```
python senawave_sync.py
```

**6. Build the project.** Open ArcGIS Pro, open a map, and in the **Python** window run:

```python
exec(open(r"C:\GIS\Senawave\senawave_sync\add_layers_to_map.py").read())
```

Then set symbology the way you like it and **save the project**. Later syncs only replace rows, so your symbology, labels and definition queries stay.

## Scheduling (Task Scheduler)

1. Open **Task Scheduler** and choose **Create Task**. Don't use the basic wizard.
2. **General** tab: name it `Senawave GIS Sync`. Select **Run whether user is logged on or not**, using your own Windows account. The environment variables belong to that account.
3. **Triggers** tab: Daily at 5:00 AM. Optionally tick **Repeat task every 1 hour** during work hours.
4. **Actions** tab:
   - Program: `C:\GIS\Senawave\senawave_sync\run_sync.bat`
   - Start in: `C:\GIS\Senawave\senawave_sync`
5. **Conditions** tab: tick **Start only if the following network connection is available**, so the NAS can be reached.

Sources that haven't changed since the last run are skipped automatically, so frequent runs are cheap. The `SyncLog` table in the geodatabase shows when each layer last loaded.

## Day-to-day

- **Pro can stay open** during syncs. Layers pick up changes on the next redraw.
- **Adding fields or new feature classes** needs Pro closed. If a sync logs "could not add field", run it again with Pro closed.
- **Safety check:** if a new download has less than half the rows already loaded, for example because the portal returned a login page or the NAS copy was half-saved, the load is **skipped** and existing data kept. Use `--force` to override when the drop is real.
- Logs are written to `sync_work\sync.log`.

## Fixing classifications

Everything is controlled by **`design_rules.py`**:

- `FOLDER_RULES`: add a folder-name pattern, e.g. a new folder called `FLOWERPOTS`:
  ```python
  (r"FLOWERPOTS?", "point", "Vaults", "Flowerpot", False),
  ```
- `NAME_RULES`: match on placemark names.
- `THIRD_PARTY_FOLDERS`: other companies' data to keep separate.

After editing, run `--dry-run`, recheck `review_design.csv`, and then do a normal run with `--force --source design`.

## Commands

```
python senawave_sync.py                      sync everything that changed
python senawave_sync.py --source design      one source
python senawave_sync.py --force              reload even if unchanged / bypass the row-count check
python senawave_sync.py --dry-run            CSVs + review report only (no ArcGIS needed)
python senawave_sync.py --test-login         check portal credentials
```

## Longer term

The portal already stores this data in a database. Ask whoever maintains it for a **GeoJSON or CSV endpoint with an API key**. That would remove the login step and the KML repair step entirely. Only the feed-parsing functions in `parsers.py` would need to change.
