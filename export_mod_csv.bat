@echo off
setlocal
rem ============================================================
rem  ЭКСПОРТ <имя-мода>.translate.csv для мода (без LLM-перевода)
rem  usage:  export_mod_csv.bat "имя мода" [ещё-моды...]
rem  Результат: <папка мода в Steam>\<имя-мода>.translate.csv (оригинал|перевод)
rem ============================================================
if "%~1"=="" (
  echo [!] укажи имя мода:  export_mod_csv.bat "имя мода"
  pause
  exit /b 1
)
set "ROOT=%~dp0"
cd /d "%ROOT%"
python "%ROOT%csv_mod.py" export %*
set "RC=%errorlevel%"
echo.
echo экспорт завершён, exit code %RC%
pause
exit /b %RC%
