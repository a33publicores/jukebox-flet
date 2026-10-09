"""
Crea el reproductor PlayBar GO para Windows (todo en Python, sin trucos de cmd).

    dist\\PlayBarGO_Reproductor\\PlayBarGO_Reproductor.exe
    (con  --instalador  también instalador\\Output\\PlayBarGO_Reproductor_Setup.exe,
     si tienes Inno Setup 6)

Se abre con CONSTRUIR_EXE.bat (doble clic) o:  py -3.12 construir_exe.py
"""
import filecmp
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VENV = AQUI / ".venv_build"
VPY = VENV / "Scripts" / "python.exe"
FLET = VENV / "Scripts" / "flet.exe"
REQ = AQUI / "reproductor" / "requirements.txt"
MARCA = VENV / "requisitos_ok.txt"
NOMBRE = "PlayBarGO_Reproductor"
SALIDA = AQUI / "dist" / NOMBRE


def paso(texto):
    print(f"\n=== {texto} ===", flush=True)


def correr(cmd, **kw):
    print("> " + " ".join(str(c) for c in cmd), flush=True)
    r = subprocess.run([str(c) for c in cmd], cwd=AQUI, **kw)
    if r.returncode != 0:
        raise SystemExit(f"*** Falló el paso anterior (código {r.returncode}). "
                         "Copia el mensaje de arriba y me lo envías. ***")
    return r


def version():
    for linea in (AQUI / "reproductor" / "version.py").read_text(encoding="utf-8").splitlines():
        if linea.startswith("VERSION"):
            return linea.split("=", 1)[1].strip().strip('"\'')
    return "1.0.0"


def preparar_entorno():
    paso("Entorno de compilación")
    if VPY.exists() and not (VENV / "Scripts" / "activate.bat").exists():
        print("El entorno quedó dañado: lo rehago.")
        shutil.rmtree(VENV, ignore_errors=True)
    if not VPY.exists():
        if sys.version_info[:2] != (3, 12):
            print(f"AVISO: este Python es {sys.version.split()[0]}; se recomienda 3.12 (python.org).")
        correr([sys.executable, "-m", "venv", VENV])
    if not (MARCA.exists() and filecmp.cmp(REQ, MARCA, shallow=False)):
        print("Instalando librerías (solo cuando cambian)...")
        correr([VPY, "-m", "pip", "install", "--upgrade", "pip"])
        correr([VPY, "-m", "pip", "install", "-r", REQ, "pyinstaller", "certifi"])
        shutil.copyfile(REQ, MARCA)
    else:
        print("Librerías ya instaladas.")
    subprocess.run([str(VPY), "-m", "pip", "install", "-U", "-q", "yt-dlp"], cwd=AQUI)


def certificados():
    r = subprocess.run([str(VPY), "-c", "import certifi; print(certifi.where())"],
                       capture_output=True, text=True, cwd=AQUI)
    ruta = (r.stdout or "").strip()
    if r.returncode != 0 or not ruta or not Path(ruta).is_file():
        print(r.stderr)
        raise SystemExit("*** No encontré certifi en el entorno. ***")
    print(f"Certificados: {ruta}")
    return ruta


def cerrar_reproductor():
    subprocess.run(["taskkill", "/im", f"{NOMBRE}.exe", "/f"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)


def compilar(cert):
    paso("Compilando (la primera vez tarda varios minutos)")
    for viejo in (SALIDA, AQUI / "dist" / f"{NOMBRE}.exe", AQUI / f"{NOMBRE}.spec"):
        if viejo.is_dir():
            shutil.rmtree(viejo, ignore_errors=True)
        elif viejo.exists():
            viejo.unlink()
    v = version()
    correr([
        FLET, "pack", "reproductor.py", "-D", "--name", NOMBRE,
        "--icon", "instalador\\playbargo.ico",
        "--add-data", "assets;assets",
        "--add-data", f"{cert};certifi",
        "--product-name", "PlayBar GO Reproductor", "--product-version", v,
        "--hidden-import", "unicodedata", "--hidden-import", "imageio_ffmpeg",
        "--hidden-import", "yt_dlp", "--hidden-import", "openpyxl",
        "--hidden-import", "flet_video", "-y",
    ])
    if not (SALIDA / "_internal" / "certifi" / "cacert.pem").is_file():
        raise SystemExit("*** Los certificados no quedaron dentro del programa. ***")
    print(f"\nListo: {SALIDA / (NOMBRE + '.exe')}  (versión {v})")


def instalador():
    paso("Instalador")
    for iscc in (Path(os.environ.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
                 Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe"):
        if iscc.is_file():
            correr([iscc, "instalador\\PlayBarGO_Reproductor.iss"])
            print("Instalador: instalador\\Output\\PlayBarGO_Reproductor_Setup.exe")
            return
    print("Para crear el instalador, instala Inno Setup 6 (jrsoftware.org) y vuelve a correr esto.")


def main():
    inicio = time.time()
    preparar_entorno()
    cert = certificados()
    cerrar_reproductor()
    compilar(cert)
    if "--instalador" in sys.argv or "instalador" in sys.argv:
        instalador()
    else:
        print("Para crear también el instalador:  CONSTRUIR_EXE.bat instalador")
    print(f"\nTiempo total: {int(time.time() - inicio)} s")


if __name__ == "__main__":
    main()
