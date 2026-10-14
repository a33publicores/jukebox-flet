@echo off
REM Crea el .apk de PlayBar GO TV (Android TV / Google TV / Fire TV / TV Box).
REM El resultado queda en  reproductor_tv\salida_apk\PlayBarGO_TV.apk
cd /d "%~dp0"
chcp 65001 >nul
py -3.12 -c "pass" >nul 2>&1
if not errorlevel 1 (
  py -3.12 construir_apk.py
) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" construir_apk.py
) else (
  echo *** No encontre Python 3.12. Instalalo desde python.org y vuelve a intentar. ***
)
echo.
pause
