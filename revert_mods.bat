@echo off
setlocal
rem ============================================================
rem  Kenshi mod REVERT launcher (roll back to EN original)
rem  usage:
rem    revert_mods.bat --list                         what can be reverted + orphan summary
rem    revert_mods.bat --dry-run <mod>                show, do not touch
rem    revert_mods.bat <mod> | id | name ...          revert specific mod(s)
rem    revert_mods.bat --list-file mods.txt           revert from a list file
rem    revert_mods.bat                                all mods (asks y/N)
rem    revert_mods.bat --file <path>                  revert any .mod (kenshi\data, kenshi\mods\...)
rem    revert_mods.bat --clean-orphans --dry-run      show orphan (deleted .mod) folders
rem    revert_mods.bat --clean-orphans                move orphan folders to _kmt_orphan_trash
rem ============================================================
python "%~dp0revert_mods.py" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
