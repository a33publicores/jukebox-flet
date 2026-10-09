@echo off
REM Crea el reproductor PlayBar GO (.exe). Todo el trabajo lo hace construir_exe.py.
REM Para crear tambien el instalador:  CONSTRUIR_EXE.bat instalador
cd /d "%~dp0"
py -3.12 -c "pass" >nul 2>&1
if not errorlevel 1 (
  py -3.12 construir_exe.py %*
) else if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" construir_exe.py %*
) else (
  echo *** No encontre Python 3.12. Instalalo desde python.org y vuelve a intentar. ***
)
echo.
pause
