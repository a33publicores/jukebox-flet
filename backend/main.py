import gspread
import time
import webbrowser
import os
import requests
import threading
import time
import threading
from flask import Flask, request, jsonify
from flask import make_response
from flask_cors import CORS
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
import json
import base64
from collections import Counter
from google.oauth2 import service_account
import gspread

CLIENTES = {
    "A33": {
        "sheet": "A33",
        "playlist": "PLE7NJOCoXUqo344KhOxeLSu7KVbsLo0ml"
    },
    "BAR01": {
        "sheet": "BAR01",
        "playlist": "PLE7NJOCoXUqp-JZ7Px2EafYZ56DOxSEYL"
    }
}



def obtener_hoja_cliente(nombre):

    try:

        return spreadsheet.worksheet(
            nombre
        )

    except:

        print(
            "🆕 Creando hoja:",
            nombre
        )

        return spreadsheet.add_worksheet(
            title=nombre,
            rows="1000",
            cols="10"
        )

#def actualizar_estados(sheet):

    data = sheet.get_all_records()

    # Limpiar estados dinámicos
    for i, row in enumerate(data, start=2):

        if row.get("Estado2") in [
            "En reproduccion",
            "Siguiente"
        ]:

            sheet.update_cell(
                i,
                8,
                ""
            )

    # Leer nuevamente
    data = sheet.get_all_records()

    pendientes = []

    for i, row in enumerate(data, start=2):

        estado = str(
            row.get("Estado", "")
        ).strip()

        estado2 = str(
            row.get("Estado2", "")
        ).strip()

        if (
            estado == "Agregado"
            and estado2 != "Reproducido"
        ):

            pendientes.append(
                (i, row)
            )

    if len(pendientes) > 0:

        sheet.update_cell(
            pendientes[0][0],
            8,
            "En reproduccion"
        )

    if len(pendientes) > 1:

        sheet.update_cell(
            pendientes[1][0],
            8,
            "Siguiente"
        )            

def obtener_config_cliente(codigo):

    sheet = spreadsheet.worksheet(
    "CLIENTES"
)
    data = sheet.get_all_records()

    print("📊 CLIENTES:", data)

    for row in data:
        codigo_sheet = str(row.get("Codigo", "")).strip()

        if codigo_sheet == str(codigo).strip():
            return {
                "sheet": row.get ("Nombre"),
                "playlist": row.get("Playlist"),
                "logo": row.get("Logo")
            }

    return None


# =========================
# 🔥 FLASK
# =========================

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

CACHE_TTL = 999999999

# =========================
# 🔐 CREDENCIALES GOOGLE / RAILWAY
# =========================
def cargar_json_secreto(nombre_variable, archivo_local=None):
    valor_b64 = os.getenv(nombre_variable, "").strip()
    if valor_b64:
        try:
            return json.loads(base64.b64decode(valor_b64).decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"No se pudo decodificar {nombre_variable}: {e}") from e
    if archivo_local and os.path.exists(archivo_local):
        with open(archivo_local, "r", encoding="utf-8") as archivo:
            return json.load(archivo)
    raise FileNotFoundError(
        f"No se encontró {nombre_variable} en Railway ni el archivo local "
        f"{archivo_local or ''}. Configura la variable de entorno o el archivo local."
    )

GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
credenciales_google = cargar_json_secreto("GOOGLE_CREDENTIALS_B64", "credenciales.json")
google_credentials = service_account.Credentials.from_service_account_info(
    credenciales_google, scopes=GOOGLE_SCOPES
)
gc = gspread.authorize(google_credentials)

SPREADSHEET_ID = "1F1SMAyyY1iUKRX5QjiyrrMmv7W4z27gBsRMS8ZVGNS0"

spreadsheet = gc.open_by_key(
    SPREADSHEET_ID
)

sheet_cache = spreadsheet.worksheet(
    "CACHE"
)
def normalizar_query(q):
    return q.strip().lower()

