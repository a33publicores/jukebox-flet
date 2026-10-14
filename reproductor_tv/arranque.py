"""
Arranque de PlayBar GO TV con actualización del código sin reinstalar el .apk.

Este archivo va dentro del .apk y NO se actualiza nunca: es el que decide qué código usar.

  * El .apk trae su código (carpeta tv/). Esa es la versión "de fábrica".
  * tv/actualizador_tv.py baja versiones nuevas desde GitHub como un .zip con la carpeta
    tv/ completa y las deja en  <datos>/codigo/tv_<versión>.zip  (ver guardar_nueva).
  * Al abrir, si hay un .zip más nuevo que el de fábrica y no ha fallado, se usa ese
    (Python importa directo desde el .zip).
  * Protección: cada arranque con el .zip suma un intento; si la app funciona 90 s el
    código queda "ok". Si suma 3 intentos sin llegar a "ok" (se cierra o no arranca),
    se marca como fallida y se vuelve al código de fábrica.
  * Si el .zip ni siquiera se puede importar, se vuelve al de fábrica en el acto.

Todo lo de aquí es a prueba de errores: si algo falla, se usa el código de fábrica.
"""
import importlib
import json
import os
import re
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
MAX_INTENTOS = 3


def carpeta_datos():
    """La misma carpeta que usa tv/config.py (no se importa tv aquí a propósito)."""
    for var in ("PLAYBAR_TV_HOME", "FLET_APP_STORAGE_DATA"):
        v = os.environ.get(var, "").strip()
        if v:
            return Path(v)
    return Path.home() / "PlayBarGoTV"


CODIGO = carpeta_datos() / "codigo"
ESTADO = CODIGO / "estado.json"


def tupla(v):
    partes = []
    for x in str(v or "0").strip().lstrip("vV").split("."):
        num = "".join(c for c in x if c.isdigit())
        partes.append(int(num) if num else 0)
    while len(partes) < 3:
        partes.append(0)
    return tuple(partes[:3])


def version_de_fabrica():
    try:
        texto = (AQUI / "tv" / "version.py").read_text("utf-8")
        return re.search(r'^VERSION\s*=\s*["\']([^"\']+)', texto, re.M).group(1)
    except Exception:
        return "0.0.0"


def leer_estado():
    try:
        return json.loads(ESTADO.read_text("utf-8"))
    except Exception:
        return {}


def _guardar_estado(est):
    try:
        CODIGO.mkdir(parents=True, exist_ok=True)
        tmp = ESTADO.with_suffix(".tmp")
        tmp.write_text(json.dumps(est, indent=2), "utf-8")
        os.replace(tmp, ESTADO)
    except Exception as ex:
        print(f"ℹ️ arranque: no se pudo guardar el estado: {ex}")


# ------------------------------------------------------------ usado por el actualizador
def guardar_nueva(version, contenido_zip):
    """Deja lista una versión nueva (bytes del .zip ya revisado). Se usa al reiniciar."""
    CODIGO.mkdir(parents=True, exist_ok=True)
    destino = CODIGO / f"tv_{version}.zip"
    tmp = destino.with_suffix(".tmp")
    tmp.write_bytes(contenido_zip)
    os.replace(tmp, destino)
    est = leer_estado()
    est.update({"version": version, "archivo": destino.name, "intentos": 0, "ok": False})
    est.setdefault("fallidas", [])
    if version in est["fallidas"]:
        est["fallidas"].remove(version)
    _guardar_estado(est)
    # borra .zip viejos (deja el nuevo y el último que funcionó)
    bueno = (est.get("bueno") or {}).get("archivo")
    for p in CODIGO.glob("tv_*.zip"):
        if p.name not in (destino.name, bueno):
            try:
                p.unlink()
            except OSError:
                pass
    return destino


def registrar_ok(version):
    """La versión que corre funcionó un rato: ya no cuenta como intento fallido."""
    est = leer_estado()
    if est.get("version") == version and not est.get("ok"):
        est.update({"ok": True, "intentos": 0,
                    "bueno": {"version": version, "archivo": est.get("archivo")}})
        _guardar_estado(est)
        print(f"✅ Código {version} funcionando (queda como bueno)")


