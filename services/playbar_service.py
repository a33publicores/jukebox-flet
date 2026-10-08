"""
Servicios directos de PlayBar GO.

Esta capa reemplaza el antiguo Flask/Bot. Flet llama directamente a
Google Sheets y YouTube desde el mismo proceso Python.
"""
import base64
import json
import os
import threading
import time
from collections import Counter

import gspread
import requests
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


SPREADSHEET_ID = "1F1SMAyyY1iUKRX5QjiyrrMmv7W4z27gBsRMS8ZVGNS0"
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube"]

TOKEN_CONFIG = [
    ("YOUTUBE_TOKEN1_B64", "token1.json"),
    ("YOUTUBE_TOKEN2_B64", "token2.json"),
]

# Con MODO_REPRODUCTOR=propio las canciones entran directo a la cola de la hoja y NO
# se usa la playlist de YouTube (sin gastar cuota de tokens).
# Por defecto sigue el modo anterior (playlist de YouTube). Poner MODO_REPRODUCTOR=propio
# cuando el reproductor de escritorio esté instalado y probado.
MODO_PROPIO = os.getenv("MODO_REPRODUCTOR", "propio").strip().lower() != "youtube"

# Hora de Colombia (UTC-5, sin horario de verano) para la columna Timestamp.
ZONA_HORAS = float(os.getenv("ZONA_HORARIA_HORAS", "-5"))
# La "noche" del bar empieza a esta hora: lo pedido desde entonces es de HOY; lo de antes
# es historial para el aleatorio. Con 0 se corta a medianoche.
JORNADA_HORA = int(os.getenv("JORNADA_HORA", "6"))


def ahora_local_txt():
    """Fecha y hora de Colombia, formato de la hoja."""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() + ZONA_HORAS * 3600))


def epoch_local(texto):
    """Timestamp de la hoja (hora de Colombia) -> epoch. None si no se entiende."""
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


def es_de_hoy(texto):
    t = epoch_local(texto)
    return t is not None and t >= inicio_jornada()
# Una solicitud solo cuenta como "ya está en la lista" si es reciente. Una canción
# pedida hace días (aunque su fila quedara con un estado viejo) se puede volver a pedir.
VENTANA_DUPLICADO_HORAS = float(os.getenv("DUPLICADO_HORAS", "12"))
ESTADOS_ACTIVOS = {"En cola", "En reproduccion", "Siguiente"}

_lock = threading.RLock()
_google = None
_spreadsheet = None
_sheet_cache = None
_api_keys = None
_api_index = 0
_token_index = 0
_ram_cache = {}
_worker_started = False


def _secret_json(variable, local_file=None):
    value = os.getenv(variable, "").strip()
    if value:
        return json.loads(base64.b64decode(value).decode("utf-8"))
    if local_file and os.path.exists(local_file):
        with open(local_file, "r", encoding="utf-8") as f:
            return json.load(f)
    raise FileNotFoundError(
        f"No se encontró {variable} en Railway ni el archivo local {local_file or ''}."
    )


def _init_google():
    global _google, _spreadsheet, _sheet_cache
    with _lock:
        if _spreadsheet is not None:
            return
        data = _secret_json("GOOGLE_CREDENTIALS_B64",
                            os.getenv("PLAYBAR_CREDENCIALES", "credenciales.json"))
        creds = service_account.Credentials.from_service_account_info(
            data, scopes=GOOGLE_SCOPES
        )
        _google = gspread.authorize(creds)
        _spreadsheet = _google.open_by_key(SPREADSHEET_ID)
        _sheet_cache = _spreadsheet.worksheet("CACHE")
        print("✅ Google Sheets conectado")


def _spreadsheet_obj():
    _init_google()
    return _spreadsheet


def obtener_hoja_cliente(nombre):
    spreadsheet = _spreadsheet_obj()
    try:
        return spreadsheet.worksheet(nombre)
    except Exception:
        print("🆕 Creando hoja:", nombre)
        return spreadsheet.add_worksheet(title=nombre, rows="1000", cols="10")