def get_cache_sheet(query):
    query = normalizar_query(query)
    rows = sheet_cache.get_all_values()

    ahora = time.time()

    for i in range(1, len(rows)):
        q = rows[i][0]
        data = rows[i][1]
        ts = float(rows[i][2]) if rows[i][2] else 0

        if q == query:
            print("⚡ Usando cache SHEETS (permanente)")
            return json.loads(data)

    return None

def set_cache_sheet(query, data):
    query = normalizar_query(query)
    ts = time.time()

    sheet_cache.append_row([
        query,
        json.dumps(data),
        str(ts)
    ])

    print("💾 Guardado en cache SHEETS")


@app.route("/top", methods=["GET"])
def top():
    return {
        "canciones": cache.get("top_canciones", []),
        "artistas": cache.get("top_artistas", [])
    }

@app.route("/estado_cola")
def estado_cola():

    cliente = request.args.get("cliente")

    try:

        config = obtener_config_cliente(cliente)

        if not config:
            return jsonify({"ok": False})

        sheet = obtener_hoja_cliente(
            config["sheet"]
        )

        data = sheet.get_all_records()

        actual = ""
        siguiente = ""

        indice_actual = -1

        for i, row in enumerate(data):

            if row.get("Estado2") == "En reproduccion":

                actual = row.get(
                    "titulo",
                    ""
                )

                indice_actual = i

                break

        if indice_actual >= 0:

            for row in data[
                indice_actual + 1:
            ]:

                if (
                    row.get("Estado")
                    == "Agregado"
                ):

                    siguiente = row.get(
                        "titulo",
                        ""
                    )

                    break

        return jsonify({
            "ok": True,
            "actual": actual,
            "siguiente": siguiente
        })

    except Exception as e:

        print(
            "❌ ERROR estado_cola:",
            e
        )

        return jsonify({
            "ok": False
        })
    
@app.route("/mis_canciones")
def mis_canciones():

    cliente = request.args.get("cliente")
    telefono = request.args.get("telefono")

    try:

        config = obtener_config_cliente(cliente)

        if not config:
            return jsonify([])

        sheet = obtener_hoja_cliente(
            config["sheet"]
        )

        registros = sheet.get_all_records()

        resultado = []

        for fila in registros:

            usuario = str(
                fila.get("Usuario", "")
            ).strip()

            if usuario != str(telefono):
                continue

            resultado.append({
                "titulo": fila.get("titulo", ""),
                "canal": fila.get("canal", ""),
                "estado": fila.get("Estado", "")
            })

        return jsonify(resultado)

    except Exception as e:

        print(
            "❌ ERROR mis_canciones:",
            str(e)
        )

        return jsonify([])

@app.route("/estado_usuario")
def estado_usuario():

    cliente = request.args.get("cliente")
    telefono = request.args.get("telefono")

    try:

        config = obtener_config_cliente(cliente)

        if not config:
            return jsonify({})

        sheet = obtener_hoja_cliente(
            config["sheet"]
        )

        registros = sheet.get_all_records()

        canciones_usuario = []

        for fila in registros:

            usuario = str(
                fila.get("Usuario", "")
            ).strip()

            if usuario == str(telefono):

                canciones_usuario.append(fila)

        if not canciones_usuario:

            return jsonify({
                "pendientes": 0,
                "ultima_cancion": "",
                "estado": ""
            })

        pendientes = 0

        for fila in canciones_usuario:

            estado = str(
                fila.get("Estado", "")
            ).strip()

            if estado in [
                "Pendiente",
                "Procesando",
                "Agregado"
            ]:
                pendientes += 1

        ultima = canciones_usuario[-1]

        return jsonify({
            "pendientes": pendientes,
            "ultima_cancion": ultima.get(
                "titulo",
                ""
            ),
            "estado": ultima.get(
                "Estado",
                ""
            )
        })

    except Exception as e:

        print(
            "❌ ERROR estado_usuario:",
            str(e)
        )

        return jsonify({})

