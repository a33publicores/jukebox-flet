@echo off
REM Abre el reproductor de TV en una ventana del PC para probarlo antes de crear el .apk.
REM Las flechas del teclado y Enter hacen lo mismo que el control remoto.
REM Sus datos quedan en la carpeta PlayBarGoTV de tu usuario (separados del reproductor .exe).
cd /d "%~dp0"
chcp 65001 >nul
set "VPY=.venv_tv\Scripts\python.exe"

if not exist "%VPY%" (
  echo Creando el Python del reproductor de TV...
  py -3.12 -m venv .venv_tv 2>nul || "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" -m venv .venv_tv
)
if not exist "%VPY%" (
  echo *** No se pudo crear .venv_tv. Instala Python 3.12 desde python.org. ***
  pause
  exit /b 1
)

REM Revisa que las librerias esten de verdad (si una instalacion anterior fallo, la repite)
"%VPY%" -c "import flet, flet_desktop, flet_video, yt_dlp, requests" >nul 2>&1
if errorlevel 1 (
  echo Instalando librerias ^(la primera vez tarda unos minutos^)...
  "%VPY%" -m pip install --upgrade pip
  "%VPY%" -m pip install flet==1.0.3 flet-desktop==1.0.3 flet-video yt-dlp requests
  "%VPY%" -c "import flet, flet_desktop, flet_video, yt_dlp, requests" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo *** La instalacion fallo. Revisa los mensajes de arriba ^(internet, antivirus^). ***
    pause
    exit /b 1
  )
)

"%VPY%" main.py
pause