def obtener_config_cliente(codigo):
    sheet = _spreadsheet_obj().worksheet("CLIENTES")
    for row in sheet.get_all_records():
        codigo_sheet = str(row.get("Codigo", row.get("codigo", ""))).strip()
        if codigo_sheet == str(codigo).strip():
            return {
                "sheet": row.get("Nombre", row.get("nombre", "")),
                "playlist": row.get("Playlist", row.get("playlist", "")),
                "logo": row.get("Logo", row.get("logo", "")),
            }
    return None


def validar_cliente(codigo):
    try:
        sheet = _spreadsheet_obj().worksheet("CLIENTES")
        for row in sheet.get_all_records():
            codigo_sheet = str(row.get("Codigo", row.get("codigo", ""))).strip()
            activo = str(row.get("Activo", row.get("activo", ""))).upper().strip()
            if codigo_sheet == str(codigo).strip() and activo == "TRUE":
                return {
                    "ok": True,
                    "nombre": row.get("Nombre", row.get("nombre", "")),
                    "logo": row.get("Logo", row.get("logo", "")),
                }
        return {"ok": False}
    except Exception as ex:
        print("❌ ERROR validar_cliente:", ex)
        return {"ok": False, "error": str(ex)}


def _normalizar_query(q):
    return str(q or "").strip().lower()


def _get_cache_sheet(query):
    query = _normalizar_query(query)
    rows = _sheet_cache.get_all_values()
    for row in rows[1:]:
        if len(row) >= 3 and row[0] == query:
            try:
                return json.loads(row[1])
            except Exception:
                return None
    return None


def _compactar_busqueda(data):
    """Deja solo lo que usa la app. Los resultados completos de YouTube pasan
    de 50.000 caracteres (límite de una celda de Sheets) y la caché fallaba."""
    items = []
    for it in data.get("items", []):
        sn = it.get("snippet", {})
        thumbs = {
            k: {"url": v.get("url", "")}
            for k, v in (sn.get("thumbnails") or {}).items()
            if isinstance(v, dict)
        }
        items.append({
            "id": {"videoId": (it.get("id") or {}).get("videoId", "")},
            "snippet": {
                "title": sn.get("title", ""),
                "channelTitle": sn.get("channelTitle", ""),
                "thumbnails": thumbs,
            },
        })
    return {"items": items, "nextPageToken": data.get("nextPageToken")}


def _set_cache_sheet(query, data):
    data = _compactar_busqueda(data)
    # Respaldo: si aún excede el límite de celda, recortar resultados.
    while len(json.dumps(data, ensure_ascii=False)) > 45000 and data["items"]:
        data["items"] = data["items"][:-5]
    _sheet_cache.append_row([
        _normalizar_query(query),
        json.dumps(data, ensure_ascii=False),
        str(time.time()),
    ])


def _get_api_keys():
    global _api_keys
    if _api_keys is None:
        value = os.getenv("YOUTUBE_API_KEYS", "").strip()
        _api_keys = [x.strip() for x in value.split(",") if x.strip()]
        if not _api_keys:
            print("⚠️ YOUTUBE_API_KEYS no está configurada")
    return _api_keys


def buscar_youtube(query, page_token=None):
    global _api_index
    keys = _get_api_keys()
    if not keys:
        return {"items": [], "nextPageToken": None}

    for _ in range(len(keys)):
        key = keys[_api_index]
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": 50,
            "key": key,
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            response = requests.get(
                "https://www.googleapis.com/youtube/v3/search",
                params=params,
                timeout=20,
            )
            data = response.json()
            if "error" not in data:
                print(f"✅ YouTube búsqueda OK (API #{_api_index + 1})")
                return {
                    "items": data.get("items", []),
                    "nextPageToken": data.get("nextPageToken"),
                }
            print("❌ YouTube API:", data["error"].get("message", "error"))
        except Exception as ex:
            print("❌ Error buscando YouTube:", ex)
        _api_index = (_api_index + 1) % len(keys)

    return {"items": [], "nextPageToken": None}


