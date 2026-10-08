"""Revisa si hay una versión nueva del reproductor. Nunca lanza errores hacia la UI."""
import requests

from reproductor.version import UPDATE_URL, VERSION


def _tupla(v):
    partes = []
    for x in str(v).strip().lstrip("vV").split("."):
        num = "".join(c for c in x if c.isdigit())
        partes.append(int(num) if num else 0)
    return tuple(partes)


def hay_actualizacion(actual=VERSION, url=UPDATE_URL, timeout=8):
    """Devuelve el dict del JSON si hay versión más nueva y trae enlace; si no, None."""
    try:
        r = requests.get(url, timeout=timeout, headers={"Cache-Control": "no-cache"})
        if r.status_code != 200:
            return None
        info = r.json()
        if not isinstance(info, dict) or not info.get("url"):
            return None
        if _tupla(info.get("version", "0")) > _tupla(actual):
            return info
    except Exception as ex:
        print("ℹ️ No se pudo revisar actualizaciones:", ex)
    return None
