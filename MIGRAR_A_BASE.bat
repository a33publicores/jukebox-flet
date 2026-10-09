@echo off
REM Copia todo lo de Google Sheets a la base PostgreSQL de Railway (se hace UNA vez).
REM Pide la direccion DATABASE_PUBLIC_URL de Railway (PostgreSQL -> Variables).
cd /d "%~dp0"
set "VPY=%~dp0.venv_build\Scripts\python.exe"
if not exist "%VPY%" (
  echo Primero ejecuta CONSTRUIR_EXE.bat una vez para preparar el entorno.
  pause
  exit /b 1
)
echo Instalando lo necesario para la migracion...
"%VPY%" -m pip install -q gspread google-auth "psycopg[binary]" psycopg-pool || goto error
"%VPY%" migrar_a_base.py %*
if errorlevel 1 goto error
echo.
echo Las llaves de cada bar quedaron en llaves_bares.txt
pause
exit /b 0
:error
echo.
echo *** Hubo un error. Copia el mensaje de arriba y me lo envias. ***
pause
exit /b 1
