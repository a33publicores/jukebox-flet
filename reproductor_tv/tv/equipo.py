"""Qué equipo es (modelo, Android, RAM, espacio, pantalla): para elegir la calidad del video
y para que el super administrador vea en /super en qué TV suena cada bar."""
import os
import platform
import shutil
import subprocess

from tv import config as CFG
from tv.version import VERSION

RAM_BASICO_GB = 2.0  # con menos RAM se baja en 480p (TV básicos / TV Box baratos)


def _prop(nombre):
    """Propiedad de Android (getprop). Vacío si no se puede leer (p. ej. en el PC)."""
    try:
        r = subprocess.run(["getprop", nombre], capture_output=True, text=True, timeout=3)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def ram_gb():
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for linea in f:
                if linea.startswith("MemTotal:"):
                    return round(int(linea.split()[1]) / 1024 / 1024, 1)
    except Exception:
        pass
    if os.name == "nt":  # probando en el PC
        try:
            import ctypes

            class _Mem(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = _Mem()
            m.dwLength = ctypes.sizeof(_Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return round(m.ullTotalPhys / 1024 ** 3, 1)
        except Exception:
            pass
    return 0.0


def es_basico():
    r = ram_gb()
    return 0 < r < RAM_BASICO_GB


def info(page=None, calidad=None):
    marca, modelo = _prop("ro.product.manufacturer"), _prop("ro.product.model")
    android = _prop("ro.build.version.release")
    d = {
        "tipo": "tv",
        "app": VERSION,
        "modelo": " ".join(x for x in (marca, modelo) if x) or platform.node(),
        "sistema": f"Android {android}" if android else f"{platform.system()} {platform.release()}",
        "ram_gb": ram_gb(),
    }
    try:
        d["libre_gb"] = round(shutil.disk_usage(CFG.CARPETA).free / 1024 ** 3, 1)
    except Exception:
        pass
    if page is not None:
        try:
            d["pantalla"] = f"{int(page.width or 0)}×{int(page.height or 0)}"
        except Exception:
            pass
    if calidad:
        d["calidad"] = f"{calidad}p"
    return d