# 🔥 CACHE GLOBAL
# =========================
# 🔥 GUARDAR CANCIÓN BACKGROUND
# =========================
def guardar_cancion_background(data):
    try:
        cliente = data.get("cliente")
        telefono = data.get("telefono")
        titulo = data.get("titulo")
        canal = data.get("canal")
        videoId = data.get("videoId")

        # 🔥 obtener config dinámica
        config = obtener_config_cliente(cliente)

        if not config:
            print("❌ Cliente no encontrado:", cliente)
            return

        sheet_cliente = obtener_hoja_cliente(config["sheet"])
        

        print("🎵 Guardando en:", config["sheet"])

        # 🔥 estructura correcta
        sheet_cliente.append_row([
            str(time.strftime("%Y-%m-%d %H:%M:%S")),
            str(cliente),
            str(telefono),
            str(titulo),
            str(canal),
            str(videoId),
            "Pendiente"
        ])
        actualizar_estados(sheet_cliente)

        print("✅ Canción guardada correctamente")

    except Exception as e:
        print("❌ Error guardando:", str(e))
        
@app.route("/validar_cliente")
def validar_cliente():

    codigo = request.args.get("codigo")

    try:
        sheet = spreadsheet.worksheet(
    "CLIENTES"
        )
        data = sheet.get_all_records()

        print("🔍 Buscando:", codigo)
        print("📊 DATA:", data)

        for row in data:

            codigo_sheet = str(row.get("Codigo", row.get("codigo", ""))).strip()
            activo = str(row.get("Activo", row.get("activo", ""))).upper()
            nombre = row.get("Nombre", row.get("nombre", ""))

            print("➡️ Comparando con:", codigo_sheet)

            if codigo_sheet == str(codigo).strip() and activo == "TRUE":
                print("✅ ENCONTRADO")

                return jsonify({
                    "ok": True,
                    "nombre": nombre,
                    "logo": row.get("Logo"),
                })

        print("❌ NO ENCONTRADO")
        return jsonify({"ok": False})

    except Exception as e:
        print("❌ ERROR:", str(e))
        return jsonify({"ok": False, "error": str(e)})


cache = {}

last_sheet_read = 0
cached_rows = []


def cargar_historial():
    try:
        with open("historial-de-reproducciones.json", "r", encoding="utf-8") as f:
            data = json.load(f)

        canciones = []
        artistas = []

        for item in data:
            titulo = item.get("title", "")
            titulo = titulo.replace("Has visto ", "").strip()

            subs = item.get("subtitles", [])
            if subs:
                artista = subs[0].get("name", "").replace(" - Topic", "").strip()
            else:
                artista = "Desconocido"

            # 🔥 solo limpiamos basura, NO fechas
            if any(x in titulo.lower() for x in ["mix", "playlist", "radio"]):
                continue

            canciones.append(titulo)
            artistas.append(artista)

        cache["top_canciones"] = Counter(canciones).most_common(50)
        cache["top_artistas"] = Counter(artistas).most_common(20)

        print(f"🔥 Historial completo cargado ({len(canciones)} registros)")

    except Exception as e:
        print("❌ Error cargando historial:", e)



# 🔥 API KEYS
# Railway: YOUTUBE_API_KEYS con claves separadas por comas.
def cargar_api_keys():
    valor = os.getenv("YOUTUBE_API_KEYS", "").strip()
    if not valor:
        print("⚠️ YOUTUBE_API_KEYS no está configurada.")
        return []
    return [clave.strip() for clave in valor.split(",") if clave.strip()]

API_KEYS = cargar_api_keys()
api_index = 0

if not API_KEYS:
    print("⚠️ No hay API Keys de YouTube configuradas. /buscar no podrá consultar YouTube.")

