"""
Sesión persistente de PlayBar GO (versión web / Railway).

Por qué existe: `page.session.store` vive en la memoria del servidor y se borra
cada vez que el navegador recarga (F5), se cierra la pestaña o el celular
suspende la página. Aquí la sesión se guarda en el DISPOSITIVO del usuario
(Flet SharedPreferences = localStorage del navegador), así que sobrevive a:
cerrar la app, F5, cambiar de app y reiniciar el servidor.

Solo se borra cuando el usuario pulsa "Cerrar sesión".
"""
import asyncio
import json

SESSION_KEY = "playbar_session"
_OBLIGATORIOS = ("codigo", "telefono")

# Último error de almacenamiento (para diagnóstico en el título de la pestaña).
estado = {"error": None}

_prefs_extra = {}
_tareas = set()


# ---------------------------------------------------------------------------
# Acceso a SharedPreferences
# ---------------------------------------------------------------------------
def _prefs(page):
    """Devuelve el servicio SharedPreferences de la página."""
    try:
        prefs = page.shared_preferences
        if prefs is not None:
            return prefs
    except Exception:
        pass

    # Respaldo: crear y registrar el servicio manualmente.
    clave = id(page)
    if clave not in _prefs_extra:
        import flet as ft

        prefs = ft.SharedPreferences()
        try:
            page.services.append(prefs)
        except Exception:
            pass
        _prefs_extra[clave] = prefs
    return _prefs_extra[clave]


def _decodificar(valor):
    if isinstance(valor, dict):
        return valor
    if isinstance(valor, str) and valor:
        try:
            return json.loads(valor)
        except Exception:
            return None
    return None


def _valida(datos):
    return isinstance(datos, dict) and all(datos.get(c) for c in _OBLIGATORIOS)


def _ejecutar(page, fn, *args):
    """
    Lanza la corrutina `fn(*args)` desde código síncrono (handlers de botones).
      - Si estamos en un hilo: usa page.run_task y espera el resultado.
      - Si estamos dentro del event loop: la deja corriendo en segundo plano.
    """
    try:
        asyncio.get_running_loop()
        en_loop = True
    except RuntimeError:
        en_loop = False

    try:
        if en_loop:
            tarea = asyncio.ensure_future(fn(*args))
            _tareas.add(tarea)
            tarea.add_done_callback(_tareas.discard)
            return
        futuro = page.run_task(fn, *args)
        futuro.result(timeout=8)
    except Exception as ex:
        estado["error"] = str(ex)
        print(f"⚠️ session_manager: {ex}")


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
async def cargar_sesion(page):
    """Lee la sesión guardada en el dispositivo. Devuelve dict o None."""
    try:
        valor = await _prefs(page).get(SESSION_KEY)
        datos = _decodificar(valor)
        if _valida(datos):
            print("✅ Sesión recuperada del dispositivo")
            return datos
        print("ℹ️ No hay sesión guardada")
        return None
    except Exception as ex:
        estado["error"] = str(ex)
        print(f"⚠️ No se pudo leer la sesión: {ex}")
        return None


def guardar_sesion(page, session):
    """Guarda la sesión (codigo, cliente, logo, telefono, modo) en el dispositivo."""
    texto = json.dumps(dict(session), ensure_ascii=False)

    async def _guardar():
        resultado = await _prefs(page).set(SESSION_KEY, texto)
        if resultado is False:
            raise RuntimeError("SharedPreferences.set devolvió False")
        print("✅ Sesión guardada en el dispositivo")

    _ejecutar(page, _guardar)


def cerrar_sesion(page):
    """Borra la sesión. Solo se llama desde el botón 'Cerrar sesión'."""

    async def _borrar():
        await _prefs(page).remove(SESSION_KEY)
        print("🗑️ Sesión eliminada del dispositivo")

    _ejecutar(page, _borrar)
