@echo off
REM Runs the Senawave GIS sync with ArcGIS Pro's Python. Used by Task Scheduler.
cd /d "%~dp0"
"C:\Program Files\ArcGIS\Pro\bin\Python\scripts\propy.bat" senawave_sync.py %*