def buscar(query, page_token=None):
    query = _normalizar_query(query)
    if len(query) < 3:
        return {"items": [], "nextPageToken": None}

    with _lock:
        cached = _ram_cache.get(query)
        if cached and time.time() - cached[1] < 172800:
            print("⚡ Cache RAM usado")
            return cached[0]

    try:
        cached = _get_cache_sheet(query)
        if cached:
            with _lock:
                _ram_cache[query] = (cached, time.time())
            print("📄 Cache Sheets usado")
            return cached
    except Exception as ex:
        print("⚠️ Error leyendo cache Sheets:", ex)

    data = buscar_youtube(query, page_token)
    if data.get("items"):
        with _lock:
            _ram_cache[query] = (data, time.time())
        try:
            _set_cache_sheet(query, data)
        except Exception as ex:
            print("⚠️ Error guardando cache Sheets:", ex)

    return data


def _edad_horas(texto):
    """Horas desde el Timestamp de la fila (hora de Colombia). None si no se entiende."""
    t = epoch_local(texto)
    return None if t is None else (time.time() - t) / 3600.0


def solicitud_activa_existe(sheet, video_id, excluir_fila=None, registros=None):
    """True si ESA canción ya está esperando o sonando (pedida hace poco).

    Evita que la misma canción quede dos veces seguidas en la lista. Las solicitudes
    viejas (más de VENTANA_DUPLICADO_HORAS) no cuentan: si hace días la pidieron y su
    fila quedó con un estado atascado, la canción se puede volver a pedir.
    """
    video_id = str(video_id or "").strip()
    if not video_id:
        return False
    try:
        registros = registros if registros is not None else sheet.get_all_records()
        for indice, row in enumerate(registros, start=2):
            if excluir_fila is not None and indice == excluir_fila:
                continue
            if str(row.get("videoId", "")).strip() != video_id:
                continue
            edad = _edad_horas(row.get("Timestamp", row.get("timestamp", "")))
            if edad is None or edad > VENTANA_DUPLICADO_HORAS:
                continue
            estado = str(row.get("Estado", "")).strip()
            estado2 = str(row.get("Estado2", "")).strip()
            if estado in {"Pendiente", "Procesando"}:
                return True
            if estado == "Agregado" and estado2 in ESTADOS_ACTIVOS:
                return True
    except Exception as ex:
        print("⚠️ No se pudo verificar solicitud activa:", ex)
    return False


def agregar_cancion(cliente, telefono, titulo, canal, video_id):
    config = obtener_config_cliente(cliente)
    if not config:
        return {"ok": False, "error": "CLIENTE_INVALIDO"}

    try:
        sheet = obtener_hoja_cliente(config["sheet"])
        # La comprobación y el append deben ser una única sección crítica.
        # Así dos clics/solicitudes simultáneas no pueden pasar ambas la
        # comprobación de duplicado antes de guardar en Google Sheets.
        with _lock:
            if solicitud_activa_existe(sheet, video_id):
                print(f"⚠️ Canción ya activa para {cliente}: {video_id}")
                return {"ok": True, "duplicado": True}

            _con_reintentos(sheet.append_row, [
                ahora_local_txt(),
                str(cliente),
                str(telefono),
                str(titulo),
                str(canal),
                str(video_id),
                "Agregado" if MODO_PROPIO else "Pendiente",
                "Siguiente" if MODO_PROPIO else "",
            ])

        print("✅ GUARDADO OK")
        return {"ok": True}
    except Exception as ex:
        print("❌ ERROR GUARDANDO EN SHEETS:", ex)
        return {"ok": False, "error": str(ex)}


def _con_reintentos(fn, *args, intentos=4, **kwargs):
    """Ejecuta una operación de Sheets reintentando ante límite de cuota (429) o 5xx."""
    espera = 2
    for n in range(intentos):
        try:
            return fn(*args, **kwargs)
        except Exception as ex:
            texto = str(ex)
            temporal = any(c in texto for c in ("429", "500", "502", "503", "504", "Quota exceeded"))
            if not temporal or n == intentos - 1:
                raise
            print(f"⏳ Sheets ocupado ({texto[:80]}); reintento en {espera}s")
            time.sleep(espera)
            espera *= 2


