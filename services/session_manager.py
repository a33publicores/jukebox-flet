"""
Sesión persistente de PlayBar GO (app web en Railway).

La sesión vive en la BASE DE DATOS (tabla sesiones) y el navegador solo guarda una
llave larga y aleatoria, en DOS lugares:

  1. La dirección:  https://.../s/<llave>   → F5 la recupera al instante, sin
     preguntarle nada al celular (antes eso fallaba por tiempo agotado).
  2. El almacenamiento del dispositivo (SharedPreferences = localStorage) → al
     cerrar la app y volver a abrirla desde el ícono o el favorito.

Sirve para usuarios (teléfono), administradores del bar y el super administrador.
Solo se borra con "Cerrar sesión" / "Salir", o cuando vence:
usuario 30 días (se renueva con el uso), admin 24 h, super admin 12 h.
"""
import asyncio
import json

SESSION_KEY = "playbar_session"   # en el dispositivo: la llave (antes: el JSON completo)
PREFIJO_RUTA = "/s/"
ESPERA_DISPOSITIVO = 4            # segundos por intento al leer el almacenamiento

estado = {"error": None}
_prefs = {}    # id(page) -> SharedPreferences
_tokens = {}   # id(page) -> llave de la sesión actual
_tareas = set()


# ---------------------------------------------------------------------------
# Almacenamiento del dispositivo (con reintento si no responde)
# ---------------------------------------------------------------------------
def _nuevo_servicio(page):
    import flet as ft
    prefs = ft.SharedPreferences()  # en Flet 1.0 se registra solo en la página actual
    _prefs[id(page)] = prefs
    try:
        page.update()
    except Exception:
        pass
    return prefs


def _servicio(page):
    return _prefs.get(id(page)) or _nuevo_servicio(page)


def preparar_prefs(page):
    """Crear el servicio lo antes posible, para que el navegador ya lo tenga listo."""
    try:
        _servicio(page)
    except Exception as ex:
        print(f"⚠️ No se pudo preparar el almacenamiento: {ex}")


async def _con_reintento(page, metodo, *args):
    """Llama prefs.<metodo>; si el navegador no responde, recrea el servicio y reintenta."""
    ultimo = None
    for intento in range(2):
        prefs = _servicio(page) if intento == 0 else _nuevo_servicio(page)
        if intento:
            await asyncio.sleep(0.6)
        try:
            return await asyncio.wait_for(getattr(prefs, metodo)(*args), ESPERA_DISPOSITIVO)
        except Exception as ex:
            ultimo = ex
            if "Session closed" in str(ex) or "destroyed session" in str(ex):
                break
    estado["error"] = f"{type(ultimo).__name__}: {ultimo}"
    raise ultimo


def _en_segundo_plano(page, corrutina_fn, *args):
    """Lanza una tarea sin esperarla (sirve desde hilos y desde el event loop)."""
    try:
        asyncio.get_running_loop()
        tarea = asyncio.ensure_future(corrutina_fn(*args))
        _tareas.add(tarea)
        tarea.add_done_callback(_tareas.discard)
    except RuntimeError:
        try:
            page.run_task(corrutina_fn, *args)
        except Exception as ex:
            print(f"⚠️ session_manager: {ex}")


async def _poner_ruta(page, ruta):
    try:
        await asyncio.wait_for(page.push_route(ruta), ESPERA_DISPOSITIVO)
    except Exception as ex:
        print(f"ℹ️ No se pudo cambiar la dirección a {ruta}: {ex}")


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------
def _token_de_ruta(page):
    ruta = str(getattr(page, "route", "") or "")
    if PREFIJO_RUTA in ruta:
        return ruta.split(PREFIJO_RUTA, 1)[1].split("?")[0].strip("/") or None
    return None


async def cargar_sesion(page):
    """Recupera la sesión: primero de la dirección (F5), luego del dispositivo.
    Devuelve un dict con 'rol' (usuario/admin/super) o None."""
    from services import db

    token = _token_de_ruta(page)
    origen = "dirección"
    viejo = None
    if not token:
        origen = "dispositivo"
        try:
            valor = await _con_reintento(page, "get", SESSION_KEY)
        except Exception as ex:
            print(f"⚠️ No se pudo leer el almacenamiento del dispositivo: {ex}")
            valor = None
        if isinstance(valor, str) and valor.strip().startswith("{"):
            try:
                viejo = json.loads(valor)  # formato anterior: el JSON completo
            except Exception:
                viejo = None
        elif isinstance(valor, str) and valor.strip():
            token = valor.strip()

    datos = None
    if token:
        try:
            datos = await asyncio.to_thread(db.leer_sesion, token)
        except Exception as ex:
            print(f"⚠️ No se pudo leer la sesión en la base: {ex}")
    elif viejo and viejo.get("codigo") and viejo.get("telefono"):
        guardar_sesion(page, viejo)  # se pasa al formato nuevo
        datos = dict(viejo, rol="usuario", token=_tokens.get(id(page)))

    if not datos:
        print(f"ℹ️ No hay sesión guardada ({origen})")
        return None
    _tokens[id(page)] = datos.get("token")
    if origen == "dispositivo":  # deja la llave en la dirección para que F5 sea instantáneo
        _en_segundo_plano(page, _poner_ruta, page, PREFIJO_RUTA + datos["token"])
    print(f"✅ Sesión recuperada ({origen}, {datos.get('rol')})")
    return datos


def guardar_sesion(page, session, rol="usuario"):
    """Crea la sesión en la base y deja la llave en la dirección y en el dispositivo.
    No espera al navegador: la persona entra de una vez."""
    from services import db

    anterior = _tokens.get(id(page))
    try:
        token = db.crear_sesion(dict(session), rol)
    except Exception as ex:
        estado["error"] = str(ex)
        print(f"⚠️ No se pudo crear la sesión en la base: {ex}")
        return None
    _tokens[id(page)] = token
    if anterior and anterior != token:
        try:
            db.borrar_sesion(anterior)
        except Exception:
            pass

    async def _guardar():
        await _poner_ruta(page, PREFIJO_RUTA + token)
        try:
            await _con_reintento(page, "set", SESSION_KEY, token)
            print(f"✅ Sesión guardada ({rol})")
        except Exception as ex:
            print(f"⚠️ La sesión quedó en la dirección pero no en el dispositivo: {ex}")

    _en_segundo_plano(page, _guardar)
    return token


def cerrar_sesion(page):
    """Borra la sesión (botón 'Cerrar sesión' / 'Salir')."""
    from services import db

    token = _tokens.pop(id(page), None)
    try:
        db.borrar_sesion(token)
    except Exception as ex:
        print(f"⚠️ No se pudo borrar la sesión en la base: {ex}")

    async def _borrar():
        await _poner_ruta(page, "/")
        try:
            await _con_reintento(page, "remove", SESSION_KEY)
            print("🗑️ Sesión eliminada")
        except Exception as ex:
            print(f"⚠️ No se pudo borrar la llave del dispositivo: {ex}")

    _en_segundo_plano(page, _borrar)
