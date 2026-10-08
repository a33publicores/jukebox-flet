@echo off
setlocal
REM ============================================================
REM  Crea el reproductor PlayBar GO para Windows:
REM    dist\PlayBarGO_Reproductor\PlayBarGO_Reproductor.exe
REM  y, si tienes Inno Setup 6, el instalador:
REM    instalador\Output\PlayBarGO_Reproductor_Setup.exe
REM ============================================================
cd /d "%~dp0"

REM --- Python 3.12 instalado desde python.org (NO el de Microsoft Store) ---
set "PYBASE="
py -3.12 -c "import sys" >nul 2>&1 && set "PYBASE=py -3.12"
if not defined PYBASE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYBASE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYBASE (
  echo *** No encontre Python 3.12. Instalalo desde python.org y vuelve a intentar. ***
  goto error
)

REM --- Entorno de compilacion limpio (se rehace si quedo danado) ---
set "VPY=%~dp0.venv_build\Scripts\python.exe"
if not exist ".venv_build\Scripts\activate.bat" (
  if exist .venv_build rmdir /s /q .venv_build
  echo Creando entorno de compilacion...
  %PYBASE% -m venv .venv_build || goto error
)
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r reproductor\requirements.txt pyinstaller || goto error

REM --- Borra compilaciones anteriores ---
if exist build rmdir /s /q build
if exist dist\PlayBarGO_Reproductor rmdir /s /q dist\PlayBarGO_Reproductor
if exist dist\PlayBarGO_Reproductor.exe del /q dist\PlayBarGO_Reproductor.exe
if exist PlayBarGO_Reproductor.spec del /q PlayBarGO_Reproductor.spec

REM --- Compila en modo carpeta (-D): arranca rapido y no se rompe con el antivirus ---
"%~dp0.venv_build\Scripts\flet.exe" pack reproductor.py -D --name PlayBarGO_Reproductor ^
  --icon instalador\playbargo.ico --add-data "assets;assets" ^
  --product-name "PlayBar GO Reproductor" --product-version 1.0.0 ^
  --hidden-import unicodedata --hidden-import imageio_ffmpeg --hidden-import yt_dlp ^
  --hidden-import gspread --hidden-import googleapiclient --hidden-import flet_video -y
if errorlevel 1 goto error

REM --- Copia credenciales.json junto al programa (si lo encuentra) ---
set "CRED="
if exist "credenciales.json" set "CRED=credenciales.json"
if not defined CRED if exist "..\credenciales.json" set "CRED=..\credenciales.json"
if defined CRED (
  copy /y "%CRED%" "dist\PlayBarGO_Reproductor\credenciales.json" >nul
  echo credenciales.json copiado junto al programa.
) else (
  echo AVISO: no encontre credenciales.json. Copialo en dist\PlayBarGO_Reproductor\
)

echo.
echo === Listo: dist\PlayBarGO_Reproductor\PlayBarGO_Reproductor.exe ===
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% instalador\PlayBarGO_Reproductor.iss || goto error
  echo === Instalador: instalador\Output\PlayBarGO_Reproductor_Setup.exe ===
) else (
  echo Para crear el instalador, instala Inno Setup 6 ^(jrsoftware.org^) y vuelve a ejecutar esto.
)
pause
exit /b 0
:error
echo.
echo *** Hubo un error. Copia el mensaje de arriba y me lo envias. ***
pause
exit /b 1
