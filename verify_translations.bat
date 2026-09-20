@echo off
setlocal
rem ============================================================
rem  Kenshi RU - VERIFY TRANSLATIONS (read-only by default)
rem  Checks every mod in the translation cache (state/) row-by-row:
rem    empty (no translation), echo (ru == en), latin,
rem    lost placeholders, and whether mods\ has the RU .mod
rem  usage:
rem    verify_translations.bat                 - check ALL cached mods (read-only, 0 LLM)
rem    verify_translations.bat --details       - + print bad rows (en => ru)
rem    verify_translations.bat "Pocket Change" - only matching name / id / hash
rem    verify_translations.bat --fix           - FIX bad rows (re-translate via LLM)
rem    verify_translations.bat --fix "Factions"- fix one specific mod
rem    verify_translations.bat --purge         - delete cache + our mods\ copy of mods
rem                                              matching exclude.txt (NO LLM)
rem  exit codes: 0 = clean, 1 = problems found, 2 = empty cache, 3 = fix errors
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
%PY% "%ROOT%verify_translations.py" %*
set "RC=%errorlevel%"
echo.
echo finished, exit code %RC%
pause
endlocal
exit /b %RC%
