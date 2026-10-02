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
        data = _secret_json("GOOGLE_CREDENTIALS_B64", "credenciales.json")
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


def _set_cache_sheet(query, data):
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


def solicitud_activa_existe(sheet, video_id, excluir_fila=None, registros=None):
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
            estado = str(row.get("Estado", "")).strip()
            estado2 = str(row.get("Estado2", "")).strip()
            if estado in {"Pendiente", "Procesando"}:
                return True
            if estado == "Agregado" and estado2 in {"En reproduccion", "Siguiente"}:
                return True
    except Exception as ex:
        print("⚠️ No se pudo verificar solicitud activa:", ex)
    return False


def agregar_cancion(cliente, telefono, titulo, canal, video_id):
    config = obtener_config_cliente(cliente)
    if not config:
        return {"ok": False, "error": "CLIENTE_INVALIDO"}

    sheet = obtener_hoja_cliente(config["sheet"])
    try:
        # La comprobación y el append deben ser una única sección crítica.
        # Así dos clics/solicitudes simultáneas no pueden pasar ambas la
        # comprobación de duplicado antes de guardar en Google Sheets.
        with _lock:
            if solicitud_activa_existe(sheet, video_id):
                print(f"⚠️ Canción ya activa para {cliente}: {video_id}")
                return {"ok": True, "duplicado": True}

            sheet.append_row([
                time.strftime("%Y-%m-%d %H:%M:%S"),
                str(cliente),
                str(telefono),
                str(titulo),
                str(canal),
                str(video_id),
                "Pendiente",
            ])

        print("✅ GUARDADO OK")
        return {"ok": True}
    except Exception as ex:
        print("❌ ERROR GUARDANDO EN SHEETS:", ex)
        return {"ok": False, "error": str(ex)}


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
            if row.get("Estado2") == "En reproduccion":
                actual = row.get("titulo", "")
                idx = i
                break
        if idx >= 0:
            for row in rows[idx + 1:]:
                if row.get("Estado") == "Agregado":
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


def _token_credentials():
    global _token_index
    tokens = [x for x, _ in TOKEN_CONFIG if os.getenv(x, "").strip()]
    if not tokens:
        raise RuntimeError("No hay tokens de YouTube configurados")

    variable, local_file = TOKEN_CONFIG[_token_index]
    data = _secret_json(variable, local_file)
    creds = Credentials.from_authorized_user_info(data, YOUTUBE_SCOPES)
    return creds


def _youtube():
    return build("youtube", "v3", credentials=_token_credentials(), cache_discovery=False)


def _siguiente_token():
    global _token_index
    _token_index = (_token_index + 1) % len(TOKEN_CONFIG)
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
                sheet.update_cell(i, 8, "")
        data = sheet.get_all_records()
        pendientes = [
            (i, row) for i, row in enumerate(data, start=2)
            if str(row.get("Estado", "")).strip() == "Agregado"
            and str(row.get("Estado2", "")).strip() != "Reproducido"
        ]
        if pendientes:
            sheet.update_cell(pendientes[0][0], 8, "En reproduccion")
        if len(pendientes) > 1:
            sheet.update_cell(pendientes[1][0], 8, "Siguiente")
    except Exception as ex:
        print("⚠️ No se pudieron actualizar estados:", ex)


def _procesar_fila(sheet, fila, row, config):
    video_id = str(row.get("videoId", "")).strip()
    if not video_id:
        sheet.update_cell(fila, 7, "Error")
        return

    sheet.update_cell(fila, 7, "Procesando")

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
                sheet.update_cell(fila, 7, "Duplicado")
                return

            if video_ya_existe(youtube, config["playlist"], video_id):
                sheet.update_cell(fila, 7, "Agregado")
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
            sheet.update_cell(fila, 7, "Agregado")
            return

        except Exception as ex:
            error = str(ex)
            print(f"❌ Error credencial YouTube: {error}")

            if "quotaExceeded" in error or "dailyLimitExceeded" in error:
                _siguiente_token()
                continue

            try:
                youtube = _youtube()
                if video_ya_existe(youtube, config["playlist"], video_id):
                    sheet.update_cell(fila, 7, "Agregado")
                    return
            except Exception as verify_ex:
                print("⚠️ No se pudo verificar:", verify_ex)

            time.sleep(5 if intento < max_intentos - 1 else 2)

    sheet.update_cell(fila, 7, "Pendiente")


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


def iniciar_procesador():
    global _worker_started
    with _lock:
        if _worker_started:
            return
        _worker_started = True
        threading.Thread(
            target=_worker,
            daemon=True,
            name="PlayBarProcessor",
        ).start()
        print("🚀 Procesador iniciado en background")
