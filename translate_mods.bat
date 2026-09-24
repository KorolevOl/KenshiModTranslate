@echo off
setlocal
rem ============================================================
rem  Kenshi RU-mod-translation launcher (foreground, resumable)
rem  usage:
rem    translate_mods.bat                         - MENU: choose 1) all  2) steam  3) mods
rem    translate_mods.bat --steam                 - same as above (explicit)
rem    translate_mods.bat --mods                  - ALL mods kenshi\mods\<mod>
rem    translate_mods.bat --all                   - Steam Workshop + kenshi\mods\<mod>
rem    translate_mods.bat "Pocket Change" 1140742609
rem    translate_mods.bat "rebirth"               - built-in (kenshi\data, always IN-PLACE)
rem    translate_mods.bat --list-file mods.txt
rem    translate_mods.bat --temperature 0.3 "Mymod" - override config temperature
rem    translate_mods.bat --force "Pocket Change" - retranslate even if cached
rem    translate_mods.bat --include-excluded "X"  - include listed mod
rem    translate_mods.bat "Mod name" --lines "12,40-55" - retranslate ONLY those CSV line numbers
rem    translate_mods.bat "Mod name" --text "Whetbone"  - retranslate lines matching text
rem    translate_mods.bat "Mod name" --lines 5 --text "cloud" - combine both
rem  ================================================================
rem  2026-09-24 NEW ALGORITHM (default for Workshop mods):
rem    Translation is NOT written into the .mod (Steam author update
rem    would wipe it). Instead a SEPARATE RU overlay mod is built:
rem      kenshi\mods\<Name> RUS\<Name> RUS.mod   (OWN records only,
rem                                              keepOnly = 4th apply arg)
rem    and its LINE is inserted into data\__mods.list RIGHT AFTER the
rem    original mod line (later in list wins by object-ID; the game
rem    enables it itself). Auto-backup of __mods.list -> T:\ before any
rem    edit. The original EN .mod is never touched: author updates keep
rem    working, the translation survives them.
rem    FLAGS: --no-overlay (cache+CSV only, no overlay) | --in-place (old)
rem    Rollback overlay : python overlay.py uninstall <mod-name>
rem    List overlays    : python overlay.py list
rem  ============================================================
set "ROOT=%~dp0"
set "PY=python"
where %PY% >nul 2>nul
if errorlevel 1 (
  echo [env] python not found in PATH
  pause
  exit /b 1
)
cd /d "%ROOT%"
%PY% "%ROOT%translate_mods.py" %*
set "RC=%errorlevel%"
echo.
echo finished, exit code %RC% (progress is saved - run the same command again to resume)
pause
exit /b %RC%