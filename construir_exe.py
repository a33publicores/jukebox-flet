"""
Crea el reproductor PlayBar GO para Windows (todo en Python, sin trucos de cmd).

    dist\\PlayBarGO_Reproductor\\PlayBarGO_Reproductor.exe
    (con  --instalador  también instalador\\Output\\PlayBarGO_Reproductor_Setup.exe,
     si tienes Inno Setup 6)

Se abre con CONSTRUIR_EXE.bat (doble clic) o:  py -3.12 construir_exe.py

Para sacar una ACTUALIZACIÓN para los bares:  PUBLICAR_ACTUALIZACION.bat 1.1.1
  (cambia la versión, crea el instalador y abre GitHub para subirlo como "Release").
"""
import filecmp
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VENV = AQUI / ".venv_build"
VPY = VENV / "Scripts" / "python.exe"
FLET = VENV / "Scripts" / "flet.exe"
REQ = AQUI / "reproductor" / "requirements.txt"
MARCA = VENV / "requisitos_ok.txt"
NOMBRE = "PlayBarGO_Reproductor"
SALIDA = AQUI / "dist" / NOMBRE
SETUP = AQUI / "instalador" / "Output" / "PlayBarGO_Reproductor_Setup.exe"
ARCHIVO_VERSION = AQUI / "reproductor" / "version.py"
REPO = "a33publicores/jukebox-flet"


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
    for linea in ARCHIVO_VERSION.read_text(encoding="utf-8").splitlines():
        if linea.startswith("VERSION"):
            return linea.split("=", 1)[1].strip().strip('"\'')
    return "1.0.0"


def _tupla(v):
    return tuple(int("".join(c for c in x if c.isdigit()) or 0) for x in v.strip().lstrip("vV").split("."))


def poner_version(nueva):
    nueva = nueva.strip().lstrip("vV")
    if len(_tupla(nueva)) != 3:
        raise SystemExit(f"*** La versión debe ser como 1.1.1 (escribiste {nueva!r}). ***")
    actual = version()
    if _tupla(nueva) <= _tupla(actual):
        raise SystemExit(f"*** La versión nueva ({nueva}) debe ser MAYOR que la actual ({actual}). "
                         "Si no, los bares no la ven como actualización. ***")
    lineas = ARCHIVO_VERSION.read_text(encoding="utf-8").splitlines(keepends=True)
    lineas = [f'VERSION = "{nueva}"\n' if l.startswith("VERSION") else l for l in lineas]
    ARCHIVO_VERSION.write_text("".join(lineas), encoding="utf-8")
    print(f"Versión: {actual}  ->  {nueva}")
    return nueva


def siguiente_version():
    a, b, c = (list(_tupla(version())) + [0, 0, 0])[:3]
    return f"{a}.{b}.{c + 1}"


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


# Fuentes oficiales de Inno Setup (se prueba en orden).
INNO_API = "https://api.github.com/repos/jrsoftware/issrc/releases/latest"
INNO_URLS = ["https://jrsoftware.org/download.php/is.exe",
             "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"]


def _urls_inno():
    import json
    import urllib.request
    urls = []
    try:
        req = urllib.request.Request(INNO_API, headers={"User-Agent": "PlayBarGO"})
        with urllib.request.urlopen(req, timeout=30) as r:
            rel = json.load(r)
        for a in rel.get("assets", []):
            nombre = a.get("name", "").lower()
            if nombre.startswith("innosetup-") and nombre.endswith(".exe"):
                urls.append(a["browser_download_url"])
    except Exception as ex:
        print(f"(no se pudo consultar la última versión: {ex})")
    return urls + INNO_URLS