def fallidas():
    return list(leer_estado().get("fallidas", []))


# --------------------------------------------------------------------- arranque
_EN_USO = {"version": None, "origen": "fabrica", "zip": None}


def _olvidar_tv():
    """Saca de memoria el código tv cargado (para poder cargar otra versión)."""
    for nombre in list(sys.modules):
        if nombre == "tv" or nombre.startswith("tv."):
            del sys.modules[nombre]
    if _EN_USO["zip"] and _EN_USO["zip"] in sys.path:
        sys.path.remove(_EN_USO["zip"])
    importlib.invalidate_caches()


def _marcar_fallida(est, motivo):
    v = est.get("version")
    print(f"⚠️ El código {v} falló ({motivo}). Vuelvo a la última versión que funcionó.")
    est.setdefault("fallidas", [])
    if v and v not in est["fallidas"]:
        est["fallidas"].append(v)
    est["ok"] = False
    _guardar_estado(est)


def _probar(version, zip_):
    """Pone el .zip en sys.path y prueba importar la app. True si cargó."""
    sys.path.insert(0, str(zip_))
    _EN_USO.update(version=version, origen="descargado", zip=str(zip_))
    try:
        importlib.import_module("tv.app_tv")
        return True
    except Exception as ex:
        _EN_USO["error"] = f"{type(ex).__name__}: {ex}"
        _olvidar_tv()
        return False


def elegir_codigo():
    """Elige el código a usar y lo deja listo para importar. Devuelve (versión, origen).
    Orden: 1) la versión descargada más nueva (si no ha fallado), 2) la última que
    funcionó, 3) la del .apk."""
    _olvidar_tv()
    fabrica = version_de_fabrica()
    est = leer_estado()
    fall = est.get("fallidas", [])

    def sirve(v, archivo):
        return (v and archivo and (CODIGO / archivo).is_file()
                and tupla(v) > tupla(fabrica) and v not in fall)

    v, archivo = est.get("version"), est.get("archivo")
    if sirve(v, archivo):
        if not est.get("ok") and int(est.get("intentos", 0)) >= MAX_INTENTOS:
            _marcar_fallida(est, f"{MAX_INTENTOS} arranques sin terminar bien")
        else:
            if not est.get("ok"):
                est["intentos"] = int(est.get("intentos", 0)) + 1
                _guardar_estado(est)
            if _probar(v, CODIGO / archivo):
                return v, "descargado"
            _marcar_fallida(est, f"no se pudo cargar: {_EN_USO.get('error')}")

    bueno = est.get("bueno") or {}
    if bueno.get("version") != v and sirve(bueno.get("version"), bueno.get("archivo")):
        if _probar(bueno["version"], CODIGO / bueno["archivo"]):
            return bueno["version"], "descargado"

    _EN_USO.update(version=fabrica, origen="fabrica", zip=None)
    return fabrica, "fabrica"


async def main(page):
    """Corre la app. Si el actualizador dejó una versión nueva lista, recarga el código
    y sigue (sin cerrar la ventana ni reinstalar)."""
    primera = True
    while True:
        if primera and _EN_USO["version"] is not None:
            version, origen = _EN_USO["version"], _EN_USO["origen"]  # ya elegido en main.py
        else:
            version, origen = elegir_codigo()
        primera = False
        print(f"🧩 Código en uso: {version} ({'del .apk' if origen == 'fabrica' else 'actualizado'})")
        app = importlib.import_module("tv.app_tv")
        try:
            resultado = await app.main(page)
        except Exception as ex:
            print(f"❌ La app se cayó: {type(ex).__name__}: {ex}")
            if origen == "descargado":
                _marcar_fallida(leer_estado(), "se cayó")
                continue
            raise
        if resultado != "actualizar":
            return
        print("🔄 Cargando la versión nueva del código…")
        page.controls.clear()
        page.overlay.clear()
        page.update()
        time.sleep(0.2)
