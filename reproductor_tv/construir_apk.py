"""
Crea el .apk de PlayBar GO TV.

    CONSTRUIR_APK.bat            (doble clic)

Pasos:
  1. Prepara un Python aparte para el TV (carpeta .venv_tv) con Flet 1.0.3.
  2. "flet build apk": Flet baja solo Flutter, el SDK de Android y Java la primera vez
     (tarda bastante la primera vez; después es más rápido).
  3. Le agrega al proyecto Android lo que Flet no deja poner en pyproject.toml:
       - la categoría LEANBACK_LAUNCHER (para que la app salga en el inicio de
         Android TV / Google TV y no solo en Ajustes > Apps), y
       - el banner (la imagen grande con el logo que muestra el TV).
     y vuelve a compilar (Flet reutiliza el proyecto ya ajustado). Si este paso falla,
     queda el .apk normal del paso 2 (sirve igual; en Google TV se abre desde
     Ajustes > Apps).
  4. Copia el resultado a la carpeta  salida_apk\\PlayBarGO_TV.apk
"""
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
VENV = AQUI / ".venv_tv"
WIN = sys.platform == "win32"
VPY = VENV / ("Scripts/python.exe" if WIN else "bin/python")
FLET = VENV / ("Scripts/flet.exe" if WIN else "bin/flet")
SALIDA = AQUI / "salida_apk"
FLUTTER_PROY = AQUI / "build" / "flutter"

# Llave de firma propia (FUERA del repo). Siempre la misma: si cambia, los TV no dejan
# actualizar. La contraseña va en el .txt de al lado o en FLET_ANDROID_SIGNING_KEY_STORE_PASSWORD.
LLAVE = Path(os.environ.get("PLAYBARGO_TV_LLAVE", AQUI.parent.parent / "llaves" / "playbargo_tv.jks"))
LLAVE_CLAVE = LLAVE.with_name(LLAVE.stem + "_password.txt")


LOG = AQUI / "construir_apk.log"


def log(texto):
    print(texto, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(texto + "\n")


def paso(texto):
    log("\n" + "=" * 64 + f"\n{time.strftime('%H:%M:%S')}  {texto}\n" + "=" * 64)


_CLAVES = ("error", "fail", "exception", "warning", "✅", "✓", "⚠", "❌", "build ",
           "running gradle", "packaged", "installing", "generated", "built ", ".apk")


def _importante(linea):
    t = linea.strip()
    if not t or "VERBOSE:" in t:
        return False
    if t[:1] == "[" and t[3:4] == ":" and t[6:7] == ":":  # [HH:MM:SS] pasos de Flet
        return True
    bajo = t.lower()
    return any(c in bajo for c in _CLAVES)


def correr(cmd, **kw):
    """Ejecuta y guarda TODA la salida en construir_apk.log. En pantalla muestra solo lo
    importante (la terminal de VS Code se cae con miles de líneas por segundo) y un punto
    cada 300 líneas para que se vea que sigue avanzando."""
    log("> " + " ".join(str(c) for c in cmd))
    env = dict(kw.pop("env", None) or os.environ, PYTHONUNBUFFERED="1")
    p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, encoding="utf-8", errors="replace", env=env, **kw)
    ocultas = 0
    with open(LOG, "a", encoding="utf-8") as f:
        for linea in p.stdout:
            linea = linea.rstrip()
            f.write(linea + "\n")
            if _importante(linea):
                if ocultas >= 300:
                    print(flush=True)
                print(linea[:200], flush=True)
                ocultas = 0
            else:
                ocultas += 1
                if ocultas % 300 == 0:
                    print(".", end="", flush=True)
    print(flush=True)
    if p.wait() != 0:
        raise subprocess.CalledProcessError(p.returncode, cmd)


def preparar_python():
    paso("1. Python para el TV (.venv_tv)")
    if not VPY.exists():
        correr([sys.executable, "-m", "venv", VENV])
    correr([VPY, "-m", "pip", "install", "--upgrade", "pip"])
    # flet-cli es el que tiene "flet build"; mismas versiones que el reproductor .exe
    correr([VPY, "-m", "pip", "install", "flet==1.0.3", "flet-cli==1.0.3",
            "flet-desktop==1.0.3", "flet-video", "yt-dlp", "requests"])


def regenerar_proyecto_android():
    """Hace que Flet vuelva a generar el proyecto de Android desde cero (sin borrar nada:
    solo invalida sus "huellas"). Así aplica lo de pyproject.toml (jni_flutter 1.0.3) y
    agrega él mismo las extensiones (flet_video) al pubspec.yaml. Las librerías de Python
    ya instaladas se conservan."""
    for nombre in ("template-1", "template-2"):
        huella = AQUI / "build" / ".hash" / nombre
        if huella.is_file():
            huella.write_text("regenerar", "utf-8")
    log("✓ El proyecto de Android se generará de nuevo (con jni_flutter 1.0.3)")


