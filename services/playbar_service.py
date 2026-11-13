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


LOGO_PLAYBAR = "/logo.png"  # los negocios sin logo muestran el de PlayBar GO
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
_logos_db = {}


def imagen_logo(logo, codigo=None):
    """Lo que va en ft.Image(src=...) para el logo de un negocio:
    imagen subida en /super (bytes), dirección web, archivo de assets, o PlayBar GO."""
    logo = str(logo or "").strip()
    if not logo:
        return LOGO_PLAYBAR
    if logo.startswith("db:"):
        clave = (str(codigo), logo)
        if clave not in _logos_db:
            try:
                from services import db
                _logos_db[clave] = db.logo_bytes(codigo)
            except Exception as ex:
                print("⚠️ logo:", ex)
                return LOGO_PLAYBAR
        return _logos_db[clave] or LOGO_PLAYBAR
    if logo.startswith(("http://", "https://", "/")):
        return logo
    for carpeta in ("logos", ""):  # nombres viejos como "logoa33.png"
        if os.path.isfile(os.path.join(_ASSETS, carpeta, logo)):
            return f"/{carpeta}/{logo}" if carpeta else f"/{logo}"
    return LOGO_PLAYBAR


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


_llaves_malas = {}  # índice -> hasta cuándo no se usa (llave inválida, suspendida o sin cupo)
LLAVE_MALA_SEG = 6 * 3600


def buscar_youtube(query, page_token=None):
    global _api_index
    keys = _get_api_keys()
    if not keys:
        return {"items": [], "nextPageToken": None}

    for _ in range(len(keys)):
        if _llaves_malas.get(_api_index, 0) > time.time() and                 len(_llaves_malas) < len(keys):  # (si todas están malas, se intenta igual)
            _api_index = (_api_index + 1) % len(keys)
            continue
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
            print(f"❌ YouTube API #{_api_index + 1}:", data["error"].get("message", "error"))
            if response.status_code in (400, 403):
                # inválida, proyecto suspendido o cupo del día agotado: no se vuelve a probar en
                # un rato (cada intento fallido hacía más lenta la búsqueda del cliente)
                _llaves_malas[_api_index] = time.time() + LLAVE_MALA_SEG
        except Exception as ex:
            print("❌ Error buscando YouTube:", ex)
        _api_index = (_api_index + 1) % len(keys)

    return {"items": [], "nextPageToken": None}


def buscar_sin_llaves(query, cuantos=30):
    """Respaldo cuando ninguna llave de YouTube responde (inválidas o sin cupo del día): la
    misma búsqueda con yt-dlp, sin llave (como buscan los reproductores). Mismo formato."""
    try:
        import yt_dlp
        opts = {"quiet": True, "extract_flat": True, "skip_download": True, "no_warnings": True,
                "socket_timeout": 15}
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(f"ytsearch{cuantos}:{query}", download=False)
    except Exception as ex:
        print("❌ Búsqueda sin llave:", str(ex)[:120])
        return {"items": [], "nextPageToken": None}
    items = []
    for e in info.get("entries") or []:
        vid = e.get("id") or ""
        if len(vid) != 11 or e.get("live_status") in ("is_live", "is_upcoming"):
            continue
        miniatura = f"https://i.ytimg.com/vi/{vid}"
        items.append({"id": {"videoId": vid}, "snippet": {
            "title": e.get("title") or "",
            "channelTitle": e.get("channel") or e.get("uploader") or "",
            "thumbnails": {"default": {"url": f"{miniatura}/default.jpg"},
                           "medium": {"url": f"{miniatura}/mqdefault.jpg"},
                           "high": {"url": f"{miniatura}/hqdefault.jpg"}},
        }})
    print(f"✅ YouTube búsqueda sin llave: {len(items)} resultados")
    return {"items": items, "nextPageToken": None}


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
    if not data.get("items") and not page_token:
        data = buscar_sin_llaves(query)  # ninguna llave respondió: igual hay resultados
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
_candados = {}


def _candado_de(codigo):
    with _lock:
        return _candados.setdefault(codigo, threading.Lock())


# Cola "a la suerte": con más de MEZCLAR_DESDE - 1 canciones esperando, cada pedido nuevo
# revuelve la cola, para que el que pidió de último no espere hasta el final. La primera (la
# que suena enseguida, el reproductor ya la está preparando) no se mueve.
MEZCLAR_DESDE = int(os.getenv("COLA_MEZCLAR_DESDE", "0"))  # 0 = apagado: ahora decide la ruleta del reproductor


def mezclar_cola(cliente):
    import random
    from services import db
    try:
        filas = db.consultar(
            """SELECT id FROM pedidos WHERE codigo = %s AND ts >= %s AND estado <> 'Error'
               AND estado2 IN ('En cola', 'Siguiente') ORDER BY COALESCE(orden, id)""",
            (str(cliente), inicio_jornada()))
        ids = [f["id"] for f in filas]
        if MEZCLAR_DESDE <= 0 or len(ids) < MEZCLAR_DESDE:
            return False
        resto = ids[1:]
        random.shuffle(resto)
        db.reordenar(str(cliente), [ids[0]] + resto)
        print(f"🎲 Cola de {cliente} revuelta ({len(ids)} canciones)")
        return True
    except Exception as ex:
        print("⚠️ No se pudo revolver la cola:", ex)
        return False


def agregar_cancion(cliente, telefono, titulo, canal, video_id):
    from services import db
    if not _cliente(cliente):
        return {"ok": False, "error": "CLIENTE_INVALIDO"}
    from services import suscripcion
    permitido, mensaje = suscripcion.puede_pedir(cliente)
    if not permitido:  # prueba gratis terminada o plan vencido
        return {"ok": False, "error": "PLAN", "mensaje": mensaje}
    if str(video_id) in db.ids_eliminadas():
        db.restaurar_cancion(str(video_id))  # un cliente la pidió: vuelve (se baja de nuevo)
    try:
        # candado por negocio (evita duplicados por doble toque) sin frenar a los demás bares
        with _candado_de(str(cliente)):
            r = db.agregar_pedido(str(cliente), str(telefono), html.unescape(str(titulo)),
                                  html.unescape(str(canal)), str(video_id))
            if not r.get("duplicado"):
                mezclar_cola(cliente)
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
        from services import respaldo
        if respaldo.ES_RESPALDO:
            return  # el respaldo recibe los datos del principal: no migra nada
        try:
            import migrar_a_base
            migrar_a_base.migrar_automatica()
        except Exception as ex:
            print("⚠️ Migración automática no disponible:", ex)

    # En segundo plano: la app abre de una vez aunque la base tarde o la copia dure.
    threading.Thread(target=_arrancar, daemon=True).start()