def buscar_iscc():
    raices = [os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
              str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs")]
    for raiz in raices:
        if raiz and Path(raiz).is_dir():
            for iscc in sorted(Path(raiz).glob("Inno Setup*/ISCC.exe"), reverse=True):
                return iscc
    return None


def instalar_inno():
    """Inno Setup solo se necesita en TU PC para fabricar el instalador (los bares no).
    Si no está, se descarga de su página oficial y se instala solo, sin preguntas."""
    import urllib.request
    paso("Instalando Inno Setup (solo la primera vez)")
    destino = Path(os.environ.get("TEMP", AQUI)) / "innosetup_instalador.exe"
    for url in _urls_inno():
        print(f"Descargando {url} ...", flush=True)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as r, open(destino, "wb") as f:
                shutil.copyfileobj(r, f)
            with open(destino, "rb") as f:
                if destino.stat().st_size > 1_000_000 and f.read(2) == b"MZ":
                    break
            print("La descarga no parece un instalador válido; pruebo otra fuente.")
        except Exception as ex:
            print(f"No se pudo descargar: {ex}")
    else:
        return None
    print("Instalando en silencio (para tu usuario, sin permisos de administrador)...", flush=True)
    subprocess.run([str(destino), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    "/CURRENTUSER", "/SP-"], cwd=AQUI)
    try:
        destino.unlink()
    except Exception:
        pass
    iscc = buscar_iscc()
    print(f"Inno Setup listo: {iscc}" if iscc else "No quedó instalado Inno Setup.")
    return iscc


def instalador():
    paso("Instalador")
    iscc = buscar_iscc() or instalar_inno()
    if not iscc:
        print("Instala Inno Setup a mano desde jrsoftware.org y vuelve a correr esto.")
        return False
    if SETUP.exists():
        SETUP.unlink()
    correr([iscc, f"/DVersion={version()}", "instalador\\PlayBarGO_Reproductor.iss"])
    print(f"Instalador: {SETUP}  ({SETUP.stat().st_size / 1048576:.0f} MB)")
    return True


def publicar():
    """Abre GitHub listo para subir la versión y la carpeta con el instalador."""
    v = version()
    paso(f"Publicar la versión {v} para los bares")
    datos = {"tag": f"v{v}", "title": f"PlayBar GO Reproductor {v}",
             "body": "Qué cambió:\n- \n\n(Escribe [obligatoria] aquí si los bares NO pueden dejarla para después)"}
    url = f"https://github.com/{REPO}/releases/new?" + urllib.parse.urlencode(datos)
    print(f"""
Se abrió GitHub en el navegador y la carpeta con el instalador.
  1. Arrastra  PlayBarGO_Reproductor_Setup.exe  al cuadro "Attach binaries"
     (NO le cambies el nombre). Espera a que termine de subir.
  2. Escribe qué cambió (opcional) y dale  "Publish release".
Listo: en máximo 3 horas (o al abrir el programa) los bares verán "Actualizar".
Recuerda subir también el código a GitHub (version.py cambió) como siempre.
""")
    webbrowser.open(url)
    try:
        subprocess.run(["explorer", "/select,", str(SETUP)])
    except Exception:
        pass


def main():
    inicio = time.time()
    args = [a.lower().lstrip("-") for a in sys.argv[1:]]
    es_publicar = "publicar" in args
    if es_publicar:
        nueva = next((a for a in args if a[:1].isdigit()), "")
        if not nueva:
            sugerida = siguiente_version()
            nueva = input(f"Versión nueva (la actual es {version()}) [Enter = {sugerida}]: ").strip() or sugerida
        poner_version(nueva)
    preparar_entorno()
    cert = certificados()
    cerrar_reproductor()
    compilar(cert)
    # El instalador se crea siempre: es lo único que se le entrega a los bares.
    if instalador():
        if es_publicar:
            publicar()
    elif es_publicar:
        raise SystemExit("*** Sin Inno Setup no hay instalador, y sin instalador no hay actualización. ***")
    print(f"\nTiempo total: {int(time.time() - inicio)} s")


if __name__ == "__main__":
    main()
