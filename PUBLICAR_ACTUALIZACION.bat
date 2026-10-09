@echo off
REM Publica una ACTUALIZACION del reproductor para los bares.
REM Uso:  PUBLICAR_ACTUALIZACION.bat 1.1.1   (o doble clic y escribes la version)
REM Cambia la version, crea el .exe y el instalador, y abre GitHub para subirlo.
cd /d "%~dp0"
py -3.12 -c "pass" >nul 2>&1
if not errorlevel 1 (
  py -3.12 construir_exe.py publicar %*
) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" construir_exe.py publicar %*
) else (
  echo *** No encontre Python 3.12. Instalalo desde python.org y vuelve a intentar. ***
)
echo.
pause
