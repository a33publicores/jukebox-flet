@echo off
REM Reproductor PlayBar GO - Windows
cd /d "%~dp0"
if not exist .venv_player (
  echo Preparando por primera vez, un momento...
  py -3.13 -m venv .venv_player || py -3 -m venv .venv_player
  call .venv_player\Scripts\activate.bat
  python -m pip install --upgrade pip
  pip install -r reproductor\requirements.txt
) else (
  call .venv_player\Scripts\activate.bat
)
REM Actualiza yt-dlp (YouTube cambia seguido)
pip install -U yt-dlp >nul 2>&1
python reproductor.py
pause