def estado_usuario(cliente, telefono):
    try:
        config = obtener_config_cliente(cliente)
        if not config:
            return {}
        rows = obtener_hoja_cliente(config["sheet"]).get_all_records()
        mine = [
            r for r in rows
            if str(r.get("Usuario", "")).strip() == str(telefono).strip()
            or str(r.get("telefono", "")).strip() == str(telefono).strip()
        ]
        if not mine:
            return {"pendientes": 0, "ultima_cancion": "", "estado": ""}
        if MODO_PROPIO:
            pendientes = sum(
                1 for r in mine
                if str(r.get("Estado2", "")).strip() in ESTADOS_ACTIVOS
                and es_de_hoy(r.get("Timestamp", ""))
            )
        else:
            pendientes = sum(
                1 for r in mine
                if str(r.get("Estado", "")).strip()
                in {"Pendiente", "Procesando", "Agregado"}
            )
        last = mine[-1]
        return {
            "pendientes": pendientes,
            "ultima_cancion": last.get("titulo", ""),
            "estado": last.get("Estado", ""),
        }
    except Exception as ex:
        print("❌ ERROR estado_usuario:", ex)
        return {}


def estado_cola(cliente):
    try:
        config = obtener_config_cliente(cliente)
        if not config:
            return {"ok": False}
        rows = obtener_hoja_cliente(config["sheet"]).get_all_records()
        actual = ""
        siguiente = ""
        idx = -1
        for i, row in enumerate(rows):
            if row.get("Estado2") == "En reproduccion" and (
                    not MODO_PROPIO or es_de_hoy(row.get("Timestamp", ""))):
                actual = row.get("titulo", "")
                idx = i
                break

        def en_espera(row):
            if str(row.get("Estado2", "")).strip() in {"En cola", "Siguiente"}:
                return (not MODO_PROPIO) or es_de_hoy(row.get("Timestamp", ""))
            return (not MODO_PROPIO) and row.get("Estado") == "Agregado"

        for row in rows[idx + 1:]:
            if en_espera(row):
                siguiente = row.get("titulo", "")
                break
        return {"ok": True, "actual": actual, "siguiente": siguiente}
    except Exception as ex:
        print("❌ ERROR estado_cola:", ex)
        return {"ok": False}


def obtener_mis_canciones(cliente, telefono):
    try:
        config = obtener_config_cliente(cliente)
        if not config:
            return []
        rows = obtener_hoja_cliente(config["sheet"]).get_all_records()
        return [
            {
                "titulo": r.get("titulo", ""),
                "canal": r.get("canal", ""),
                "estado": r.get("Estado", ""),
            }
            for r in rows
            if str(r.get("Usuario", r.get("telefono", ""))).strip()
            == str(telefono).strip()
        ]
    except Exception as ex:
        print("❌ ERROR mis_canciones:", ex)
        return []


def _tokens_disponibles():
    """Índices de TOKEN_CONFIG con credencial (variable Railway o archivo local)."""
    disponibles = []
    for i, (variable, local_file) in enumerate(TOKEN_CONFIG):
        if os.getenv(variable, "").strip() or (local_file and os.path.exists(local_file)):
            disponibles.append(i)
    return disponibles


def _token_credentials():
    global _token_index
    disponibles = _tokens_disponibles()
    if not disponibles:
        raise RuntimeError("No hay tokens de YouTube configurados")
    if _token_index not in disponibles:
        _token_index = disponibles[0]

    variable, local_file = TOKEN_CONFIG[_token_index]
    data = _secret_json(variable, local_file)
    creds = Credentials.from_authorized_user_info(data, YOUTUBE_SCOPES)
    if not creds.valid:
        # Refrescar aquí permite ver el error real (p. ej. invalid_grant =
        # token vencido/revocado) en vez de fallar en silencio más adelante.
        from google.auth.transport.requests import Request

        creds.refresh(Request())
    return creds


def _youtube():
    return build("youtube", "v3", credentials=_token_credentials(), cache_discovery=False)


def _siguiente_token():
    global _token_index
    disponibles = _tokens_disponibles() or list(range(len(TOKEN_CONFIG)))
    pos = disponibles.index(_token_index) if _token_index in disponibles else -1
    _token_index = disponibles[(pos + 1) % len(disponibles)]
    print(f"🔄 Cambiando a credencial YouTube #{_token_index + 1}")


def video_ya_existe(youtube, playlist_id, video_id):
    page_token = None
    while True:
        kwargs = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        response = youtube.playlistItems().list(**kwargs).execute()
        for item in response.get("items", []):
            if item["snippet"]["resourceId"]["videoId"] == video_id:
                return True
        page_token = response.get("nextPageToken")
        if not page_token:
            return False


