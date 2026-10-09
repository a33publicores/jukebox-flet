"""
Actualización automática del reproductor PlayBar GO.

De dónde sale la versión nueva (en este orden):
  1. La última "Release" publicada en GitHub (a33publicores/jukebox-flet) que traiga
     el archivo PlayBarGO_Reproductor_Setup.exe. La versión es la etiqueta (v1.1.1).
     Si en la descripción hay una línea que dice solo  [obligatoria]  el bar no puede
     dejarla para más tarde.
  2. Si no hay release: el archivo reproductor_version.json del repo (forma antigua).

Flujo en el bar:  aviso "Actualizar" -> descarga con barra de progreso ->
instalación silenciosa (Inno Setup) -> el reproductor se cierra y se abre solo con
la versión nueva. El código y la llave del bar se conservan (están en ~/PlayBarGo).

Nada de aquí lanza errores hacia la pantalla.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

from reproductor.version import RELEASES_URL, UPDATE_URL, VERSION

NOMBRE_INSTALADOR = "PlayBarGO_Reproductor_Setup.exe"
CARPETA_TMP = Path(tempfile.gettempdir()) / "PlayBarGO_actualizacion"


def _tupla(v):
    partes = []
    for x in str(v).strip().lstrip("vV").split("."):
        num = "".join(c for c in x if c.isdigit())
        partes.append(int(num) if num else 0)
    while len(partes) < 3:
        partes.append(0)
    return tuple(partes)


def es_mas_nueva(nueva, actual=VERSION):
    return _tupla(nueva) > _tupla(actual)


def _desde_release(url, timeout):
    r = requests.get(url, timeout=timeout,
                     headers={"Accept": "application/vnd.github+json",
                              "User-Agent": f"PlayBarGO-Reproductor/{VERSION}"})
    if r.status_code != 200:
        return None
    rel = r.json()
    if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
        return None
    activos = [a for a in rel.get("assets") or [] if str(a.get("name", "")).lower().endswith(".exe")]
    if not activos:
        return None
    exe = next((a for a in activos if a.get("name") == NOMBRE_INSTALADOR), activos[0])
    cuerpo = str(rel.get("body") or "")
    lineas = [l.strip() for l in cuerpo.replace("\r", "").split("\n")]
    obligatoria = any(l.lower() == "[obligatoria]" for l in lineas)
    notas = "\n".join(l for l in lineas if l and l.lower() != "[obligatoria]"
                      and not l.startswith("(") and l not in ("-", "Qué cambió:")).strip()
    return {
        "version": str(rel.get("tag_name") or "").lstrip("vV"),
        "url": exe.get("browser_download_url"),
        "tamano": int(exe.get("size") or 0),
        "notas": notas[:600],
        "obligatoria": obligatoria,
        "pagina": rel.get("html_url"),
    }


def _desde_json(url, timeout):
    r = requests.get(url, timeout=timeout, headers={"Cache-Control": "no-cache"})
    if r.status_code != 200:
        return None
    info = r.json()
    if not isinstance(info, dict) or not info.get("url"):
        return None
    return dict(info, version=str(info.get("version", "0")))


def hay_actualizacion(actual=VERSION, releases_url=RELEASES_URL, json_url=UPDATE_URL, timeout=10):
    """Dict con version/url/notas/obligatoria si hay una versión más nueva; si no, None."""
    for fuente, url in ((_desde_release, releases_url), (_desde_json, json_url)):
        if not url:
            continue
        try:
            info = fuente(url, timeout)
        except Exception as ex:
            print(f"ℹ️ No se pudo revisar actualizaciones ({url}): {ex}")
            continue
        if info and info.get("url"):
            if es_mas_nueva(info["version"], actual):
                print(f"🔄 Hay versión nueva: {info['version']} (tengo {actual})")
                return info
            return None  # la fuente respondió y no hay nada más nuevo
    return None


def descargar(info, progreso=None, carpeta=CARPETA_TMP, cancelado=lambda: False):
    """Baja el instalador. progreso(bajado, total) se llama cada ~0,3 s.
    Devuelve la ruta del archivo. Lanza excepción si falla (la pantalla la muestra)."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"PlayBarGO_Setup_{info.get('version', 'nueva')}.exe"
    parcial = destino.with_suffix(".part")
    esperado = int(info.get("tamano") or 0)
    if destino.is_file() and esperado and destino.stat().st_size == esperado:
        if progreso:
            progreso(esperado, esperado)
        return destino  # ya estaba bajado de un intento anterior

    with requests.get(info["url"], stream=True, timeout=30,
                      headers={"User-Agent": f"PlayBarGO-Reproductor/{VERSION}"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or esperado or 0)
        bajado, ultimo = 0, 0.0
        with open(parcial, "wb") as f:
            for trozo in r.iter_content(chunk_size=256 * 1024):
                if cancelado():
                    raise RuntimeError("Descarga cancelada")
                if not trozo:
                    continue
                f.write(trozo)
                bajado += len(trozo)
                if progreso and time.time() - ultimo > 0.3:
                    ultimo = time.time()
                    progreso(bajado, total)
    if total and bajado != total:
        raise RuntimeError(f"La descarga quedó incompleta ({bajado} de {total} bytes)")
    if bajado < 1_000_000:
        raise RuntimeError("El archivo descargado es demasiado pequeño; revisa la release")
    with open(parcial, "rb") as f:
        if f.read(2) != b"MZ":
            raise RuntimeError("El archivo descargado no es un instalador de Windows")
    if destino.exists():
        destino.unlink()
    parcial.rename(destino)
    if progreso:
        progreso(bajado, total or bajado)
    return destino


def puede_instalar_solo():
    """Solo el .exe en Windows se reinstala solo (en modo desarrollo se abre el navegador)."""
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def instalar(ruta):
    """Lanza el instalador en silencio, separado de este proceso. Quien llama debe
    cerrar el reproductor enseguida para que los archivos se puedan reemplazar.
    /RELANZAR hace que el instalador vuelva a abrir el reproductor al terminar."""
    log = Path(ruta).with_suffix(".log")
    args = [str(ruta), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
            "/CLOSEAPPLICATIONS", "/RELANZAR", f"/LOG={log}"]
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(args, creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"🔧 Instalando actualización: {' '.join(args)}")
    return args


def limpiar_viejos():
    """Borra instaladores de actualizaciones ya aplicadas."""
    try:
        for f in CARPETA_TMP.glob("PlayBarGO_Setup_*"):
            v = f.stem.replace("PlayBarGO_Setup_", "")
            if not es_mas_nueva(v):
                f.unlink()
    except Exception:
        pass
