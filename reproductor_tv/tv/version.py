"""Versión del reproductor de TV (independiente de la del .exe del PC)."""
import os

VERSION = "0.2.2"

# Dirección de la API de PlayBar GO (dominio propio; hoy apunta a Railway, servicio playbar-api).
API_POR_DEFECTO = os.environ.get("PLAYBAR_API", "https://api.play.alnovix.com")

# Direcciones viejas de la API: se cambian solas por la nueva al abrir el reproductor
# (la nueva puede pasar al servidor de respaldo si Railway se cae).
APIS_VIEJAS = {"https://playbar-api-production.up.railway.app"}
