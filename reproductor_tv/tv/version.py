"""Versión del reproductor de TV (independiente de la del .exe del PC)."""
import os

VERSION = "0.1.3"

# Dirección de la API de PlayBar GO en Railway (servicio playbar-api).
API_POR_DEFECTO = os.environ.get("PLAYBAR_API", "https://playbar-api-production.up.railway.app")
