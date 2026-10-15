"""
Actualización automática del reproductor de TV (solo el código Python, sin reinstalar).

De dónde sale la versión nueva:
  Releases de GitHub del repo REPO cuya etiqueta empieza por "tv-v" (ej. tv-v0.1.1) y
  que traen el archivo tv_codigo.zip. Se publican como "pre-release" para que el
  reproductor del PC (que solo mira la última release normal) no las vea.
  Las publica  publicar_tv.py.

Flujo en el TV (no hay que tocar nada):
  revisa al abrir (1 min después) y cada REVISAR_HORAS ->
  baja el .zip y lo revisa (que traiga todo y que el código no tenga errores) ->
  avisa en pantalla -> espera a que termine la canción (máx. 15 min) ->
  recarga el código sin cerrar la app (arranque.py). Si la versión nueva falla,
  arranque.py vuelve sola a la anterior.

Si en la descripción de la release hay una línea que dice solo  [ahora]  se instala sin
esperar a que termine la canción.
"""
import asyncio
import io
import time
import zipfile

import requests

from tv.version import VERSION

REPO = "a33publicores/jukebox-flet"   # si algún día se separa el TV, solo se cambia aquí
API = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
PREFIJO = "tv-v"
ACTIVO = "tv_codigo.zip"
REVISAR_HORAS = 3
ESPERA_MAX_SEG = 15 * 60
ARCHIVOS_NECESARIOS = ("tv/__init__.py", "tv/app_tv.py", "tv/motor.py", "tv/version.py",
                       "tv/descargas_tv.py", "tv/actualizador_tv.py")


def _arranque():
    try:
        import arranque
        return arranque
    except Exception:
        return None  # p. ej. corriendo sin arranque.py: entonces no se actualiza


def buscar(actual=VERSION, timeout=15):
    """La release de TV más nueva que la actual: {version, url, tamano, notas, ahora} o None."""
    r = requests.get(API, timeout=timeout, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"PlayBarGO-TV/{actual}"})
    r.raise_for_status()
    arr = _arranque()
    tupla = arr.tupla if arr else (lambda v: tuple(int(x) for x in v.split(".")))
    fallidas = set(arr.fallidas()) if arr else set()
    mejor = None
    for rel in r.json():
        etiqueta = str(rel.get("tag_name") or "")
        if rel.get("draft") or not etiqueta.startswith(PREFIJO):
            continue
        version = etiqueta[len(PREFIJO):]
        activo = next((a for a in rel.get("assets") or [] if a.get("name") == ACTIVO), None)
        if not activo or version in fallidas or tupla(version) <= tupla(actual):
            continue
        if mejor is None or tupla(version) > tupla(mejor["version"]):
            lineas = [l.strip() for l in str(rel.get("body") or "").replace("\r", "").split("\n")]
            mejor = {
                "version": version,
                "url": activo.get("browser_download_url"),
                "tamano": int(activo.get("size") or 0),
                "ahora": any(l.lower() == "[ahora]" for l in lineas),
                "notas": "\n".join(l for l in lineas if l and l.lower() != "[ahora]")[:300],
            }
    return mejor


def revisar_zip(contenido, version):
    """Que el .zip traiga la carpeta tv/ completa, de la versión anunciada y sin errores
    de sintaxis. Lanza ValueError si algo no cuadra."""
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        nombres = set(z.namelist())
        faltan = [n for n in ARCHIVOS_NECESARIOS if n not in nombres]
        if faltan:
            raise ValueError(f"al .zip le faltan: {', '.join(faltan)}")
        texto_version = z.read("tv/version.py").decode("utf-8")
        if f'"{version}"' not in texto_version and f"'{version}'" not in texto_version:
            raise ValueError(f"el .zip no es la versión {version}")
        for n in nombres:
            if n.endswith(".py"):
                compile(z.read(n).decode("utf-8"), n, "exec")  # SyntaxError si está mal


def descargar(info, timeout=60):
    """Baja y revisa el .zip; lo deja listo para el próximo arranque del código."""
    arr = _arranque()
    if arr is None:
        raise RuntimeError("falta arranque.py")
    r = requests.get(info["url"], timeout=timeout,
                     headers={"User-Agent": f"PlayBarGO-TV/{VERSION}"})
    r.raise_for_status()
    contenido = r.content
    if info.get("tamano") and len(contenido) != info["tamano"]:
        raise RuntimeError("la descarga quedó incompleta")
    if len(contenido) > 20 * 1024 * 1024:
        raise RuntimeError("el .zip es demasiado grande")
    revisar_zip(contenido, info["version"])
    return arr.guardar_nueva(info["version"], contenido)


async def revisar_ya():
    """Una revisión inmediata (antes de la pantalla de configuración, que corre sin música):
    True si bajó código nuevo y hay que recargar la app. Nunca lanza errores."""
    try:
        info = await asyncio.wait_for(asyncio.to_thread(buscar), 20)
        if not info:
            return False
        await asyncio.wait_for(asyncio.to_thread(descargar, info), 120)
        print(f"⬇️ Código {info['version']} descargado antes de configurar")
        return True
    except Exception as ex:
        print(f"ℹ️ Revisión de actualizaciones (sin configurar): {ex}")
        return False


def confirmar_que_funciona():
    """La app lleva un rato funcionando con este código: ya no se devuelve a la anterior."""
    arr = _arranque()
    if arr is not None:
        arr.registrar_ok(VERSION)


async def vigilar(motor, avisar, aplicar):
    """Tarea de fondo. avisar(texto) muestra un aviso en pantalla; aplicar() recarga la app."""
    await asyncio.sleep(60)  # primero que arranque la música
    while True:
        try:
            info = await asyncio.to_thread(buscar)
            if info:
                print(f"🔄 Hay código nuevo para el TV: {info['version']} (tengo {VERSION})")
                await asyncio.to_thread(descargar, info)
                print(f"⬇️ Código {info['version']} descargado y revisado")
                if not info["ahora"]:
                    avisar(f"⬆️ Actualización {info['version']} lista: se instala al "
                           "terminar esta canción.")
                    await _esperar_fin_cancion(motor)
                avisar(f"⬆️ Instalando la actualización {info['version']}…")
                await asyncio.sleep(1)
                aplicar()
                return
        except asyncio.CancelledError:
            raise
        except Exception as ex:
            print(f"ℹ️ Revisión de actualizaciones del TV: {ex}")
        await asyncio.sleep(REVISAR_HORAS * 3600)


async def _esperar_fin_cancion(motor):
    """Hasta que cambie la canción (o no esté sonando nada), máx. ESPERA_MAX_SEG."""
    inicio, token = time.time(), motor.token
    while time.time() - inicio < ESPERA_MAX_SEG:
        if motor.actual is None or motor.pausado or motor.token != token:
            return
        await asyncio.sleep(2)
