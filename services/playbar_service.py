"""
Servicios de PlayBar GO para la app web (Railway).

Los datos (negocios, pedidos, admins) están en PostgreSQL (services/db.py).
Ya no se usa Google Sheets ni la playlist de YouTube: solo la búsqueda de YouTube.
"""
import html
import os
import threading
import time

import requests

# Hora de Colombia (UTC-5, sin horario de verano).
ZONA_HORAS = float(os.getenv("ZONA_HORARIA_HORAS", "-5"))
# La "noche" del bar empieza a esta hora: lo pedido desde entonces es de HOY; lo de antes
# es historial para el aleatorio. Con 0 se corta a medianoche.
JORNADA_HORA = int(os.getenv("JORNADA_HORA", "6"))
CACHE_BUSQUEDA_SEG = 172800  # 2 días

_lock = threading.RLock()
_api_keys = None
_api_index = 0
_ram_cache = {}
_clientes_cache = {}
CLIENTES_CACHE_SEG = 30


# ---------------------------------------------------------------------------
# Hora de Colombia y jornada
# ---------------------------------------------------------------------------
def ahora_local_txt(t=None):
    """Fecha y hora de Colombia, formato AAAA-MM-DD HH:MM:SS."""
    t = time.time() if t is None else float(t)
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(t + ZONA_HORAS * 3600))


def epoch_local(texto):
    """Texto en hora de Colombia -> epoch. None si no se entiende."""
    import calendar
    try:
        t = calendar.timegm(time.strptime(str(texto).strip()[:19], "%Y-%m-%d %H:%M:%S"))
        return t - ZONA_HORAS * 3600
    except Exception:
        return None


def inicio_jornada(ahora=None):
    """Epoch del inicio de la jornada actual (hoy a las JORNADA_HORA, hora de Colombia)."""
    ahora = time.time() if ahora is None else ahora
    local = ahora + ZONA_HORAS * 3600
    dia = local - (local % 86400)
    inicio = dia + JORNADA_HORA * 3600
    if local < inicio:
        inicio -= 86400
    return inicio - ZONA_HORAS * 3600


def es_de_hoy(texto_o_epoch):
    t = texto_o_epoch if isinstance(texto_o_epoch, (int, float)) else epoch_local(texto_o_epoch)
    return t is not None and t >= inicio_jornada()


# ---------------------------------------------------------------------------
# Negocios
# ---------------------------------------------------------------------------
def _cliente(codigo):
    """Negocio por código, con caché corta (se consulta en cada acción de la app)."""
    from services import db
    codigo = str(codigo or "").strip()
    c = _clientes_cache.get(codigo)
    if c and time.time() - c[1] < CLIENTES_CACHE_SEG:
        return c[0]
    fila = db.cliente(codigo)
    _clientes_cache[codigo] = (fila, time.time())
    return fila


def olvidar_cliente(codigo=None):
    """El super admin cambió un negocio: no usar la copia en memoria."""
    if codigo is None:
        _clientes_cache.clear()
    else:
        _clientes_cache.pop(str(codigo), None)


def obtener_config_cliente(codigo):
    c = _cliente(codigo)
    if not c:
        return None
    return {"sheet": c["nombre"], "nombre": c["nombre"], "playlist": c["playlist"],
            "logo": c["logo"], "activo": c["activo"]}


def validar_cliente(codigo):
    try:
        c = _cliente(codigo)
        if c and c["activo"]:
            return {"ok": True, "nombre": c["nombre"], "logo": c["logo"]}
        return {"ok": False}
    except Exception as ex:
        print("❌ ERROR validar_cliente:", ex)
        return {"ok": False, "error": str(ex)}


# ---------------------------------------------------------------------------
# Búsqueda de YouTube (con caché en la base)
# ---------------------------------------------------------------------------
def _normalizar_query(q):
    return str(q or "").strip().lower()


def _get_api_keys():
    global _api_keys
    if _api_keys is None:
        value = os.getenv("YOUTUBE_API_KEYS", "").strip()
        _api_keys = [x.strip() for x in value.split(",") if x.strip()]
        if not _api_keys:
            print("⚠️ YOUTUBE_API_KEYS no está configurada")
    return _api_keys


def _compactar_busqueda(data):
    """Deja solo lo que usa la app (título, canal, miniatura, id)."""
    items = []
    for it in data.get("items", []):
        sn = it.get("snippet", {})
        thumbs = {
            k: {"url": v.get("url", "")}
            for k, v in (sn.get("thumbnails") or {}).items()
            if isinstance(v, dict) and k in ("default", "medium", "high")
        }
        vid = (it.get("id") or {}).get("videoId", "")
        if not vid:
            continue
        items.append({
            "id": {"videoId": vid},
            "snippet": {
                "title": html.unescape(sn.get("title", "")),
                "channelTitle": html.unescape(sn.get("channelTitle", "")),
                "thumbnails": thumbs,
            },
        })
    return {"items": items, "nextPageToken": data.get("nextPageToken")}


