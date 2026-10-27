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


# ---------------------------------------------------------------------------------------
# ¿Ya está en la nube? (para el reproductor del navegador, que no puede bajar de YouTube)
# Los TV y PC guardan cada canción como <video_id>_<altura>.mp4 (720 casi siempre).
# ---------------------------------------------------------------------------------------
ALTURAS = (720, 480)  # 720 por defecto; 480 en TV con poca memoria
_vistas = {}  # video_id -> (archivo o None, hora): un rato en memoria, la nube no cambia tanto
_VISTA_SI_SEG = 3600
_VISTA_NO_SEG = 8


def existe(archivo):
    import requests
    try:
        return requests.head(direccion("GET", archivo), timeout=6).status_code == 200
    except Exception as ex:
        print(f"ℹ️ Nube: no se pudo revisar {archivo}: {type(ex).__name__}")
        return False


def buscar(video_id):
    """El archivo de la nube de esa canción (en la primera calidad que exista) o None."""
    if not activa():
        return None
    v = _vistas.get(video_id)
    if v and time.time() - v[1] < (_VISTA_SI_SEG if v[0] else _VISTA_NO_SEG):
        return v[0]
    encontrado = None
    for h in ALTURAS:
        archivo = f"{video_id}_{h}.mp4"
        if archivo_valido(archivo) and existe(archivo):
            encontrado = archivo
            break
    if len(_vistas) > 20000:
        _vistas.clear()
    _vistas[video_id] = (encontrado, time.time())
    return encontrado
