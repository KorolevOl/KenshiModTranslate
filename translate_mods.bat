@echo off
setlocal
rem ============================================================
rem  Kenshi RU-mod-translation launcher (foreground, resumable)
rem  usage:
rem    translate_mods.bat                        - ask: translate ALL workshop mods?
rem    translate_mods.bat "Pocket Change" 1140742609
rem    translate_mods.bat --list-file mods.txt
rem    translate_mods.bat --force "Pocket Change"   - re-translate EVEN IF cached
rem    translate_mods.bat --include-excluded "X"   - translate mod from exclude list
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
