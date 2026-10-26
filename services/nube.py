"""
Canciones en la nube (Cloudflare R2, ver nube_cloudflare/worker.js).

La API firma direcciones de corta duración para que un reproductor con llave válida baje
o suba una canción. Sin NUBE_URL / NUBE_FIRMA (variables de Railway) la nube está apagada
y los reproductores siguen como siempre (todo de YouTube).
"""
import hashlib
import hmac
import os
import re
import time

DURACION_SEG = 6 * 3600  # una descarga lenta en un TV puede tardar; la firma dura 6 h
_ARCHIVO = re.compile(r"^[A-Za-z0-9_-]{6,20}(_\d{3,4})?\.mp4$")


def activa():
    return bool(os.getenv("NUBE_URL", "").strip() and os.getenv("NUBE_FIRMA", "").strip())


def archivo_valido(archivo):
    return bool(_ARCHIVO.match(str(archivo or "")))


def _firmar(metodo, archivo, exp):
    secreto = os.getenv("NUBE_FIRMA", "").strip().encode()
    return hmac.new(secreto, f"{metodo}:{archivo}:{exp}".encode(), hashlib.sha256).hexdigest()


def direccion(metodo, archivo):
    exp = int(time.time()) + DURACION_SEG
    base = os.getenv("NUBE_URL", "").strip().rstrip("/")
    return f"{base}/v/{archivo}?exp={exp}&sig={_firmar(metodo, archivo, exp)}"


def direcciones(archivo):
    """{"activo": False} sin nube; si no, las direcciones firmadas para bajar y subir."""
    if not activa() or not archivo_valido(archivo):
        return {"activo": False}
    return {"activo": True, "get": direccion("GET", archivo), "put": direccion("PUT", archivo)}
