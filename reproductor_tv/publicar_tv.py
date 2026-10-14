"""
Publica una versión nueva del CÓDIGO del reproductor de TV. Los televisores la bajan
solos (revisan cada 3 horas) y se actualizan al terminar la canción, sin reinstalar.

    py -3.12 publicar_tv.py 0.1.1        (o sin número: propone la siguiente)

Qué hace:
  1. Cambia la versión en tv/version.py.
  2. Crea salida_apk/tv_codigo.zip con la carpeta tv/ y lo revisa.
  3. Lo publica en GitHub como release "tv-v<versión>" marcada como PRE-RELEASE
     (así el reproductor del PC no la confunde con la suya):
       - si tienes "gh" (GitHub CLI) con sesión iniciada, lo publica solo;
       - si no, abre GitHub en el navegador con todo lleno y la carpeta con el .zip.

Cuándo NO sirve (hay que crear un .apk nuevo con construir_apk.py e instalarlo):
  cambios en main.py, arranque.py, pyproject.toml, assets/ o librerías nuevas.
"""
import re
import shutil
import subprocess
import sys
import urllib.parse
import webbrowser
import zipfile
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VERSION_PY = AQUI / "tv" / "version.py"
SALIDA = AQUI / "salida_apk"
ZIP = SALIDA / "tv_codigo.zip"
sys.path.insert(0, str(AQUI))
from tv.actualizador_tv import ACTIVO, PREFIJO, REPO, revisar_zip  # noqa: E402


def version_actual():
    return re.search(r'^VERSION\s*=\s*"([^"]+)"', VERSION_PY.read_text("utf-8"), re.M).group(1)


def siguiente(v):
    a, b, c = (list(map(int, v.split("."))) + [0, 0, 0])[:3]
    return f"{a}.{b}.{c + 1}"


def poner_version(v):
    texto = VERSION_PY.read_text("utf-8")
    texto = re.sub(r'^VERSION\s*=\s*"[^"]+"', f'VERSION = "{v}"', texto, count=1, flags=re.M)
    VERSION_PY.write_text(texto, "utf-8")


def crear_zip(v):
    SALIDA.mkdir(exist_ok=True)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted((AQUI / "tv").rglob("*.py")):
            if "__pycache__" not in p.parts:
                z.write(p, p.relative_to(AQUI).as_posix())
    revisar_zip(ZIP.read_bytes(), v)  # misma revisión que hará el TV
    print(f"✓ {ZIP} ({ZIP.stat().st_size / 1024:.0f} KB) revisado")


def publicar(v, notas):
    etiqueta, titulo = f"{PREFIJO}{v}", f"PlayBar GO TV {v}"
    gh = shutil.which("gh")
    if gh and subprocess.run([gh, "auth", "status"], capture_output=True).returncode == 0:
        r = subprocess.run([gh, "release", "create", etiqueta, str(ZIP), "--repo", REPO,
                            "--prerelease", "--title", titulo, "--notes", notas or "-"])
        if r.returncode == 0:
            print(f"✅ Publicada {etiqueta}. Los TV la instalan solos (máx. 3 horas).")
            return
        print("⚠️ gh no pudo publicar; abro GitHub en el navegador.")
    datos = {"tag": etiqueta, "title": titulo, "prerelease": "1", "body": notas or "Qué cambió:\n- "}
    webbrowser.open(f"https://github.com/{REPO}/releases/new?" + urllib.parse.urlencode(datos))
    try:
        subprocess.run(["explorer", "/select,", str(ZIP)])
    except Exception:
        pass
    print(f"""
Se abrió GitHub en el navegador y la carpeta con el archivo.
  1. Arrastra  {ACTIVO}  al cuadro "Attach binaries" (NO le cambies el nombre).
  2. Revisa que esté marcada la casilla  "Set as a pre-release"  (ya viene marcada).
     Así el reproductor del PC no la toma como suya.
  3. "Publish release". Los TV la instalan solos al terminar la canción (máx. 3 horas).
     Si debe instalarse sin esperar la canción, agrega una línea que diga: [ahora]
""")


def main():
    actual = version_actual()
    args = [a for a in sys.argv[1:] if a[:1].isdigit()]
    nueva = args[0] if args else (input(f"Versión nueva del TV (actual {actual}) "
                                         f"[Enter = {siguiente(actual)}]: ").strip()
                                  or siguiente(actual))
    notas = input("¿Qué cambió? (una línea, opcional): ").strip()
    poner_version(nueva)
    crear_zip(nueva)
    publicar(nueva, notas)
    print("Recuerda subir también el código a GitHub (git add, commit, push) como siempre.")


if __name__ == "__main__":
    main()
    input("\nPresiona ENTER para cerrar...")
