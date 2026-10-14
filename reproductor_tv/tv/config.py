"""Dónde guarda sus datos el reproductor de TV.

En Android, Flet entrega una carpeta privada de la app en FLET_APP_STORAGE_DATA (no
necesita permisos de almacenamiento y se borra al desinstalar). En el PC (para probar
con PROBAR_EN_PC.bat) se usa ~/PlayBarGoTV, separada de la del reproductor .exe.
"""
import json
import os
from pathlib import Path


def _carpeta():
    for var in ("PLAYBAR_TV_HOME", "FLET_APP_STORAGE_DATA"):
        v = os.environ.get(var, "").strip()
        if v:
            return Path(v)
    return Path.home() / "PlayBarGoTV"


CARPETA = _carpeta()
CONFIG = CARPETA / "reproductor_config.json"
CACHE = CARPETA / "cache"


def leer_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def guardar_config(cfg):
    CARPETA.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def es_android():
    import sys
    return sys.platform == "android" or "ANDROID_ROOT" in os.environ
