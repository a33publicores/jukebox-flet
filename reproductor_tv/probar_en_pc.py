"""
Prueba el reproductor de TV en el PC (antes de crear el .apk).

    py -3.12 probar_en_pc.py        (o doble clic en este archivo)

1. Crea un Python aparte para el TV (carpeta .venv_tv) si no existe.
2. Revisa que estén Flet, flet-video, yt-dlp y requests; si falta algo, lo instala.
3. Abre la app (main.py) con ese Python.

Todo lo que pasa queda en  probar_en_pc.log  (para revisar si algo falla).
Las flechas del teclado y Enter hacen lo mismo que el control remoto.
"""
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VENV = AQUI / ".venv_tv"
VPY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
LOG = AQUI / "probar_en_pc.log"
PAQUETES = ["flet==1.0.3", "flet-desktop==1.0.3", "flet-video", "yt-dlp", "requests"]
IMPORTS = "import flet, flet_desktop, flet_video, yt_dlp, requests; print('flet', flet.__version__ if hasattr(flet, '__version__') else '?')"


def log(texto=""):
    print(texto, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')}  {texto}\n")


def correr(cmd, mostrar=True):
    """Ejecuta un comando, muestra su salida en pantalla y la guarda en el log."""
    log("> " + " ".join(str(c) for c in cmd))
    p = subprocess.Popen([str(c) for c in cmd], cwd=AQUI, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for linea in p.stdout:
        linea = linea.rstrip()
        if mostrar:
            print(linea, flush=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("    " + linea + "\n")
    return p.wait()


def librerias_ok():
    return VPY.exists() and correr([VPY, "-c", IMPORTS], mostrar=False) == 0


def main():
    LOG.write_text("", encoding="utf-8")
    log(f"Python que ejecuta este script: {sys.executable} ({sys.version.split()[0]})")

    if not VPY.exists():
        log("1. Creando .venv_tv ...")
        if correr([sys.executable, "-m", "venv", VENV]) != 0 or not VPY.exists():
            log("*** No se pudo crear .venv_tv ***")
            return 1
    else:
        log("1. .venv_tv ya existe")

    if librerias_ok():
        log("2. Librerías OK")
    else:
        log("2. Instalando librerías (la primera vez tarda unos minutos)...")
        correr([VPY, "-m", "pip", "install", "--upgrade", "pip"])
        codigo = correr([VPY, "-m", "pip", "install", *PAQUETES])
        if codigo != 0 or not librerias_ok():
            log("*** La instalación falló. El detalle está en probar_en_pc.log ***")
            correr([VPY, "-c", IMPORTS])  # muestra cuál librería falta
            return 1
        log("   Librerías instaladas")

    log("3. Abriendo PlayBar GO TV ...")
    return correr([VPY, "main.py"])


if __name__ == "__main__":
    try:
        codigo = main()
    except Exception:
        log(traceback.format_exc())
        codigo = 1
    if codigo:
        log(f"Terminó con código {codigo}")
    input("\nPresiona ENTER para cerrar...")
