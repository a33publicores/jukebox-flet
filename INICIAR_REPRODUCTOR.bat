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
"%VPY%" reproductor.py
if errorlevel 1 pause
