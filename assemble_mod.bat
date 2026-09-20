@echo off
setlocal
rem ============================================================
rem  СБОРКА мода из translate.csv (ручная правка перевода)
rem  usage:  assemble_mod.bat "имя мода"
rem          assemble_mod.bat 1140742609
rem  Перед сборкой: поправьте translate.csv в папке мода (Steam Workshop).
rem ============================================================
if "%~1"=="" (
  echo [!] укажи имя мода:  assemble_mod.bat "имя мода"
  pause
  exit /b 1
)
set "ROOT=%~dp0"
cd /d "%ROOT%"
python "%ROOT%csv_mod.py" import %*
set "RC=%errorlevel%"
echo.
echo сборка завершена, exit code %RC%
pause
exit /b %RC%
