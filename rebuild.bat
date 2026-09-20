@echo off
chcp 866 >nul
title Пересборка модов (rebuild из кеша)
setlocal

python "%~dp0rebuild_mods.py" %*
set RC=%ERRORLEVEL%
echo.
pause
exit /b %RC%
