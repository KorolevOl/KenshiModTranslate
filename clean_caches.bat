@echo off
setlocal
rem ============================================================
rem  Kenshi mod CACHE CLEANER (state/ + *.translate.csv)
rem  usage:
rem    clean_caches.bat                 dry-run: list what would be deleted
rem    clean_caches.bat --yes           delete (asks y/N confirmation)
rem    clean_caches.bat --state-only    only state/
rem    clean_caches.bat --csv-only      only *.translate.csv
rem  Never touches: .mod, .orig_*.backup (EN rollback),
rem                 *.revert_* (RU copies), code/DLL
rem ============================================================
python "%~dp0clean_caches.py" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