# =========================
# 🔥 ROOT
# =========================
@app.route("/", methods=["GET", "POST", "OPTIONS"])
def home():

    # 🔥 CORS PREFLIGHT (SOLUCION REAL)
    if request.method == "OPTIONS":
        response = make_response()
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    # 🔥 GET TEST
    if request.method == "GET":
        return "Servidor activo"

    # 🔥 POST
    data = request.get_json()

    if not data:
        return make_response("ERROR")

    tipo = data.get("tipo")

    # =========================
    # 🔥 LOGIN
    # =========================
    if tipo == "login":

        telefono = data.get("telefono")

        if telefono:
            print("📱 Login:", telefono)

            response = make_response("OK")
            response.headers["Access-Control-Allow-Origin"] = "*"
            return response

        return make_response("ERROR")

    # =========================
    # 🔥 CANCION
    # =========================
    if tipo == "cancion":

        print("🎵 DATA RECIBIDA:", data)

        cliente = data.get("cliente", "A33")
        telefono = data.get("telefono")
        titulo = data.get("titulo")
        canal = data.get("canal")
        videoId = data.get("videoId")

        if not telefono or not titulo or not videoId:
            print("❌ DATOS INCOMPLETOS")
            return make_response("ERROR_DATOS")

        config = obtener_config_cliente(cliente)

        if not config:
            return make_response("CLIENTE_INVALIDO")

        sheet = obtener_hoja_cliente(
            config["sheet"]
        )

        registros = sheet.get_all_records()

    try:
        # 🔥 DEBUG
        print("🔍 Cliente recibido:", cliente)

        config = obtener_config_cliente(cliente)

        print("🔍 Config:", config)

        if not config:
            print("❌ Cliente no encontrado en Sheets")
            return make_response("CLIENTE_INVALIDO")

        playlist_id = config.get("playlist")
        nombre_hoja = config.get("sheet")

        print("📄 Hoja:", nombre_hoja)
        print("🎧 Playlist:", playlist_id)

        if not playlist_id:
            print("❌ Playlist vacía en Sheets")
            return make_response("ERROR_PLAYLIST")

        sheet = obtener_hoja_cliente(nombre_hoja)

        # 🔥 función background
        def guardar():
            try:
                print("💾 Guardando en hoja...")
            except Exception as e:
                print("❌ ERROR GUARDANDO EN SHEETS:", str(e))

        # Leer filas existentes
        filas = sheet.get_all_records()

        # Evitar que el mismo video se registre dos veces mientras
        # todavía está activo en la cola/reproducción.
        if solicitud_activa_existe(sheet, videoId):
            print(
                f"⚠️ Canción ya activa para {cliente}: {videoId}. "
                "No se registrará otra solicitud."
            )
            return make_response("OK")

        # Guardar nueva canción
        sheet.append_row([
            str(time.strftime("%Y-%m-%d %H:%M:%S")),
            str(cliente),
            str(telefono),
            str(titulo),
            str(canal),
            str(videoId),
            "Pendiente"
        ])

        print("✅ GUARDADO OK")
        return make_response("OK")

    except Exception as e:
        print("❌ ERROR GUARDANDO EN SHEETS:", str(e))

        # 🔥 ejecutar hilo
        threading.Thread(target=guardar).start()

        return make_response("OK")

    except Exception as e:
        print("❌ ERROR GENERAL:", str(e))
        return make_response("ERROR_GENERAL")

# 🔥 DEFAULT (IMPORTANTE QUE ESTÉ DENTRO)
    return make_response("ERROR")
# =========================
# 🔥 BUSCAR YOUTUBE
# =========================
def buscar_youtube(query, pageToken=None):
    global api_index

    for _ in range(len(API_KEYS)):
        key = API_KEYS[api_index]

        print(f"🔑 Usando API key #{api_index}")

        url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={query}&type=video&maxResults=50&key={key}"

        if pageToken:
            url += f"&pageToken={pageToken}"

        res = requests.get(url)
        data = res.json()

        if "error" not in data:
            print("✅ API funcionando")
            return data
        else:
            print("❌ API FALLÓ:", data["error"]["message"])

        api_index = (api_index + 1) % len(API_KEYS)

    print("🚨 TODAS LAS APIS FALLARON")
    return None

