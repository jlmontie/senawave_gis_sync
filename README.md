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

The code lives in `C:\Users\jessem\Code\senawave_sync` and is tracked in git. Data does not: the geodatabase and the working files live under `C:\GIS\Senawave\`, outside the repo.

**1. Create your local settings file.** `config.ini` is git-ignored so paths, URLs and machine-specific settings never get committed. Copy the template once:

```
cd C:\Users\jessem\Code\senawave_sync
copy config.example.ini config.ini
```

**2. Edit `config.ini`:**

- `gdb`: where the geodatabase should live.
- `[source:design] path`: the NAS path to `Q-NETWORK LINK.kmz`. **Write it without quotes**, even though it contains spaces - an INI file keeps quotes as part of the value. Use the full `\\server\share\...` form rather than a mapped drive letter, because mapped drives don't exist in scheduled runs:

  ```
  path = \\NAS\Users Shared\Quentin M\Q-NETWORK LINK.kmz
  ```

  To confirm the server name, open the mapped drive in File Explorer and look at the address bar, or run `net use` in Command Prompt: the Remote column shows the `\\server\share` each letter points to.
- `[source:address_ids] url` and `[source:autobill] url`: the two portal links.
- `[portal]`: leave `auth = basic`. The portal uses the browser's own sign-in box, which is HTTP Basic authentication, so there are no form fields to look up. (If it ever changes to a real login web page, switch to `auth = form` and fill in the commented-out settings.)

**3. Store your portal login** as Windows user environment variables. Open **Command Prompt** and run:

```
setx SENAWAVE_PORTAL_USER "your-username"
setx SENAWAVE_PORTAL_PASSWORD "your-password"
```

`setx` writes the values for future programs only. **Any window that was already open, including the ArcGIS Python Command Prompt, keeps its old environment and can't see them** - this is the usual reason for a "credentials not found" error. Close and reopen the prompt after running `setx`.

The script also reads the values straight from the Windows registry, so it usually works even in a window that was open at the time. To see what is visible from where:

```
python senawave_sync.py --check-env
```

It prints which of the three places hold a value and masks the password.

If you'd rather not use environment variables, put the credentials in a file outside the repo instead, at `%USERPROFILE%\.senawave_sync\credentials.ini`:

```
[portal]
username = your-username
password = your-password
```

Restrict it to your account (right-click > Properties > Security) since it holds a plain-text password. You can point somewhere else with `credentials_file` under `[portal]` in `config.ini`.

When nothing is stored and you're running by hand, the script asks for the username and password at the prompt. Scheduled runs can't do that, so use `--no-prompt` there to fail fast instead of hanging.

**4. Test without touching ArcGIS.** Open the **Python Command Prompt** (Start menu > ArcGIS) and run:

```
cd C:\Users\jessem\Code\senawave_sync
python senawave_sync.py --test-login
python senawave_sync.py --dry-run
```

Then open `C:\GIS\Senawave\sync_work\review_design.csv` in Excel. Rows marked `NeedsReview = YES` are the ones to check.

`--test-login` prints `LOGIN OK` and the size of each feed it could download. If it reports HTTP 401, the username or password is wrong; HTTP 403 usually means the account can reach the portal but not that feed. You can always fall back to `path =` instead of `url =` with hand-downloaded files; everything else still works.

**5. Run the first real sync with ArcGIS Pro closed**, since it creates the feature classes:

```
python senawave_sync.py
```

**6. Build the project.** Open ArcGIS Pro, open a map, and in the **Python** window run:

```python
exec(open(r"C:\Users\jessem\Code\senawave_sync\add_layers_to_map.py").read())
```

It reads the geodatabase path from your `config.ini`, so there is nothing to edit in it.

Then run the symbology script in the same window:

```python
exec(open(r"C:\Users\jessem\Code\senawave_sync\apply_symbology.py").read())
```

and **save the project**. Symbology is stored in the project, not in the data, so the nightly sync never disturbs it.

## Symbology

Color says what a feature **is**; line pattern says whether it **exists yet**. Hues come from the Okabe-Ito colorblind-safe palette, so layers stay distinguishable for red-green color vision deficiency and in grayscale printing.

| Layer | Color | Notes |
|---|---|---|
| Conduit / UG Fiber | vermillion `213,94,0` | 2.0 pt, the main line on the map |
| Drops | teal `0,158,115` | 1.2 pt, hidden beyond 1:15,000 |
| Aerial Fiber | ultra blue `0,77,168` | 1.8 pt |
| Vaults / Handholes | amber squares | size by `Subtype`: small 4 pt, medium 6, large 9; drop vaults are circles; vaults holding a splice case are purple |
| Splice Cases | purple diamonds `204,121,167` | aerial cases are ultra blue triangles, matching aerial fiber |
| Poles | gray circles | |
| Sites / MDUs | white stars, dark outline | reads on both light basemaps and imagery |
| Drop / Case Coverage | hollow, slate outline | reference only, stays out of the way |
| Project Areas | hollow, dark slate outline | |
| Syringa | muted lilac | third-party plant, deliberately recessive |
| Address IDs | green / gold / light gray | by `FiberStatus` |
| AutoBill Customers | dark green / sky blue / light gray | active / lead / closed |
| Anything "(review)" | magenta | deliberately loud, so misfiled features stand out |

Line pattern comes from `StatusHint`:

| Pattern | Meaning |
|---|---|
| solid | constructed or existing |
| dashed | planned, to be built, or in design |
| fine dots, gray | abandoned |

Point layers are hidden when zoomed far out so the map stays readable: vaults, splice cases and poles past 1:30,000, drops past 1:15,000, customers past 1:50,000.

To change anything, edit the palette and `LAYERS` tables at the top of `apply_symbology.py` and run it again. It also writes `.lyrx` layer files into a `layers\` folder, so the same styling can be reused in another project with **Import Symbology** or by dragging them in.

## Scheduling (Task Scheduler)

1. Open **Task Scheduler** and choose **Create Task**. Don't use the basic wizard.
2. **General** tab: name it `Senawave GIS Sync`. Select **Run whether user is logged on or not**, using your own Windows account. The environment variables belong to that account.
3. **Triggers** tab: Daily at 5:00 AM. Optionally tick **Repeat task every 1 hour** during work hours.
4. **Actions** tab:
   - Program: `C:\Users\jessem\Code\senawave_sync\run_sync.bat`
   - Add arguments: `--no-prompt`
   - Start in: `C:\Users\jessem\Code\senawave_sync`
5. **Conditions** tab: tick **Start only if the following network connection is available**, so the NAS can be reached.

Sources that haven't changed since the last run are skipped automatically, so frequent runs are cheap. The `SyncLog` table in the geodatabase shows when each layer last loaded.

## Day-to-day

- **Pro can stay open** during syncs. Layers pick up changes on the next redraw.
- **Adding fields or new feature classes** needs Pro closed. If a sync logs "could not add field", run it again with Pro closed.
- **Safety check:** if a new download has less than half the rows already loaded, for example because the portal returned a login page or the NAS copy was half-saved, the load is **skipped** and existing data kept. Use `--force` to override when the drop is real.
- Logs are written to `sync_work\sync.log`. Each run records which of the credential sources it used.

## Working with the repo

| File | Tracked in git? | What it is |
|---|---|---|
| `*.py`, `run_sync.bat`, `README.md` | yes | the tool |
| `config.example.ini` | yes | template with placeholder paths |
| `config.ini` | **no** | your real paths, URLs and settings |
| `sync_work\` | **no** | logs, review reports, dry-run CSVs, sync state |
| geodatabase | **no** | lives in `C:\GIS\Senawave\` |

Credentials are never in the repo. They come from the `SENAWAVE_PORTAL_USER` and `SENAWAVE_PORTAL_PASSWORD` environment variables.

`config.ini` was committed in the first push, before the template existed. Untrack it once, keeping your local copy:

```
git rm --cached config.ini
git add .gitignore .gitattributes config.example.ini
git commit -m "Untrack local config; add template and gitignore"
git push
```

**On another machine**, or after a fresh clone:

```
git clone <your repo url> senawave_sync
cd senawave_sync
copy config.example.ini config.ini
```

then edit `config.ini` and set the two environment variables. The only dependency beyond ArcGIS Pro's Python is `requests`, which Pro already includes.

To run from a different folder, or to keep several configs, point at one explicitly:

```
python senawave_sync.py --config D:\configs\senawave_prod.ini
```

or set a `SENAWAVE_SYNC_CONFIG` environment variable. Relative `gdb` and `work_folder` paths in a config are resolved against the repo folder.

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
python senawave_sync.py --check-env          show where credentials are visible from
python senawave_sync.py --no-prompt          never ask interactively (use in scheduled runs)
```

## Longer term

The portal already stores this data in a database. Ask whoever maintains it for a **GeoJSON or CSV endpoint with an API key**. That would remove the login step and the KML repair step entirely. Only the feed-parsing functions in `parsers.py` would need to change.