def actualizar_estados(sheet):
    try:
        data = sheet.get_all_records()
        for i, row in enumerate(data, start=2):
            if row.get("Estado2") in {"En reproduccion", "Siguiente"}:
                _con_reintentos(sheet.update_cell, i, 8, "")
        data = sheet.get_all_records()
        pendientes = [
            (i, row) for i, row in enumerate(data, start=2)
            if str(row.get("Estado", "")).strip() == "Agregado"
            and str(row.get("Estado2", "")).strip() != "Reproducido"
        ]
        if pendientes:
            _con_reintentos(sheet.update_cell, pendientes[0][0], 8, "En reproduccion")
        if len(pendientes) > 1:
            _con_reintentos(sheet.update_cell, pendientes[1][0], 8, "Siguiente")
    except Exception as ex:
        print("⚠️ No se pudieron actualizar estados:", ex)


def _procesar_fila(sheet, fila, row, config):
    video_id = str(row.get("videoId", "")).strip()
    if not video_id:
        _con_reintentos(sheet.update_cell, fila, 7, "Error")
        return

    print(f"▶️ Procesando fila {fila}: {row.get('titulo', '')} ({video_id})")
    _con_reintentos(sheet.update_cell, fila, 7, "Procesando")

    keys = _get_api_keys()
    # El worker usa los tokens OAuth de YouTube, no las API keys.
    max_intentos = max(1, len([x for x, _ in TOKEN_CONFIG if os.getenv(x, "").strip()]))

    for intento in range(max_intentos):
        try:
            youtube = _youtube()
            rows = sheet.get_all_records()

            if solicitud_activa_existe(
                sheet, video_id, excluir_fila=fila, registros=rows
            ):
                print(f"ℹ️ {video_id} duplicado (fila {fila}); marcado Duplicado")
                _con_reintentos(sheet.update_cell, fila, 7, "Duplicado")
                return

            response = youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": config["playlist"],
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id,
                        },
                    }
                },
            ).execute()

            print("✅ INSERT:", response.get("id"))
            _con_reintentos(sheet.update_cell, fila, 7, "Agregado")
            return

        except Exception as ex:
            error = str(ex)
            print(f"❌ Error credencial YouTube: {error}")

            # Errores definitivos: reintentar no sirve y gasta cuota.
            if "videoAlreadyInPlaylist" in error:
                _con_reintentos(sheet.update_cell, fila, 7, "Agregado")
                return
            if "videoNotFound" in error or "Video not found" in error:
                print(
                    f"🚫 Video no disponible en YouTube ({video_id}): privado, "
                    "eliminado o restringido. Se marca como Error y no se reintenta."
                )
                _con_reintentos(sheet.update_cell, fila, 7, "Error")
                return
            if any(x in error for x in (
                "playlistNotFound", "playlistForbidden",
                "playlistContainsMaximumNumberOfVideos",
            )):
                print(
                    f"🚫 Problema con la playlist del cliente ({config.get('playlist')}): "
                    "no existe, no es de la cuenta del token, o está llena. "
                    "Se marca como Error."
                )
                _con_reintentos(sheet.update_cell, fila, 7, "Error")
                return

            if "quotaExceeded" in error or "dailyLimitExceeded" in error:
                _siguiente_token()
                continue

            if "invalid_grant" in error or "RefreshError" in type(ex).__name__:
                print(
                    "🔑 TOKEN DE YOUTUBE VENCIDO O REVOCADO "
                    f"(credencial #{_token_index + 1}). Hay que generar el token "
                    "de nuevo y actualizar la variable YOUTUBE_TOKEN*_B64 en Railway."
                )
                _siguiente_token()
                continue

            time.sleep(5 if intento < max_intentos - 1 else 2)

    _con_reintentos(sheet.update_cell, fila, 7, "Pendiente")