# =========================
# 🔥 ENDPOINT BUSCAR
# =========================
@app.route("/buscar")
def buscar():

    query = request.args.get("q", "").lower().strip()
    pageToken = request.args.get("pageToken")

    if len(query) < 3:
        return jsonify({"error": "query corta"})

    cache_key = query.lower().strip()

    # =========================
    # 🔥 1. CACHE EN MEMORIA (RÁPIDO)
    # =========================
    if cache_key in cache:
        data, tiempo = cache[cache_key]

        if time.time() - tiempo < 172800: #48 horas
            print("⚡ cache RAM usado")
            return jsonify(data)
        else:
            del cache[cache_key]

    # =========================
    # 🔥 2. CACHE EN GOOGLE SHEETS (PERSISTENTE)
    # =========================
    try:
        cached_sheet = get_cache_sheet(cache_key)

        if cached_sheet:
            print("📄 cache SHEETS usado")

            # 🔥 guardar también en RAM para acelerar siguientes
            cache[cache_key] = (cached_sheet, time.time())

            return jsonify(cached_sheet)

    except Exception as e:
        print("❌ error leyendo cache sheets:", e)

    # =========================
    # 🔥 3. LLAMAR YOUTUBE
    # =========================
    data = buscar_youtube(query, pageToken)

    # =========================
    # 🔥 4. GUARDAR EN CACHE
    # =========================
    if data:
        # RAM
        cache[cache_key] = (data, time.time())

        # SHEETS
        try:
            set_cache_sheet(cache_key, data)
        except Exception as e:
            print("❌ error guardando en sheets:", e)

    # =========================
    # 🔥 5. FALLBACK
    # =========================
    if not data:
        print("⚠️ Usando cache fallback")

        for key in cache:
            if query in key:
                return jsonify(cache[key][0])

        return jsonify({
            "items": [],
            "nextPageToken": None
        })

    # =========================
    # 🔥 6. RESPUESTA FINAL
    # =========================
    return jsonify({
        "items": data.get("items", []),
        "nextPageToken": data.get("nextPageToken")
    })
# =========================
# CONFIG YOUTUBE
# =========================
#PLAYLIST_ID = "PLE7NJOCoXUqo344KhOxeLSu7KVbsLo0ml"



SCOPES = ["https://www.googleapis.com/auth/youtube"]

# Tokens YouTube: variables *_B64 en Railway; archivos locales fuera de Git.
TOKEN_CONFIG = [
    ("YOUTUBE_TOKEN1_B64", "token1.json"),
    ("YOUTUBE_TOKEN2_B64", "token2.json"),
]
TOKENS = [nombre_variable for nombre_variable, _ in TOKEN_CONFIG]
token_index = 0

def get_youtube():
    global token_index

    nombre_variable, archivo_local = TOKEN_CONFIG[token_index]
    print(f"🔑 Usando credencial YouTube #{token_index + 1}")
    creds = Credentials.from_authorized_user_info(
        cargar_json_secreto(nombre_variable, archivo_local),
        SCOPES
    )
    return build("youtube", "v3", credentials=creds)


def solicitud_activa_existe(sheet, video_id, excluir_fila=None, registros=None):
    """
    Verifica si el mismo video ya tiene una solicitud activa en esta
    hoja/establecimiento. Se consideran activas:
      - Estado = Pendiente
      - Estado = Procesando
      - Estado = Agregado y Estado2 = En reproduccion/Siguiente
    """
    video_id = str(video_id or "").strip()

    if not video_id:
        return False

    try:
        if registros is None:
            registros = sheet.get_all_records()

        for indice, row in enumerate(registros, start=2):
            if excluir_fila is not None and indice == excluir_fila:
                continue

            existente = str(row.get("videoId", "")).strip()
            estado = str(row.get("Estado", "")).strip()
            estado2 = str(row.get("Estado2", "")).strip()

            if existente != video_id:
                continue

            if estado in {"Pendiente", "Procesando"}:
                return True

            if (
                estado == "Agregado"
                and estado2 in {"En reproduccion", "Siguiente"}
            ):
                return True

    except Exception as ex:
        print("⚠️ No se pudo verificar solicitud activa:", ex)

    return False


