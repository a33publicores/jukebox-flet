@echo off
REM Abre el reproductor directo desde el codigo (sin crear el .exe): sirve para probar
REM cambios al instante. Usa el mismo entorno que CONSTRUIR_EXE.bat.
cd /d "%~dp0"
set "VPY=%~dp0.venv_build\Scripts\python.exe"
if not exist "%VPY%" (
  echo Primero ejecuta CONSTRUIR_EXE.bat una vez para preparar el entorno.
  pause
  exit /b 1
)
REM Instala librerias nuevas solo si cambiaron
fc /b reproductor\requirements.txt .venv_build\requisitos_ok.txt >nul 2>&1
if errorlevel 1 (
  echo Instalando librerias nuevas, un momento...
  "%VPY%" -m pip install -r reproductor\requirements.txt pyinstaller certifi || goto error
  copy /y reproductor\requirements.txt .venv_build\requisitos_ok.txt >nul
)
"%VPY%" reproductor.py
if errorlevel 1 pause
exit /b 0
:error
echo *** No se pudieron instalar las librerias. Copia el mensaje de arriba y me lo envias. ***
pause
exit /b 1
