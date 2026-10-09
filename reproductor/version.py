"""Versión del reproductor y dónde consultar si hay una nueva.

Para sacar una versión nueva NO edites esto a mano: usa
    PUBLICAR_ACTUALIZACION.bat 1.1.1
que cambia este número, crea el instalador y abre GitHub para subirlo.
"""
import os

VERSION = "1.1.1"

# Repositorio público donde se publican las versiones (pestaña "Releases").
REPO = os.environ.get("PLAYBAR_REPO", "a33publicores/jukebox-flet")
RELEASES_URL = os.environ.get(
    "PLAYBAR_RELEASES_URL", f"https://api.github.com/repos/{REPO}/releases/latest")

# Forma antigua (respaldo): archivo JSON en el repo.
UPDATE_URL = os.environ.get(
    "PLAYBAR_UPDATE_URL",
    f"https://raw.githubusercontent.com/{REPO}/main/reproductor_version.json",
)

# Cada cuánto vuelve a revisar mientras está abierto (los bares lo dejan prendido toda la noche).
REVISAR_CADA_HORAS = float(os.environ.get("PLAYBAR_REVISAR_HORAS", "3"))

# Dirección de la API de PlayBar GO en Railway (servicio playbar-api). Se puede cambiar
# en la pantalla de configuración del reproductor o con la variable PLAYBAR_API.
API_POR_DEFECTO = os.environ.get("PLAYBAR_API", "https://playbar-api-production.up.railway.app")
