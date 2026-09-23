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
rem    translate_mods.bat "rebirth"               - built-in (kenshi\data)
rem    translate_mods.bat --list-file mods.txt
rem    translate_mods.bat --temperature 0.3 "Mymod" - override config temperature
rem    translate_mods.bat --force "Pocket Change" - retranslate even if cached
rem    translate_mods.bat --include-excluded "X"  - include listed mod
rem  NOTE: built-in game mods (kenshi\data: rebirth, Dialogue, Newwworld)
rem  are NEVER part of "translate ALL" - request them by name.
rem  --force can also be set in config.json: "force_retranslate": true
rem  Ctrl+C stops it safely; run again to resume (progress saves)
rem ============================================================
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