@echo off
setlocal
rem ============================================================
rem  Kenshi RU - FIX TRANSLATIONS (re-translate ONLY broken rows)
rem  Run verify_translations --fix: finds rows in the cache that are
rem  empty / echo / no-Cyrillic / lost placeholders and re-asks the LLM
rem  for exactly those rows, then re-applies the RU .mod.
rem  Already-good rows are untouched (saves tokens, avoids reshuffling).
rem  optional: pass a mod name / id to fix only that one
rem  usage:
rem    fix_translations.bat              - fix ALL broken rows in cache
rem    fix_translations.bat "Factions"   - fix only that mod
rem  exit codes: 0 = all clean, 1 = problems remain, 3 = fix errors
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
%PY% "%ROOT%verify_translations.py" --fix %*
set "RC=%errorlevel%"
echo.
echo finished, exit code %RC%
pause
endlocal
exit /b %RC%