def buscar_youtube(query, page_token=None):
    global _api_index
    keys = _get_api_keys()
    if not keys:
        return {"items": [], "nextPageToken": None}

    for _ in range(len(keys)):
        key = keys[_api_index]
        params = {"part": "snippet", "q": query, "type": "video", "maxResults": 50, "key": key}
        if page_token:
            params["pageToken"] = page_token
        try:
            response = requests.get("https://www.googleapis.com/youtube/v3/search",
                                    params=params, timeout=20)
            data = response.json()
            if "error" not in data:
                print(f"✅ YouTube búsqueda OK (API #{_api_index + 1}): "
                      f"{len(data.get('items', []))} resultados")
                return _compactar_busqueda(data)
            print("❌ YouTube API:", data["error"].get("message", "error"))
        except Exception as ex:
            print("❌ Error buscando YouTube:", ex)
        _api_index = (_api_index + 1) % len(keys)

    return {"items": [], "nextPageToken": None}


def buscar(query, page_token=None):
    from services import db
    query = _normalizar_query(query)
    if len(query) < 3:
        return {"items": [], "nextPageToken": None}

    with _lock:
        cached = _ram_cache.get(query)
        if cached and time.time() - cached[1] < CACHE_BUSQUEDA_SEG:
            return cached[0]

    try:
        cached = db.busqueda(query, CACHE_BUSQUEDA_SEG)
        # las búsquedas viejas de Sheets venían recortadas a ~10: se rehacen
        if cached and len(cached.get("items", [])) >= 20:
            with _lock:
                _ram_cache[query] = (cached, time.time())
            return cached
    except Exception as ex:
        print("⚠️ Error leyendo caché de búsquedas:", ex)

    data = buscar_youtube(query, page_token)
    if data.get("items"):
        with _lock:
            _ram_cache[query] = (data, time.time())
        try:
            db.guardar_busqueda(query, data)
        except Exception as ex:
            print("⚠️ Error guardando caché de búsquedas:", ex)
    return data


# ---------------------------------------------------------------------------
# Pedidos
# ---------------------------------------------------------------------------
def agregar_cancion(cliente, telefono, titulo, canal, video_id):
    from services import db
    if not _cliente(cliente):
        return {"ok": False, "error": "CLIENTE_INVALIDO"}
    try:
        with _lock:
            r = db.agregar_pedido(str(cliente), str(telefono), html.unescape(str(titulo)),
                                  html.unescape(str(canal)), str(video_id))
        if r.get("duplicado"):
            print(f"⚠️ Canción ya activa para {cliente}: {video_id}")
        else:
            print("✅ GUARDADO OK")
        return r
    except Exception as ex:
        print("❌ ERROR GUARDANDO PEDIDO:", ex)
        return {"ok": False, "error": str(ex)}


def estado_usuario(cliente, telefono):
    from services import db
    try:
        mios = db.pedidos_de_usuario(str(cliente), str(telefono))
        if not mios:
            return {"pendientes": 0, "ultima_cancion": "", "estado": ""}
        inicio = inicio_jornada()
        pendientes = sum(1 for r in mios if r["estado2"] in ("En cola", "En reproduccion", "Siguiente")
                         and float(r["ts"]) >= inicio)
        return {"pendientes": pendientes, "ultima_cancion": mios[0]["titulo"],
                "estado": mios[0]["estado"]}
    except Exception as ex:
        print("❌ ERROR estado_usuario:", ex)
        return {}


def estado_cola(cliente):
    from services import cola
    try:
        snap = cola.instantanea(cliente)
        return {"ok": True, "actual": snap.actual.titulo if snap.actual else "",
                "siguiente": snap.cola[0].titulo if snap.cola else ""}
    except Exception as ex:
        print("❌ ERROR estado_cola:", ex)
        return {"ok": False}


def obtener_mis_canciones(cliente, telefono):
    from services import db
    try:
        return [{"titulo": r["titulo"], "canal": r["canal"], "estado": r["estado"]}
                for r in db.pedidos_de_usuario(str(cliente), str(telefono))]
    except Exception as ex:
        print("❌ ERROR mis_canciones:", ex)
        return []


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------
def iniciar_procesador():
    """Se llama al arrancar la app web: prepara la base de datos."""
    from services import db
    if not db.disponible():
        print("❌ Falta DATABASE_URL: agrega PostgreSQL al proyecto de Railway "
              "y la variable DATABASE_URL a este servicio.")
        return
    def _arrancar():
        try:
            db.asegurar()
            print(f"🩺 Base OK: {len(db.clientes())} negocios")
        except Exception as ex:
            print("❌ No se pudo conectar a la base de datos:", ex)
            return
        try:
            import migrar_a_base
            migrar_a_base.migrar_automatica()
        except Exception as ex:
            print("⚠️ Migración automática no disponible:", ex)

    # En segundo plano: la app abre de una vez aunque la base tarde o la copia dure.
    threading.Thread(target=_arrancar, daemon=True).start()
