@echo off
setlocal EnableExtensions
rem ============================================================
rem  Kenshi RU-mod-translation - one-click installer (thin wrapper).
rem
rem  Real logic lives in install.py.  This file just finds python
rem  and runs it, then pauses so the user can read output and see
rem  the result.  Pure-ASCII, works in any Windows code page.
rem
rem  Flags (passed to install.py, e.g.  install.bat --check):
rem    --check     only run checks, do not modify config.json
rem    --skip-net  skip the .NET Desktop Runtime check
rem ============================================================
set "ROOT=%~dp0"
cd /d "%ROOT%"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo [FAIL] Python is not on PATH.
    echo        Install Python 3.10+ (check "Add Python to PATH"),
    echo        then re-run install.bat.
    echo
    echo        https://python.org/getting-started/
    start "Kenshi - install Python" https://python.org/getting-started/
    pause
    exit /b 1
)

python "%ROOT%install.py" %*
set "RC=%errorlevel%"

echo.
pause
exit /b %RC%
