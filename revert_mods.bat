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
rem    revert_mods.bat --clean <mod> | all            also delete the mod's state cache + its *.translate.csv
rem    revert_mods.bat --clean-orphans --dry-run      show orphan (deleted .mod) folders
rem    revert_mods.bat --clean-orphans                move orphan folders to _kmt_orphan_trash
rem  FULL CLEAN (2026-09-24, expanded 2026-09-25) - "chistoi stol" before re-translate:
rem    revert_mods.bat --full-clean               revert ALL mods + unhook+move ALL " RUS"
rem                                               overlays + delete ALL *.translate.csv
rem                                               (new) + translate.csv (legacy) + wipe STATE/
rem                                               (full cache incl. .prev) + DELETE .orig_*.backup
rem    revert_mods.bat --full-clean --keep-backups
rem                                               same, but KEEP .orig_*.backup files
rem    revert_mods.bat --full-clean --dry-run     show what WOULD be removed/moved, touch nothing
rem    revert_mods.bat --full-clean --yes         skip the y/N prompt (for batch)
rem  (overlays are MOVED to kenshi\_kmt_full_clean_<ts>\; registry gets
rem   .fullclean_<ts>.bak next to __mods.list / mods.cfg; backup deletion is
rem   NON-REVERSIBLE (EN is already in the .mod after successful revert)
rem ============================================================
python "%~dp0revert_mods.py" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
