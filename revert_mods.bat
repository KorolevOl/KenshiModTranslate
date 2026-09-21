@echo off
setlocal
rem ============================================================
rem  Kenshi mod REVERT launcher (roll back to EN original)
rem  usage:
rem    revert_mods.bat --list                    what can be reverted
rem    revert_mods.bat --dry-run <mod>           show, do not touch
rem    revert_mods.bat <mod> | id | name ...     revert specific mod(s)
rem    revert_mods.bat --list-file mods.txt      revert from a list file
rem    revert_mods.bat                           all mods (asks y/N)
rem ============================================================
python "%~dp0revert_mods.py" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