def video_ya_existe(youtube, playlist_id, video_id):

    page_token = None

    while True:

        respuesta = youtube.playlistItems().list(
            part="snippet",
            playlistId=playlist_id,
            maxResults=50,
            pageToken=page_token
        ).execute()

        for item in respuesta.get("items", []):

            actual = item["snippet"]["resourceId"]["videoId"]

            if actual == video_id:
                return True

        page_token = respuesta.get("nextPageToken")

        if not page_token:
            break

    return False


def siguiente_token():
    global token_index

    # Avanzar al siguiente token de la lista
    token_index = (token_index + 1) % len(TOKENS)

    # Mostrar el archivo real que se usará
    print(f"🔄 Cambiando a credencial YouTube #{token_index + 1}")


# ⚠️ NO USAR EDGE EN SERVIDOR
if os.environ.get("RAILWAY_ENVIRONMENT") is None:
    edge_path = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
    webbrowser.register('edge', None, webbrowser.BackgroundBrowser(edge_path))
    os.environ["BROWSER"] = "edge"

# =========================
# 🔥 AUTENTICACIÓN YOUTUBE
# =========================


# =========================
# 🔥 GOOGLE SHEETS
# =========================


cargar_historial()

print("✅ Sistema iniciado correctamente")

# =========================
# 🔥 LOOP PRINCIPAL
# =========================
# =========================
# LOOP PRINCIPAL
# =========================

