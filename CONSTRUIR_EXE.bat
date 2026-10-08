@echo off
REM Genera dist\PlayBarGO_Reproductor.exe y el instalador (si tienes Inno Setup)
cd /d "%~dp0"
if not exist .venv_build (
  py -3.13 -m venv .venv_build || py -3 -m venv .venv_build
)
call .venv_build\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r reproductor\requirements.txt pyinstaller
if errorlevel 1 goto error

REM El .exe lleva dentro: Flet, ffmpeg, yt-dlp y los logos (assets).
flet pack reproductor.py --name PlayBarGO_Reproductor --icon instalador\playbargo.ico ^
  --add-data "assets;assets" --product-name "PlayBar GO Reproductor" ^
  --product-version 1.0.0 --hidden-import imageio_ffmpeg --hidden-import yt_dlp ^
  --hidden-import gspread --hidden-import googleapiclient -y
if errorlevel 1 goto error

echo.
echo === Listo: dist\PlayBarGO_Reproductor.exe ===
set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% instalador\PlayBarGO_Reproductor.iss
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