def flet_build(regenerar=False):
    if regenerar:
        regenerar_proyecto_android()
    paso("flet build apk (la primera vez descarga Flutter y Android: paciencia)")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", **variables_firma())
    correr([FLET, "build", "apk", "--yes", "-vv"], cwd=AQUI, env=env)


def variables_firma():
    """Firma con la llave propia (por variables de entorno: la contraseña no queda en el log)."""
    if not LLAVE.is_file():
        sys.exit(f"No encontré la llave de firma {LLAVE}. Sin ella los TV no podrán actualizar.")
    clave = os.environ.get("FLET_ANDROID_SIGNING_KEY_STORE_PASSWORD") or LLAVE_CLAVE.read_text("utf-8").strip()
    return {"FLET_ANDROID_SIGNING_KEY_STORE": str(LLAVE),
            "FLET_ANDROID_SIGNING_KEY_STORE_PASSWORD": clave,
            "FLET_ANDROID_SIGNING_KEY_PASSWORD": clave,
            "FLET_ANDROID_SIGNING_KEY_ALIAS": "playbargo_tv"}


def buscar_apks(carpeta):
    return sorted(Path(carpeta).rglob("*.apk"), key=lambda p: p.stat().st_mtime, reverse=True)


def ajustar_para_tv():
    """Agrega LEANBACK_LAUNCHER + banner al AndroidManifest que generó Flet."""
    manifiesto = FLUTTER_PROY / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    if not manifiesto.is_file():
        raise FileNotFoundError(f"No encontré {manifiesto}")
    xml = manifiesto.read_text("utf-8")
    if "LEANBACK_LAUNCHER" not in xml:
        xml, n = re.subn(
            r'(<category\s+android:name="android\.intent\.category\.LAUNCHER"\s*/>)',
            r'\1\n                <category android:name="android.intent.category.LEANBACK_LAUNCHER"/>',
            xml, count=1)
        if n == 0:
            raise RuntimeError("No encontré la categoría LAUNCHER en el AndroidManifest")
    if "android:banner" not in xml:
        xml = re.sub(r"<application\b", '<application android:banner="@drawable/banner"', xml, count=1)
    manifiesto.write_text(xml, "utf-8")
    dibujos = manifiesto.parent / "res" / "drawable"
    dibujos.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(AQUI / "assets" / "banner.png", dibujos / "banner.png")
    print("✓ AndroidManifest con LEANBACK_LAUNCHER y banner")


def main():
    os.chdir(AQUI)
    LOG.write_text("", encoding="utf-8")
    preparar_python()
    paso("2. Primera compilación")
    flet_build(regenerar=True)
    apk_flet = buscar_apks(AQUI / "build" / "apk")
    if not apk_flet:
        sys.exit("No se generó ningún .apk (mira los mensajes de arriba).")
    SALIDA.mkdir(exist_ok=True)
    respaldo = SALIDA / "PlayBarGO_TV_basico.apk"  # por si falla el paso 3
    shutil.copyfile(apk_flet[0], respaldo)
    final, con_tv = respaldo, False

    paso("3. Ajustes para Android TV (inicio del TV + banner)")
    try:
        ajustar_para_tv()
        # Flet conserva el proyecto Android si la configuración no cambió: al compilar
        # otra vez usa el AndroidManifest ya ajustado (y esta vez es mucho más rápido).
        flet_build()
        apks = buscar_apks(AQUI / "build" / "apk")
        xml = (FLUTTER_PROY / "android" / "app" / "src" / "main" / "AndroidManifest.xml").read_text("utf-8")
        if apks and "LEANBACK_LAUNCHER" in xml:
            final, con_tv = apks[0], True
    except Exception as ex:
        print(f"⚠️ No se pudo agregar el modo TV ({ex}). Uso el .apk normal de Flet.")

    paso("4. Listo")
    destino = SALIDA / "PlayBarGO_TV.apk"
    shutil.copyfile(final, destino)
    if con_tv:
        respaldo.unlink(missing_ok=True)
    mb = destino.stat().st_size / 1048576
    print(f"✅ {destino}  ({mb:.0f} MB)")
    print("   Sale en el inicio del TV." if con_tv else
          "   En Google TV ábrela desde Ajustes > Apps > PlayBar GO TV (en Fire TV sale sola).")
    print("   Cómo instalarlo en el TV: mira README_TV.md")
    if WIN:
        os.startfile(SALIDA)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as ex:
        log(f"\n❌ Falló un paso: {ex}")
        log("   Todo el detalle quedó en construir_apk.log")
        sys.exit(1)