def loop_principal():

    print("🚀 LOOP INICIADO")

    while True:

        try:

            print("📥 Procesando clientes...")

            for nombre_cliente, config in CLIENTES.items():

                print(f"🏪 Cliente: {nombre_cliente}")

                sheet = obtener_hoja_cliente(
                    config["sheet"]
                )

                rows = sheet.get_all_records()

                for fila, row in enumerate(
                    rows,
                    start=2
                ):

                    estado = str(
                        row.get(
                            "Estado",
                            ""
                        )
                    ).strip()

                    if estado != "Pendiente":
                        continue

                    video_id = str(
                        row.get(
                            "videoId",
                            ""
                        )
                    ).strip()

                    if not video_id:

                        print(
                            f"⚠️ Fila {fila} sin videoId"
                        )

                        sheet.update_cell(
                            fila,
                            7,
                            "Error"
                        )

                        continue

                    print(
                        f"🎵 Procesando fila {fila} - {video_id}"
                    )

                    # Marcar inmediatamente
                    sheet.update_cell(
                        fila,
                        7,
                        "Procesando"
                    )

                    agregado = False
                    intentos = 0

                    while (
                        intentos < len(TOKENS)
                        and not agregado
                    ):

                        try:

                            youtube = get_youtube()

                            # 1) Doble protección en Google Sheets:
                            # si otra fila ya tiene la misma canción activa,
                            # no se procesa nuevamente.
                            if solicitud_activa_existe(
                                sheet,
                                video_id,
                                excluir_fila=fila,
                                registros=rows
                            ):
                                print(
                                    f"⚠️ Duplicado activo detectado: {video_id}. "
                                    "No se insertará nuevamente."
                                )
                                sheet.update_cell(
                                    fila,
                                    7,
                                    "Duplicado"
                                )
                                agregado = True
                                break

                            # 2) Protección contra duplicados reales en YouTube.
                            # Se verifica justo antes del INSERT para evitar
                            # que dos solicitudes terminen en la playlist.
                            if video_ya_existe(
                                youtube,
                                config["playlist"],
                                video_id
                            ):
                                print(
                                    f"⚠️ El video ya existe en YouTube: {video_id}. "
                                    "No se insertará nuevamente."
                                )
                                sheet.update_cell(
                                    fila,
                                    7,
                                    "Agregado"
                                )
                                agregado = True
                                break

                            response = youtube.playlistItems().insert(
                                part="snippet",
                                body={
                                    "snippet": {
                                        "playlistId": config["playlist"],
                                        "resourceId": {
                                            "kind": "youtube#video",
                                            "videoId": video_id
                                        }
                                    }
                                }
                            ).execute()

                            print(
                                "✅ INSERT:",
                                response["id"]
                            )

                            sheet.update_cell(
                                fila,
                                7,
                                "Agregado"
                            )

                            agregado = True

                        except Exception as ex:

                            error = str(ex)

                            print(
                                f"❌ Error credencial YouTube #{token_index + 1}: {error}"
                            )

                            # Solo cambiar token cuando realmente se agotó la cuota
                            if "quotaExceeded" in error or "dailyLimitExceeded" in error:

                                print("🔄 Cambiando de token por cuota")
                                siguiente_token()

                            # Error temporal de YouTube
                            elif (
                                "SERVICE_UNAVAILABLE" in error
                                or "backendError" in error
                                or "Internal error" in error
                            ):

                                print("⏳ Verificando si YouTube alcanzó a insertar...")

                                try:

                                    youtube = get_youtube()

                                    if video_ya_existe(
                                        youtube,
                                        config["playlist"],
                                        video_id
                                    ):

                                        print("✅ El video YA estaba en la playlist")

                                        sheet.update_cell(
                                            fila,
                                            7,
                                            "Agregado"
                                        )

                                        agregado = True

                                        break

                                except Exception as ex2:

                                    print("⚠️ No se pudo verificar:", ex2)

                                print("🔁 Reintentando...")

                                time.sleep(5)

                            else:

                                # Última verificación de seguridad: algunos
                                # errores de red pueden ocurrir después de que
                                # YouTube haya aceptado el INSERT.
                                try:

                                    youtube = get_youtube()

                                    if video_ya_existe(
                                        youtube,
                                        config["playlist"],
                                        video_id
                                    ):
                                        print(
                                            "✅ Verificación posterior: "
                                            "el video ya estaba en la playlist"
                                        )

                                        sheet.update_cell(
                                            fila,
                                            7,
                                            "Agregado"
                                        )

                                        agregado = True
                                        break

                                except Exception as ex2:

                                    print(
                                        "⚠️ No se pudo verificar el INSERT:",
                                        ex2
                                    )

                                print("⚠️ Otro error:", error)

                                time.sleep(2)

                            intentos += 1

                    if not agregado:

                        sheet.update_cell(
                            fila,
                            7,
                            "Pendiente"
                        )

            print("⏳ Esperando siguiente ciclo...")
            time.sleep(30)

        except Exception as ex:

            print(
                "❌ Error general:",
                str(ex)
            )

            time.sleep(30)

# =========================
# 🔥 INICIAR LOOP DE PROCESAMIENTO
# =========================
def iniciar_loop_principal():
    # Gunicorn importa este módulo en el worker y, por tanto, `__name__`
    # NO es "__main__". El loop debe iniciarse también en Railway.
    if getattr(app, "_loop_principal_iniciado", False):
        return

    app._loop_principal_iniciado = True
    threading.Thread(target=loop_principal, daemon=True, name="PlayBarLoop").start()
    print("🚀 LOOP PRINCIPAL INICIADO EN BACKGROUND")


# Iniciar el procesador tanto en Railway/Gunicorn como en ejecución local.
# Railway está configurado con 1 worker para evitar múltiples loops simultáneos.
iniciar_loop_principal()

# =========================
# 🔥 INICIAR SERVIDOR LOCAL
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
