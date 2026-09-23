@echo off
setlocal
rem ============================================================
rem  Kenshi RU-mod search launcher (search phrase across ALL mods
rem  AND game files, then optionally translate selected mods)
rem  usage:
rem    search_mods.bat "phrase to find"
rem    search_mods.bat "phrase" --no-translate
rem    search_mods.bat "phrase" --yes
rem    search_mods.bat "phrase" --force
rem    search_mods.bat "phrase" --ru        (only RU hits in cache)
rem    search_mods.bat "phrase" --all       (show already-translated rows too)
rem    search_mods.bat "phrase" --all --cap 100
rem  For each matched row in a .mod (already translated mod) the search ALSO
rem  prints its TRANSLATION (EN -> RU) from the state cache, whichever side
rem  (EN or RU) you searched by.
rem  By default rows that ALREADY have a translation are HIDDEN (the point is
rem  to find what still needs translating).  Add  --all  to show everything.
rem  --cap N limits table rows (default 20).
rem  After search you get a numbered list - type mod numbers
rem  (comma/space separated) to start translation of those mods.
rem ============================================================
set "ROOT=%~dp0"
set "PY=py"
where %PY% >nul 2>nul
if errorlevel 1 (
  set "PY=python"
)
cd /d "%ROOT%"
%PY% "%ROOT%search_mods.py" %*
set "RC=%errorlevel%"
echo.
echo finished, exit code %RC%
pause
exit /b %RC%
