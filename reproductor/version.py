"""Versión del reproductor y dónde consultar si hay una nueva."""
import os

VERSION = "1.1.0"

# Archivo JSON público con la última versión. Súbelo al repo (rama main):
#   {"version": "1.0.1", "url": "https://.../PlayBarGO_Reproductor_Setup.exe",
#    "notas": "Qué cambió", "obligatoria": false}
UPDATE_URL = os.environ.get(
    "PLAYBAR_UPDATE_URL",
    "https://raw.githubusercontent.com/a33publicores/jukebox-flet/main/reproductor_version.json",
)

# Dirección de la API de PlayBar GO en Railway (servicio playbar-api). Se puede cambiar
# en la pantalla de configuración del reproductor o con la variable PLAYBAR_API.
API_POR_DEFECTO = os.environ.get("PLAYBAR_API", "https://playbar-api-production.up.railway.app")