def _worker():
    print("🚀 PROCESADOR PLAYBAR GO INICIADO")
    while True:
        try:
            # Leer clientes activos desde la hoja CLIENTES.
            rows_clientes = _spreadsheet_obj().worksheet("CLIENTES").get_all_records()
            for c in rows_clientes:
                activo = str(c.get("Activo", c.get("activo", ""))).upper().strip()
                if activo != "TRUE":
                    continue
                nombre = str(c.get("Codigo", c.get("codigo", ""))).strip()
                sheet_name = c.get("Nombre", c.get("nombre", ""))
                playlist = c.get("Playlist", c.get("playlist", ""))
                if not nombre or not sheet_name or not playlist:
                    continue
                config = {"sheet": sheet_name, "playlist": playlist}
                sheet = obtener_hoja_cliente(sheet_name)
                rows = sheet.get_all_records()
                for fila, row in enumerate(rows, start=2):
                    if str(row.get("Estado", "")).strip() != "Pendiente":
                        continue
                    _procesar_fila(sheet, fila, row, config)
                actualizar_estados(sheet)
            print("⏳ Esperando siguiente ciclo...")
        except Exception as ex:
            print("❌ Error general procesador:", ex)
        time.sleep(30)


def diagnostico():
    """Comprueba Sheets, tokens de YouTube y playlists. Se imprime en los logs."""
    print("🩺 DIAGNÓSTICO PLAYBAR GO — inicio")
    try:
        ss = _spreadsheet_obj()
        print(f"🩺 Sheets OK: {ss.title}")
        clientes = ss.worksheet("CLIENTES").get_all_records()
    except Exception as ex:
        print(f"🩺 ❌ Google Sheets falló: {ex}")
        print("🩺    Revisa GOOGLE_CREDENTIALS_B64 y que la hoja esté compartida "
              "con el correo de la cuenta de servicio (client_email).")
        return

    if MODO_PROPIO:
        print("🩺 Modo reproductor propio: no se usan tokens ni playlists de YouTube "
              "(solo la clave de búsqueda).")
        print("🩺 DIAGNÓSTICO PLAYBAR GO — fin")
        return

    disponibles = _tokens_disponibles()
    if not disponibles:
        print("🩺 ❌ No hay ningún token de YouTube (YOUTUBE_TOKEN1_B64 / YOUTUBE_TOKEN2_B64).")
    from google.auth.transport.requests import Request

    yt_ok = None
    for i in disponibles:
        variable, local_file = TOKEN_CONFIG[i]
        try:
            data = _secret_json(variable, local_file)
            creds = Credentials.from_authorized_user_info(data, YOUTUBE_SCOPES)
            creds.refresh(Request())
            print(f"🩺 YouTube token #{i + 1} OK")
            yt_ok = yt_ok or build("youtube", "v3", credentials=creds, cache_discovery=False)
        except Exception as ex:
            print(f"🩺 ❌ YouTube token #{i + 1} NO sirve: {ex}")
            print("🩺    Si dice invalid_grant: el token venció/fue revocado; "
                  "genera uno nuevo y actualiza la variable en Railway.")

    for c in clientes:
        activo = str(c.get("Activo", c.get("activo", ""))).upper().strip()
        nombre = c.get("Nombre", c.get("nombre", ""))
        playlist = str(c.get("Playlist", c.get("playlist", ""))).strip()
        if activo != "TRUE":
            continue
        if not playlist:
            print(f"🩺 ❌ Cliente '{nombre}' activo pero SIN playlist en la hoja CLIENTES")
            continue
        if yt_ok is None:
            continue
        try:
            r = yt_ok.playlists().list(part="snippet", id=playlist).execute()
            if r.get("items"):
                print(f"🩺 Playlist OK para '{nombre}'")
            else:
                print(f"🩺 ❌ Playlist '{playlist}' de '{nombre}' no existe o la cuenta del token no es su dueña")
        except Exception as ex:
            print(f"🩺 ❌ Playlist de '{nombre}': {ex}")
    print("🩺 DIAGNÓSTICO PLAYBAR GO — fin")


def iniciar_procesador():
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True
        if not MODO_PROPIO:
            threading.Thread(
                target=_worker,
                daemon=True,
                name="PlayBarProcessor",
            ).start()
        else:
            print("🎬 Modo reproductor propio: las canciones entran directo a la cola")
        threading.Thread(target=diagnostico, daemon=True, name="PlayBarDiag").start()
        print("🚀 Procesador iniciado en background")
