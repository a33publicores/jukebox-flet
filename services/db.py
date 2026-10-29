"""
Base de datos PostgreSQL de PlayBar GO (Railway). Reemplaza a Google Sheets.

Tablas:
    clientes   un negocio por fila: código, nombre, logo, playlist, activo, llave del reproductor
    admins     usuarios del panel: por negocio (codigo) o super administrador (rol = super)
    pedidos    canciones pedidas (lo que antes eran las pestañas A33, BAR01...)
    control    comandos del admin al reproductor y estado del reproductor (uno por negocio)
    busquedas  caché de búsquedas de YouTube (sin el límite de 50.000 caracteres de Sheets)
    descargas  enlaces temporales para descargar Excel desde el panel

Las fechas se guardan como epoch (segundos); se muestran en hora de Colombia.
La conexión usa la variable DATABASE_URL (Railway la crea al agregar PostgreSQL).
"""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

ESTADOS_ACTIVOS = ("En cola", "En reproduccion", "Siguiente")
VENTANA_DUPLICADO_HORAS = float(os.getenv("DUPLICADO_HORAS", "12"))

_pool = None
_lock_pool = threading.Lock()     # crear la conexión
_lock_esquema = threading.Lock()  # crear las tablas (son candados DISTINTOS: con uno
_listo = False                    # solo, crear tablas esperaba a la conexión para siempre)

ESQUEMA = [
    """CREATE TABLE IF NOT EXISTS clientes (
        codigo   TEXT PRIMARY KEY,
        nombre   TEXT NOT NULL,
        logo     TEXT NOT NULL DEFAULT '',
        playlist TEXT NOT NULL DEFAULT '',
        activo   BOOLEAN NOT NULL DEFAULT TRUE,
        llave    TEXT UNIQUE,
        creado   DOUBLE PRECISION NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS admins (
        id      SERIAL PRIMARY KEY,
        codigo  TEXT NOT NULL,
        usuario TEXT NOT NULL,
        clave   TEXT NOT NULL,
        rol     TEXT NOT NULL DEFAULT 'admin',
        activo  BOOLEAN NOT NULL DEFAULT TRUE,
        nota    TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS pedidos (
        id       SERIAL PRIMARY KEY,
        codigo   TEXT NOT NULL,
        ts       DOUBLE PRECISION NOT NULL,
        usuario  TEXT NOT NULL DEFAULT '',
        titulo   TEXT NOT NULL DEFAULT '',
        canal    TEXT NOT NULL DEFAULT '',
        video_id TEXT NOT NULL,
        estado   TEXT NOT NULL DEFAULT 'Agregado',
        estado2  TEXT NOT NULL DEFAULT '',
        orden    DOUBLE PRECISION
    )""",
    "CREATE INDEX IF NOT EXISTS pedidos_codigo_ts ON pedidos (codigo, ts)",
    """CREATE TABLE IF NOT EXISTS control (
        codigo     TEXT PRIMARY KEY,
        comando    TEXT NOT NULL DEFAULT '',
        comando_id TEXT NOT NULL DEFAULT '',
        param      TEXT NOT NULL DEFAULT '',
        estado     TEXT NOT NULL DEFAULT '',
        actual     TEXT NOT NULL DEFAULT '',
        siguiente  TEXT NOT NULL DEFAULT '',
        latido     DOUBLE PRECISION NOT NULL DEFAULT 0,
        ack        TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS busquedas (
        consulta TEXT PRIMARY KEY,
        datos    TEXT NOT NULL,
        ts       DOUBLE PRECISION NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS sesiones (
        token  TEXT PRIMARY KEY,
        rol    TEXT NOT NULL DEFAULT 'usuario',
        datos  TEXT NOT NULL,
        creado DOUBLE PRECISION NOT NULL,
        expira DOUBLE PRECISION NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS descargas (
        token  TEXT PRIMARY KEY,
        codigo TEXT NOT NULL,
        expira DOUBLE PRECISION NOT NULL
    )""",
    # --- Suscripción (prueba gratis + planes pagos con Wompi) ---------------------
    # Los negocios que ya existían quedan en "cortesia" (sin cobro); los nuevos empiezan
    # en "prueba" con 30 canciones. El super admin cambia todo desde /super.
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS plan_estado TEXT",
    "UPDATE clientes SET plan_estado = 'cortesia' WHERE plan_estado IS NULL",
    "ALTER TABLE clientes ALTER COLUMN plan_estado SET DEFAULT 'prueba'",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS prueba_limite INTEGER NOT NULL DEFAULT 30",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS prueba_desde DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS plan_vence DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS plan_nombre TEXT NOT NULL DEFAULT ''",
    """CREATE TABLE IF NOT EXISTS planes (
        id        SERIAL PRIMARY KEY,
        nombre    TEXT NOT NULL,
        precio    INTEGER NOT NULL,
        dias      INTEGER NOT NULL DEFAULT 30,
        activo    BOOLEAN NOT NULL DEFAULT TRUE,
        solo_para TEXT NOT NULL DEFAULT '',
        orden     INTEGER NOT NULL DEFAULT 0,
        clave     TEXT UNIQUE
    )""",
    """CREATE TABLE IF NOT EXISTS pagos (
        referencia     TEXT PRIMARY KEY,
        codigo         TEXT NOT NULL,
        plan_id        INTEGER,
        plan_nombre    TEXT NOT NULL DEFAULT '',
        monto          INTEGER NOT NULL,
        dias           INTEGER NOT NULL DEFAULT 30,
        moneda         TEXT NOT NULL DEFAULT 'COP',
        estado         TEXT NOT NULL DEFAULT 'PENDIENTE',
        id_transaccion TEXT NOT NULL DEFAULT '',
        creado         DOUBLE PRECISION NOT NULL,
        pagado         DOUBLE PRECISION NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS pagos_codigo ON pagos (codigo, creado)",
    # Géneros del relleno que escoge el admin del bar ('' = todos). Ver services/generos.py
    "ALTER TABLE control ADD COLUMN IF NOT EXISTS generos TEXT NOT NULL DEFAULT ''",
    # Logo del negocio subido desde /super (PNG/JPG guardado en la base, no se pierde
    # cuando Railway reinicia). clientes.logo queda como "db:<versión>".
    """CREATE TABLE IF NOT EXISTS logos (
        codigo     TEXT PRIMARY KEY,
        datos      TEXT NOT NULL,
        tipo       TEXT NOT NULL DEFAULT 'image/png',
        actualizado DOUBLE PRECISION NOT NULL
    )""",
    # Bonos de referido (services/bonos.py): un descuento en UN pago. Mientras un pago
    # está en curso el bono queda "reservado" a esa orden; al aprobarse queda "usado".
    """CREATE TABLE IF NOT EXISTS bonos (
        codigo          TEXT PRIMARY KEY,
        nota            TEXT NOT NULL DEFAULT '',
        descuento       INTEGER NOT NULL,
        activo          BOOLEAN NOT NULL DEFAULT TRUE,
        creado          DOUBLE PRECISION NOT NULL,
        reservado_ref   TEXT NOT NULL DEFAULT '',
        reservado_hasta DOUBLE PRECISION NOT NULL DEFAULT 0,
        usado_ref       TEXT NOT NULL DEFAULT '',
        usado_bar       TEXT NOT NULL DEFAULT '',
        usado_en        DOUBLE PRECISION NOT NULL DEFAULT 0
    )""",
    # Un solo reproductor activo por bar (como Spotify): cuál equipo tiene el control.
    "ALTER TABLE control ADD COLUMN IF NOT EXISTS instancia TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE control ADD COLUMN IF NOT EXISTS instancia_nombre TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE control ADD COLUMN IF NOT EXISTS instancia_visto DOUBLE PRECISION NOT NULL DEFAULT 0",
    # Ficha del equipo donde suena el bar (modelo, sistema, RAM, espacio, pantalla) en JSON.
    "ALTER TABLE control ADD COLUMN IF NOT EXISTS equipo_info TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS bono TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE pagos ADD COLUMN IF NOT EXISTS descuento INTEGER NOT NULL DEFAULT 0",
    # Cuántos televisores/equipos pueden tener abierto el reproductor del bar al mismo tiempo
    # (lo pone el super administrador). Con más, al siguiente le sale "Usar aquí".
    "ALTER TABLE clientes ADD COLUMN IF NOT EXISTS televisores INTEGER NOT NULL DEFAULT 1",
    # Promoción de un plan: los primeros `promo_pagos` pagos de cada bar cuestan `promo_precio`
    # (0 = sin promoción). Ej.: 2 meses a $19.900 y luego el precio normal.
    "ALTER TABLE planes ADD COLUMN IF NOT EXISTS promo_precio INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE planes ADD COLUMN IF NOT EXISTS promo_pagos INTEGER NOT NULL DEFAULT 0",
    # Los demás televisores del bar ("espejos"): siguen la canción del principal.
    """CREATE TABLE IF NOT EXISTS reproductores (
        codigo    TEXT NOT NULL,
        instancia TEXT NOT NULL,
        equipo    TEXT NOT NULL DEFAULT '',
        desde     DOUBLE PRECISION NOT NULL,
        visto     DOUBLE PRECISION NOT NULL,
        info      TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (codigo, instancia)
    )""",
    # Qué suena en el principal (para que los espejos lo sigan): video, siguiente y posición.
    "ALTER TABLE control ADD COLUMN IF NOT EXISTS actual_video TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE control ADD COLUMN IF NOT EXISTS actual_canal TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE control ADD COLUMN IF NOT EXISTS siguiente_video TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE control ADD COLUMN IF NOT EXISTS actual_pos DOUBLE PRECISION NOT NULL DEFAULT 0",
    "ALTER TABLE control ADD COLUMN IF NOT EXISTS actual_ts DOUBLE PRECISION NOT NULL DEFAULT 0",
    # Canciones que el reproductor del navegador necesita en la nube: un TV o PC con la app
    # (que sí puede bajar de YouTube) la baja y la sube. Ver encargar() / tomar_encargo().
    """CREATE TABLE IF NOT EXISTS encargos (
        video_id   TEXT PRIMARY KEY,
        titulo     TEXT NOT NULL DEFAULT '',
        canal      TEXT NOT NULL DEFAULT '',
        codigo     TEXT NOT NULL DEFAULT '',
        estado     TEXT NOT NULL DEFAULT 'pendiente',
        creado     DOUBLE PRECISION NOT NULL,
        tomado     DOUBLE PRECISION NOT NULL DEFAULT 0,
        tomado_por TEXT NOT NULL DEFAULT '',
        intentos   INTEGER NOT NULL DEFAULT 0,
        error      TEXT NOT NULL DEFAULT '',
        prioridad  INTEGER NOT NULL DEFAULT 0
    )""",
    # Temas por temporada (Navidad, Halloween...): ver services/temas.py
    """CREATE TABLE IF NOT EXISTS temas (
        clave       TEXT PRIMARY KEY,
        nombre      TEXT NOT NULL,
        datos       TEXT NOT NULL DEFAULT '{}',
        orden       INTEGER NOT NULL DEFAULT 0,
        actualizado DOUBLE PRECISION NOT NULL DEFAULT 0
    )""",
    # Volumen parejo: qué tan duro suena cada canción (LUFS). Ver services/volumen.py
    """CREATE TABLE IF NOT EXISTS volumenes (
        video_id TEXT PRIMARY KEY,
        lufs     DOUBLE PRECISION,
        medido   DOUBLE PRECISION NOT NULL DEFAULT 0
    )""",
    # Catálogo de canciones por género (ej. diciembre): ver services/catalogo/*.json
    """CREATE TABLE IF NOT EXISTS catalogo (
        video_id TEXT PRIMARY KEY,
        titulo   TEXT NOT NULL DEFAULT '',
        canal    TEXT NOT NULL DEFAULT '',
        genero   TEXT NOT NULL DEFAULT '',
        duracion INTEGER NOT NULL DEFAULT 0
    )""",
    # Canciones eliminadas por el super administrador: dejan de sonar de relleno (y salen de
    # los géneros) y la API borra su archivo de la nube. Los clientes sí la pueden pedir: si
    # alguien la pide, vuelve (se borra de aquí).
    """CREATE TABLE IF NOT EXISTS eliminadas (
        video_id     TEXT PRIMARY KEY,
        titulo       TEXT NOT NULL DEFAULT '',
        canal        TEXT NOT NULL DEFAULT '',
        cuando       DOUBLE PRECISION NOT NULL,
        borrada_nube BOOLEAN NOT NULL DEFAULT FALSE
    )""",
    # Lo que de verdad hay en la nube (Cloudflare R2): la API lo copia cada rato.
    """CREATE TABLE IF NOT EXISTS nube_archivos (
        archivo  TEXT PRIMARY KEY,
        video_id TEXT NOT NULL,
        bytes    BIGINT NOT NULL DEFAULT 0,
        subido   DOUBLE PRECISION NOT NULL DEFAULT 0
    )""",
    # Ajustes generales del sistema (clave -> valor). Ej.: tema_modo.
    """CREATE TABLE IF NOT EXISTS ajustes (
        clave TEXT PRIMARY KEY,
        valor TEXT NOT NULL DEFAULT ''
    )""",
]


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------
def disponible():
    return bool(os.getenv("DATABASE_URL", "").strip())


def _pool_obj():
    global _pool
    with _lock_pool:
        if _pool is None:
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool

            _pool = ConnectionPool(
                os.environ["DATABASE_URL"],
                min_size=1,
                max_size=int(os.getenv("DB_POOL_MAX", "8")),
                kwargs={"autocommit": True, "row_factory": dict_row, "connect_timeout": 10},
                timeout=15,
                open=True,
            )
        return _pool


def diagnostico():
    """Prueba una conexión directa (sin pool) y devuelve el error REAL si falla.
    Nunca devuelve la contraseña."""
    from urllib.parse import urlparse
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return {"conexion": "Falta la variable DATABASE_URL en este servicio"}
    u = urlparse(url)
    info = {"host": u.hostname, "puerto": u.port, "base": (u.path or "").lstrip("/"),
            "usuario": u.username}
    try:
        import psycopg
        with psycopg.connect(url, connect_timeout=8) as c:
            c.execute("SELECT 1")
        info["conexion"] = "ok"
    except Exception as ex:
        texto = str(ex)
        if u.password:
            texto = texto.replace(u.password, "***")
        info["conexion"] = f"{type(ex).__name__}: {texto}"
    return info


def _consultar_pg(sql, params):
    with _pool_obj().connection() as conn:
        cur = conn.execute(sql, params)
        return list(cur.fetchall()) if cur.description else []


def _ejecutar_pg(sql, params):
    with _pool_obj().connection() as conn:
        return conn.execute(sql, params).rowcount


# Las pruebas reemplazan estas dos funciones por otra conexión.
motor = {"consultar": _consultar_pg, "ejecutar": _ejecutar_pg}


def asegurar():
    """Crea las tablas la primera vez (es seguro llamarlo siempre)."""
    global _listo
    if _listo:
        return
    with _lock_esquema:
        if _listo:
            return
        for sql in ESQUEMA:
            motor["ejecutar"](sql, ())
        _listo = True
        print("✅ Base de datos lista")
    try:  # planes de suscripción y bar de ejemplo (solo si faltan)
        from services import suscripcion
        suscripcion.sembrar()
    except Exception as ex:
        print("⚠️ No se pudieron crear los planes:", ex)
    try:  # catálogo de canciones por género (diciembre...)
        sembrar_catalogo()
    except Exception as ex:
        print("⚠️ No se pudo cargar el catálogo:", ex)
    try:  # plantillas de ejemplo de los temas (Navidad, Halloween)
        from services import temas
        temas.sembrar()
    except Exception as ex:
        print("⚠️ No se pudieron crear los temas de ejemplo:", ex)


def consultar(sql, params=()):
    asegurar()
    return motor["consultar"](sql, tuple(params))


def uno(sql, params=()):
    filas = consultar(sql, params)
    return filas[0] if filas else None


def ejecutar(sql, params=()):
    asegurar()
    return motor["ejecutar"](sql, tuple(params))


# ---------------------------------------------------------------------------
# Claves (se guardan cifradas, nunca en texto)
# ---------------------------------------------------------------------------
def cifrar_clave(clave):
    sal = secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", str(clave).encode(), sal.encode(), 120_000).hex()
    return f"pbkdf2${sal}${h}"


def clave_correcta(clave, guardada):
    guardada = str(guardada or "")
    if guardada.startswith("pbkdf2$"):
        _, sal, h = guardada.split("$", 2)
        calc = hashlib.pbkdf2_hmac("sha256", str(clave).encode(), sal.encode(), 120_000).hex()
        return hmac.compare_digest(calc, h)
    return bool(guardada) and hmac.compare_digest(str(clave).encode(), guardada.encode())


# Llave del reproductor: 8 caracteres fáciles de escribir con el control del TV, mostrados
# como K7M4-X9P2. Sin 0/O ni 1/I/L para que no se confundan. ~850.000 millones de
# combinaciones. Las llaves viejas "pbg_..." (largas) siguen sirviendo tal cual.
_ALFABETO_LLAVE = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
LARGO_LLAVE = 8


def normalizar_llave(llave):
    """Como la escriban (minúsculas, con espacios o guion), queda como se guarda."""
    s = str(llave or "").strip()
    if s.lower().startswith("pbg_"):
        return s  # llave vieja: se compara exacta
    return "".join(c for c in s.upper() if c.isalnum())


def formato_llave(llave):
    """Para mostrarla: K7M4X9P2 -> K7M4-X9P2 (las viejas se muestran igual)."""
    s = str(llave or "")
    if len(s) == LARGO_LLAVE and not s.lower().startswith("pbg_"):
        return f"{s[:4]}-{s[4:]}"
    return s


def nueva_llave():
    for _ in range(50):
        llave = "".join(secrets.choice(_ALFABETO_LLAVE) for _ in range(LARGO_LLAVE))
        if not uno("SELECT 1 AS x FROM clientes WHERE llave = %s", (llave,)):
            return llave
    raise RuntimeError("No se pudo generar una llave única")


# ---------------------------------------------------------------------------
# Clientes (negocios)
# ---------------------------------------------------------------------------
def cliente(codigo):
    return uno("SELECT * FROM clientes WHERE codigo = %s", (str(codigo).strip(),))


def clientes():
    return consultar("SELECT * FROM clientes ORDER BY nombre")


def cliente_por_llave(llave):
    if not llave:
        return None
    return uno("SELECT * FROM clientes WHERE llave = %s AND activo", (normalizar_llave(llave),))


def guardar_cliente(codigo, nombre, logo="", playlist="", activo=True):
    """Crea o actualiza un negocio. Si es nuevo, le genera su llave."""
    codigo = str(codigo).strip()
    return uno(
        """INSERT INTO clientes (codigo, nombre, logo, playlist, activo, llave, creado,
                                 plan_estado, prueba_desde)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'prueba', %s)
           ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre,
               logo = EXCLUDED.logo, playlist = EXCLUDED.playlist, activo = EXCLUDED.activo
           RETURNING *""",
        (codigo, str(nombre).strip(), str(logo or "").strip(), str(playlist or "").strip(),
         bool(activo), nueva_llave(), time.time(), time.time()),
    )


MAX_TELEVISORES = 20


def poner_televisores(codigo, cantidad):
    """Cuántos equipos pueden tener abierto el reproductor del bar a la vez (1 a 20)."""
    n = max(1, min(MAX_TELEVISORES, int(cantidad or 1)))
    ejecutar("UPDATE clientes SET televisores = %s WHERE codigo = %s", (n, str(codigo).strip()))
    return n


def eliminar_negocio(codigo):
    """Borra de verdad TODO lo del negocio, en una sola operación (todo o nada): el bar
    (y con él su llave del reproductor), sus administradores, canciones e historial,
    control y géneros, logo, pagos, descargas y sesiones abiertas. Los bonos que usó se
    conservan marcados como usados (con el código del bar como texto). No se deshace.
    Devuelve cuántas filas se borraron de cada tabla, o None si el negocio no existe."""
    codigo = str(codigo).strip()
    if not codigo or codigo == "*":
        raise ValueError("Código de negocio no válido")
    fila = uno(
        """WITH reservas AS (UPDATE bonos SET reservado_ref = '', reservado_hasta = 0
                             WHERE usado_ref = '' AND reservado_ref IN
                                   (SELECT referencia FROM pagos WHERE codigo = %s) RETURNING 1),
                admins_   AS (DELETE FROM admins    WHERE codigo = %s RETURNING 1),
                pedidos_  AS (DELETE FROM pedidos   WHERE codigo = %s RETURNING 1),
                control_  AS (DELETE FROM control   WHERE codigo = %s RETURNING 1),
                espejos_  AS (DELETE FROM reproductores WHERE codigo = %s RETURNING 1),
                logos_    AS (DELETE FROM logos     WHERE codigo = %s RETURNING 1),
                pagos_    AS (DELETE FROM pagos     WHERE codigo = %s RETURNING 1),
                descargas_ AS (DELETE FROM descargas WHERE codigo = %s RETURNING 1),
                sesiones_ AS (DELETE FROM sesiones  WHERE datos LIKE %s RETURNING 1),
                negocio   AS (DELETE FROM clientes  WHERE codigo = %s RETURNING 1)
           SELECT (SELECT COUNT(*) FROM negocio) AS negocio,
                  (SELECT COUNT(*) FROM admins_) AS admins,
                  (SELECT COUNT(*) FROM pedidos_) AS pedidos,
                  (SELECT COUNT(*) FROM control_) AS control,
                  (SELECT COUNT(*) FROM logos_) AS logos,
                  (SELECT COUNT(*) FROM pagos_) AS pagos,
                  (SELECT COUNT(*) FROM descargas_) AS descargas,
                  (SELECT COUNT(*) FROM sesiones_) AS sesiones,
                  (SELECT COUNT(*) FROM reservas) AS bonos_liberados""",
        (codigo, codigo, codigo, codigo, codigo, codigo, codigo, codigo,
         "%" + json.dumps({"codigo": codigo})[1:-1] + "%", codigo))
    if not fila or not fila["negocio"]:
        return None
    try:
        from services.playbar_service import olvidar_cliente
        olvidar_cliente(codigo)
    except Exception:
        pass
    print(f"🗑️ Negocio {codigo} eliminado: {dict(fila)}")
    return dict(fila)


def guardar_logo(codigo, contenido, tipo="image/png"):
    """Guarda la imagen del logo y deja el negocio apuntando a ella."""
    import base64
    ahora = time.time()
    ejecutar(
        """INSERT INTO logos (codigo, datos, tipo, actualizado) VALUES (%s, %s, %s, %s)
           ON CONFLICT (codigo) DO UPDATE SET datos = EXCLUDED.datos, tipo = EXCLUDED.tipo,
               actualizado = EXCLUDED.actualizado""",
        (str(codigo), base64.b64encode(contenido).decode(), tipo, ahora))
    ejecutar("UPDATE clientes SET logo = %s WHERE codigo = %s", (f"db:{int(ahora)}", str(codigo)))


def logo_bytes(codigo):
    import base64
    f = uno("SELECT datos FROM logos WHERE codigo = %s", (str(codigo),))
    return base64.b64decode(f["datos"]) if f else None


def quitar_logo(codigo):
    ejecutar("DELETE FROM logos WHERE codigo = %s", (str(codigo),))
    ejecutar("UPDATE clientes SET logo = '' WHERE codigo = %s", (str(codigo),))


def regenerar_llave(codigo):
    return uno("UPDATE clientes SET llave = %s WHERE codigo = %s RETURNING *",
               (nueva_llave(), str(codigo)))


# ---------------------------------------------------------------------------
# Administradores
# ---------------------------------------------------------------------------
def admins(codigo=None):
    if codigo is None:
        return consultar("SELECT id, codigo, usuario, rol, activo, nota FROM admins "
                         "ORDER BY codigo, usuario")
    return consultar("SELECT id, codigo, usuario, rol, activo, nota FROM admins "
                     "WHERE codigo = %s ORDER BY usuario", (str(codigo),))


def agregar_admin(codigo, usuario, clave, rol="admin", nota=""):
    return uno(
        """INSERT INTO admins (codigo, usuario, clave, rol, nota) VALUES (%s, %s, %s, %s, %s)
           RETURNING id, codigo, usuario, rol, activo, nota""",
        (str(codigo).strip(), str(usuario).strip(), cifrar_clave(clave), rol, str(nota or "")),
    )


def cambiar_admin(id_admin, activo=None, clave=None, nota=None):
    if activo is not None:
        ejecutar("UPDATE admins SET activo = %s WHERE id = %s", (bool(activo), int(id_admin)))
    if clave:
        ejecutar("UPDATE admins SET clave = %s WHERE id = %s", (cifrar_clave(clave), int(id_admin)))
    if nota is not None:
        ejecutar("UPDATE admins SET nota = %s WHERE id = %s", (str(nota), int(id_admin)))


def borrar_admin(id_admin):
    ejecutar("DELETE FROM admins WHERE id = %s", (int(id_admin),))


def validar_admin(codigo, usuario, clave):
    """(ok, hay_admins). El usuario no distingue mayúsculas; la clave sí.
    Los admins con código * y los super administradores entran a cualquier negocio."""
    filas = consultar(
        "SELECT usuario, clave, rol FROM admins WHERE activo "
        "AND (codigo = %s OR codigo = '*' OR rol = 'super')",
        (str(codigo).strip(),),
    )
    u = str(usuario or "").strip().lower()
    for f in filas:
        if f["usuario"].strip().lower() == u and clave_correcta(str(clave or "").strip(), f["clave"]):
            return True, True
    return False, bool(filas)


def validar_super(usuario, clave):
    """Super admin: filas con rol = super, o las variables SUPERADMIN_USER / SUPERADMIN_PASS."""
    u = str(usuario or "").strip().lower()
    c = str(clave or "").strip()
    env_u = os.getenv("SUPERADMIN_USER", "").strip().lower()
    env_c = os.getenv("SUPERADMIN_PASS", "").strip()
    if env_u and env_c and hmac.compare_digest(u.encode(), env_u.encode()) \
            and hmac.compare_digest(c.encode(), env_c.encode()):
        return True
    if not u:
        return False
    for f in consultar("SELECT usuario, clave FROM admins WHERE activo AND rol = 'super' "
                       "AND LOWER(TRIM(usuario)) = %s", (u,)):
        if clave_correcta(c, f["clave"]):
            return True
    return False


# ---------------------------------------------------------------------------
# Pedidos (canciones)
# ---------------------------------------------------------------------------
def importar_pedidos(filas):
    """Carga masiva (migración): filas = [(codigo, ts, usuario, titulo, canal, video_id,
    estado, estado2, orden)]. Inserta de a 200 por consulta."""
    total = 0
    for i in range(0, len(filas), 200):
        lote = filas[i:i + 200]
        marcas = ", ".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(lote))
        ejecutar(
            "INSERT INTO pedidos (codigo, ts, usuario, titulo, canal, video_id, estado, estado2, orden) "
            f"VALUES {marcas}",
            tuple(x for f in lote for x in f),
        )
        total += len(lote)
    return total


def agregar_pedido(codigo, usuario, titulo, canal, video_id, estado2="Siguiente", ts=None):
    """Guarda una canción. No la repite si ya está esperando o sonando (pedida hace poco)."""
    ahora = time.time() if ts is None else ts
    limite = ahora - VENTANA_DUPLICADO_HORAS * 3600
    ya = uno(
        """SELECT id FROM pedidos WHERE codigo = %s AND video_id = %s AND ts >= %s
           AND estado <> 'Error' AND estado2 IN ('En cola', 'En reproduccion', 'Siguiente')
           LIMIT 1""",
        (str(codigo), str(video_id), limite),
    )
    if ya:
        return {"ok": True, "duplicado": True}
    fila = uno(
        """INSERT INTO pedidos (codigo, ts, usuario, titulo, canal, video_id, estado, estado2)
           VALUES (%s, %s, %s, %s, %s, %s, 'Agregado', %s) RETURNING id""",
        (str(codigo), ahora, str(usuario), str(titulo), str(canal), str(video_id), estado2),
    )
    return {"ok": True, "id": fila["id"] if fila else None}


def pedidos_desde(codigo, desde):
    return consultar(
        "SELECT * FROM pedidos WHERE codigo = %s AND ts >= %s ORDER BY id",
        (str(codigo), float(desde)),
    )


# Un bar con menos de estas canciones propias recibe también el repertorio compartido
# (lo que ha sonado en TODOS los bares), para que el aleatorio nunca quede vacío.
ALEATORIO_MIN_PROPIO = int(os.getenv("ALEATORIO_MIN_PROPIO", "60"))
ALEATORIO_COMPARTIDO = int(os.getenv("ALEATORIO_COMPARTIDO", "400"))


CATALOGO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalogo")


def sembrar_catalogo():
    """Deja la tabla catalogo igual a services/catalogo/<genero>.json: agrega lo que falte y
    quita lo que ya no está en el archivo (sin volver a meter las que el super eliminó)."""
    import glob
    fuera = {r["video_id"] for r in consultar("SELECT video_id FROM eliminadas")}
    for ruta in glob.glob(os.path.join(CATALOGO_DIR, "*.json")):
        genero = os.path.splitext(os.path.basename(ruta))[0]
        with open(ruta, encoding="utf-8") as f:
            canciones = json.load(f)
        ids = [c["video_id"] for c in canciones if c.get("video_id")]
        sobran = ejecutar("DELETE FROM catalogo WHERE genero = %s AND NOT (video_id = ANY(%s))", (genero, ids))
        if sobran:
            print(f"🎵 Catálogo {genero}: {sobran} canciones quitadas (ya no están en el archivo)")
        ya = {r["video_id"] for r in consultar("SELECT video_id FROM catalogo WHERE genero = %s", (genero,))}
        nuevas = [c for c in canciones if c.get("video_id") and c["video_id"] not in ya | fuera]
        for c in nuevas:
            ejecutar("""INSERT INTO catalogo (video_id, titulo, canal, genero, duracion)
                        VALUES (%s, %s, %s, %s, %s) ON CONFLICT (video_id) DO NOTHING""",
                     (c["video_id"], c.get("titulo", "")[:300], c.get("canal", "")[:200], genero,
                      int(c.get("duracion") or 0)))
        if nuevas:
            print(f"🎵 Catálogo {genero}: {len(nuevas)} canciones nuevas")


def guardar_lista_nube(archivos):
    """Reemplaza la copia de lo que hay en la nube (lista de {nombre, bytes, subido})."""
    vistos = set()
    for a in archivos:
        nombre = str(a.get("nombre") or "")
        if not nombre.endswith(".mp4"):
            continue
        vistos.add(nombre)
        ejecutar("""INSERT INTO nube_archivos (archivo, video_id, bytes, subido) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (archivo) DO UPDATE SET bytes = EXCLUDED.bytes, subido = EXCLUDED.subido""",
                 (nombre, nombre[:-4].rsplit("_", 1)[0], int(a.get("bytes") or 0), float(a.get("subido") or 0)))
    for f in consultar("SELECT archivo FROM nube_archivos"):
        if f["archivo"] not in vistos:
            ejecutar("DELETE FROM nube_archivos WHERE archivo = %s", (f["archivo"],))


def _base_nube():
    """De dónde salen las canciones de la nube: la lista real de Cloudflare (si la API ya la
    copió) o, mientras tanto, las que el servidor ya midió."""
    if uno("SELECT 1 AS si FROM nube_archivos LIMIT 1"):
        return """SELECT n.video_id, MAX(n.subido) AS cuando, SUM(n.bytes) AS bytes
                  FROM nube_archivos n GROUP BY n.video_id"""
    return """SELECT video_id, medido AS cuando, 0 AS bytes FROM volumenes WHERE lufs IS NOT NULL"""


def canciones_nube(buscar="", limite=300):
    """Canciones que están en la nube, con su nombre claro: título, canal, cuántas veces la
    han pedido, género del catálogo, tamaño y volumen parejo. Sin las eliminadas."""
    filtro, params = "", []
    if buscar.strip():
        filtro = ("AND (COALESCE(p.titulo, c.titulo, '') ILIKE %s OR COALESCE(p.canal, c.canal, '') ILIKE %s "
                  "OR b.video_id = %s)")
        params = [f"%{buscar.strip()}%"] * 2 + [buscar.strip()]
    return consultar(f"""
        SELECT b.video_id, b.cuando, b.bytes, v.lufs,
               COALESCE(p.titulo, c.titulo, '') AS titulo, COALESCE(p.canal, c.canal, '') AS canal,
               COALESCE(p.veces, 0) AS veces, COALESCE(c.genero, '') AS genero
        FROM ({_base_nube()}) b
        LEFT JOIN volumenes v ON v.video_id = b.video_id
        LEFT JOIN (SELECT video_id, MAX(titulo) AS titulo, MAX(canal) AS canal, COUNT(*) AS veces
                   FROM pedidos GROUP BY video_id) p ON p.video_id = b.video_id
        LEFT JOIN catalogo c ON c.video_id = b.video_id
        WHERE b.video_id NOT IN (SELECT video_id FROM eliminadas) {filtro}
        ORDER BY b.cuando DESC LIMIT %s""", (*params, int(limite)))


_eliminadas_cache = {"ids": None, "hasta": 0.0}


def ids_eliminadas():
    """Conjunto de video_id eliminados (se relee cada 60 s)."""
    if _eliminadas_cache["ids"] is None or time.time() > _eliminadas_cache["hasta"]:
        try:
            _eliminadas_cache["ids"] = {f["video_id"] for f in consultar("SELECT video_id FROM eliminadas")}
        except Exception:
            _eliminadas_cache["ids"] = _eliminadas_cache["ids"] or set()
        _eliminadas_cache["hasta"] = time.time() + 60
    return _eliminadas_cache["ids"]


def eliminar_cancion(video_id, titulo="", canal=""):
    """El super la elimina: deja de sonar de relleno, sale de los géneros y se borra de la
    nube. Si un cliente la vuelve a pedir, vuelve (ver playbar_service.agregar_cancion)."""
    ejecutar("""INSERT INTO eliminadas (video_id, titulo, canal, cuando) VALUES (%s, %s, %s, %s)
                ON CONFLICT (video_id) DO UPDATE SET cuando = EXCLUDED.cuando, borrada_nube = FALSE""",
             (video_id, str(titulo)[:300], str(canal)[:200], time.time()))
    for tabla in ("catalogo", "volumenes", "encargos"):
        ejecutar(f"DELETE FROM {tabla} WHERE video_id = %s", (video_id,))
    _eliminadas_cache["hasta"] = 0


def restaurar_cancion(video_id):
    ejecutar("DELETE FROM eliminadas WHERE video_id = %s", (video_id,))
    _eliminadas_cache["hasta"] = 0


def canciones_eliminadas():
    return consultar("SELECT video_id, titulo, canal, cuando, borrada_nube FROM eliminadas ORDER BY cuando DESC")


def contar_canciones_nube():
    """(canciones, megas) en la nube, sin las eliminadas."""
    f = uno(f"""SELECT COUNT(*) AS n, COALESCE(SUM(b.bytes), 0) AS bytes FROM ({_base_nube()}) b
                WHERE b.video_id NOT IN (SELECT video_id FROM eliminadas)""")
    return (int(f["n"]), int(f["bytes"]) // (1024 * 1024)) if f else (0, 0)


def catalogo(generos):
    """Canciones del catálogo de esos géneros (cada una con su 'genero')."""
    generos = [g for g in generos if g]
    if not generos:
        return []
    return consultar("""SELECT video_id, titulo, canal, genero, 0 AS ts FROM catalogo
                        WHERE genero = ANY(%s)""", (generos,))


def contar_catalogo(genero):
    f = uno("SELECT COUNT(*) AS n FROM catalogo WHERE genero = %s", (genero,))
    return int(f["n"]) if f else 0


def _generos_de_temporada():
    """Géneros del catálogo que entran solos al relleno en su temporada (diciembre: del 15 de
    noviembre al 15 de enero), aunque el bar no los haya escogido."""
    hoy = time.strftime("%m-%d", time.localtime(time.time() - 5 * 3600))  # hora de Colombia
    return ["diciembre"] if (hoy >= "11-15" or hoy <= "01-15") else []


def aleatorio(codigo, antes_de, limite=3000):
    """Repertorio para cuando nadie pide: el de siempre (_aleatorio_bar) más las canciones del
    catálogo de los géneros que el bar escogió (ej. Diciembre) o que están en temporada."""
    filas = _aleatorio_bar(codigo, antes_de, limite)
    try:
        escogidos = [g.strip() for g in str((control(codigo) or {}).get("generos") or "").split(",")]
        generos = set(g for g in escogidos if g == "diciembre") | set(_generos_de_temporada())
        ya = {f["video_id"] for f in filas}
        filas = list(filas) + [dict(c) for c in catalogo(sorted(generos)) if c["video_id"] not in ya]
    except Exception as ex:
        print(f"⚠️ catálogo en el relleno: {ex}")
    fuera = ids_eliminadas()
    return [f for f in filas if f["video_id"] not in fuera] if fuera else filas


def _aleatorio_bar(codigo, antes_de, limite=3000):
    """Repertorio para cuando nadie pide, sin repetir:
    1) lo que pidieron en ESE bar en fechas anteriores;
    2) si todavía tiene poco (bar nuevo), se completa con lo más pedido en todos los bares
       (solo canciones que de verdad sonaron bien). A medida que el bar arma su propio
       historial, lo compartido deja de usarse solo."""
    propio = consultar(
        """SELECT video_id, MAX(titulo) AS titulo, MAX(canal) AS canal, MAX(ts) AS ts
           FROM pedidos WHERE codigo = %s AND ts < %s AND estado <> 'Error'
             AND estado2 NOT IN ('Eliminado', 'Error')
           GROUP BY video_id ORDER BY MAX(ts) DESC LIMIT %s""",
        (str(codigo), float(antes_de), int(limite)),
    )
    if len(propio) >= ALEATORIO_MIN_PROPIO:
        return propio
    ya = {f["video_id"] for f in propio}
    compartido = consultar(
        """SELECT video_id, MAX(titulo) AS titulo, MAX(canal) AS canal, MAX(ts) AS ts
           FROM pedidos WHERE codigo <> %s AND estado <> 'Error' AND estado2 = 'Reproducido'
           GROUP BY video_id
           ORDER BY COUNT(DISTINCT codigo) DESC, COUNT(*) DESC, MAX(ts) DESC LIMIT %s""",
        (str(codigo), ALEATORIO_COMPARTIDO),
    )
    return propio + [f for f in compartido if f["video_id"] not in ya]


def marcar(codigo, id_pedido, estado2=None, estado=None):
    if estado2 is not None:
        ejecutar("UPDATE pedidos SET estado2 = %s WHERE id = %s AND codigo = %s",
                 (estado2, int(id_pedido), str(codigo)))
    if estado is not None:
        ejecutar("UPDATE pedidos SET estado = %s WHERE id = %s AND codigo = %s",
                 (estado, int(id_pedido), str(codigo)))


def reordenar(codigo, ids):
    """Nuevo orden de la cola: reparte entre esas canciones las claves que ya tenían,
    así lo que pidan después sigue quedando al final."""
    ids = [int(i) for i in ids]
    if not ids:
        return
    marcas = ", ".join(["%s"] * len(ids))
    filas = consultar(
        f"SELECT id, COALESCE(orden, id) AS clave FROM pedidos WHERE codigo = %s AND id IN ({marcas})",
        (str(codigo), *ids),
    )
    claves = sorted(float(f["clave"]) for f in filas)
    existentes = {f["id"] for f in filas}
    pares = [(i, k) for i, k in zip([i for i in ids if i in existentes], claves)]
    if not pares:
        return
    valores = ", ".join(["(%s, %s)"] * len(pares))
    ejecutar(
        f"""UPDATE pedidos AS p SET orden = v.o
            FROM (VALUES {valores}) AS v(id, o)
            WHERE p.id = v.id AND p.codigo = %s""",
        tuple(x for par in pares for x in (int(par[0]), float(par[1]))) + (str(codigo),),
    )


def cerrar_atascadas(codigo, antes_de):
    """Filas de días anteriores que quedaron como activas pasan a Reproducido."""
    return ejecutar(
        """UPDATE pedidos SET estado2 = 'Reproducido' WHERE codigo = %s AND ts < %s
           AND estado2 IN ('En cola', 'En reproduccion', 'Siguiente')""",
        (str(codigo), float(antes_de)),
    )


def tabla(codigo, desde=0, limite=1000):
    """Para la ventana 'Ver tabla' y el Excel: lo más nuevo primero."""
    return consultar(
        "SELECT * FROM pedidos WHERE codigo = %s AND ts >= %s ORDER BY id DESC LIMIT %s",
        (str(codigo), float(desde or 0), int(limite)),
    )


def pedidos_de_usuario(codigo, usuario, limite=200):
    return consultar(
        "SELECT * FROM pedidos WHERE codigo = %s AND usuario = %s ORDER BY id DESC LIMIT %s",
        (str(codigo), str(usuario), int(limite)),
    )


def contar_pedidos(codigo):
    f = uno("SELECT COUNT(*) AS n FROM pedidos WHERE codigo = %s", (str(codigo),))
    return int(f["n"]) if f else 0


# ---------------------------------------------------------------------------
# Control (admin -> reproductor)
# ---------------------------------------------------------------------------
def control(codigo):
    return uno("SELECT * FROM control WHERE codigo = %s", (str(codigo),)) or {}


def _asegurar_control(codigo):
    ejecutar("INSERT INTO control (codigo) VALUES (%s) ON CONFLICT (codigo) DO NOTHING",
             (str(codigo),))


def poner_generos(codigo, claves):
    """Relleno del bar: lista de claves de géneros, o el texto ya armado con
    generos.guardar_texto() (géneros + "artista:<nombre>"). Vacío = todo."""
    _asegurar_control(codigo)
    texto = claves if isinstance(claves, str) else ",".join(sorted(set(claves)))
    ejecutar("UPDATE control SET generos = %s WHERE codigo = %s", (texto, str(codigo)))


def enviar_comando(codigo, comando, param=""):
    _asegurar_control(codigo)
    cid = f"{int(time.time())}-{secrets.token_hex(3)}"
    ejecutar("UPDATE control SET comando = %s, comando_id = %s, param = %s WHERE codigo = %s",
             (comando, cid, str(param or ""), str(codigo)))
    return cid


REPRODUCTOR_VENCE_SEG = 90  # si el reproductor activo no avisa en este tiempo, se apagó


def reclamar_reproductor(codigo, instancia, equipo="", forzar=False, info=None):
    """(activo, equipo que lo tiene). Ver reproductor()."""
    r = reproductor(codigo, instancia, equipo, forzar, info)
    return r["activo"], r["equipo"]


def reproductor(codigo, instancia, equipo="", forzar=False, info=None, espejo=True):
    """Quién suena en el bar. El bar puede tener abierto el reproductor en tantos equipos
    como `clientes.televisores` (por defecto 1):

      * el PRINCIPAL maneja la cola (control.instancia). Lo es el primero que llega, o
        cualquiera si el principal dejó de avisar hace más de REPRODUCTOR_VENCE_SEG;
      * los demás, hasta completar el número, son ESPEJOS: muestran la misma canción
        (ver estado_principal());
      * uno de más queda inactivo ("Usar aquí"). Con `forzar` ("Usar aquí") entra
        sacando al espejo más antiguo, o al principal si el bar tiene un solo televisor.

    `espejo=False`: reproductor viejo que no sabe ser espejo; para él cuenta 1 televisor.
    Devuelve {"activo", "rol": "principal"|"espejo"|"", "equipo": quién tiene el control}."""
    codigo, instancia = str(codigo), str(instancia)
    equipo = str(equipo or "")[:60]
    _asegurar_control(codigo)
    ahora = time.time()
    limite_visto = ahora - REPRODUCTOR_VENCE_SEG
    fila_tv = uno("SELECT televisores FROM clientes WHERE codigo = %s", (codigo,))
    televisores = max(1, int((fila_tv or {}).get("televisores") or 1)) if espejo else 1
    info_txt = json.dumps(info, ensure_ascii=False)[:2000] if info else ""

    fila = uno("""UPDATE control SET instancia = %s, instancia_nombre = %s, instancia_visto = %s
                  WHERE codigo = %s AND (%s OR instancia = '' OR instancia = %s
                                         OR instancia_visto < %s)
                  RETURNING instancia_nombre""",
               (instancia, equipo, ahora, codigo, bool(forzar and televisores == 1), instancia,
                limite_visto))
    if fila:
        ejecutar("DELETE FROM reproductores WHERE codigo = %s AND instancia = %s",
                 (codigo, instancia))
        if info_txt:
            ejecutar("UPDATE control SET equipo_info = %s WHERE codigo = %s", (info_txt, codigo))
        return {"activo": True, "rol": "principal", "equipo": fila["instancia_nombre"]}

    ctl = uno("SELECT instancia, instancia_nombre FROM control WHERE codigo = %s", (codigo,)) or {}
    principal = ctl.get("instancia_nombre") or "otro equipo"
    if televisores > 1:
        otros = consultar("""SELECT instancia FROM reproductores
                             WHERE codigo = %s AND visto >= %s AND instancia <> %s
                             ORDER BY desde""", (codigo, limite_visto, ctl.get("instancia") or ""))
        ya = any(o["instancia"] == instancia for o in otros)
        libre = 1 + len(otros) < televisores
        if not ya and not libre and forzar and otros:
            ejecutar("DELETE FROM reproductores WHERE codigo = %s AND instancia = %s",
                     (codigo, otros[0]["instancia"]))  # sale el espejo más antiguo
            libre = True
        if ya or libre:
            ejecutar("""INSERT INTO reproductores (codigo, instancia, equipo, desde, visto, info)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (codigo, instancia) DO UPDATE SET equipo = EXCLUDED.equipo,
                            visto = EXCLUDED.visto,
                            info = CASE WHEN EXCLUDED.info = '' THEN reproductores.info
                                        ELSE EXCLUDED.info END""",
                     (codigo, instancia, equipo, ahora, ahora, info_txt))
            return {"activo": True, "rol": "espejo", "equipo": principal}
    return {"activo": False, "rol": "", "equipo": principal}


def estado_principal(codigo):
    """Lo que suena en el televisor principal, para que los espejos lo sigan. `pos` es la
    posición (segundos) en este momento, calculada con el reloj del servidor."""
    c = control(codigo)
    if not c:
        return {}
    pos = float(c.get("actual_pos") or 0)
    if c.get("estado") in ("reproduciendo", "relleno") and c.get("actual_ts"):
        pos += max(0.0, time.time() - float(c["actual_ts"]))
    return {"video": c.get("actual_video") or "", "titulo": c.get("actual") or "",
            "canal": c.get("actual_canal") or "", "siguiente": c.get("siguiente_video") or "",
            "estado": c.get("estado") or "", "pos": round(pos, 2)}


def reproductores_activos(codigo):
    """Los televisores espejo en línea del bar (para /super)."""
    return consultar("""SELECT equipo, info, visto FROM reproductores
                        WHERE codigo = %s AND visto >= %s ORDER BY desde""",
                     (str(codigo), time.time() - REPRODUCTOR_VENCE_SEG))


def publicar_estado(codigo, estado, actual="", siguiente="", ack=None, video=None):
    """`video` (de los reproductores nuevos): {"id", "canal", "siguiente", "pos"} de lo que
    suena, para que los televisores espejo lo sigan."""
    _asegurar_control(codigo)
    if isinstance(video, dict):
        try:
            pos = float(video.get("pos") or 0)
        except (TypeError, ValueError):
            pos = 0.0
        ejecutar("""UPDATE control SET actual_video = %s, actual_canal = %s, siguiente_video = %s,
                    actual_pos = %s, actual_ts = %s WHERE codigo = %s""",
                 (str(video.get("id") or "")[:40], str(video.get("canal") or "")[:200],
                  str(video.get("siguiente") or "")[:40], pos, time.time(), str(codigo)))
    if ack is None:
        ejecutar("""UPDATE control SET estado = %s, actual = %s, siguiente = %s, latido = %s
                    WHERE codigo = %s""",
                 (estado, actual or "", siguiente or "", time.time(), str(codigo)))
    else:
        ejecutar("""UPDATE control SET estado = %s, actual = %s, siguiente = %s, latido = %s,
                    ack = %s WHERE codigo = %s""",
                 (estado, actual or "", siguiente or "", time.time(), str(ack), str(codigo)))


# ---------------------------------------------------------------------------
# Caché de búsquedas de YouTube
# ---------------------------------------------------------------------------
def busqueda(consulta_txt, max_edad_seg):
    f = uno("SELECT datos, ts FROM busquedas WHERE consulta = %s", (consulta_txt,))
    if not f or time.time() - float(f["ts"]) > max_edad_seg:
        return None
    try:
        return json.loads(f["datos"])
    except Exception:
        return None


def guardar_busqueda(consulta_txt, datos):
    ejecutar(
        """INSERT INTO busquedas (consulta, datos, ts) VALUES (%s, %s, %s)
           ON CONFLICT (consulta) DO UPDATE SET datos = EXCLUDED.datos, ts = EXCLUDED.ts""",
        (consulta_txt, json.dumps(datos, ensure_ascii=False), time.time()),
    )


# ---------------------------------------------------------------------------
# Descargas temporales (Excel desde el panel web)
# ---------------------------------------------------------------------------
def crear_descarga(codigo, minutos=10):
    token = secrets.token_urlsafe(18)
    ejecutar("DELETE FROM descargas WHERE expira < %s", (time.time(),))
    ejecutar("INSERT INTO descargas (token, codigo, expira) VALUES (%s, %s, %s)",
             (token, str(codigo), time.time() + minutos * 60))
    return token


def usar_descarga(token):
    f = uno("SELECT codigo, expira FROM descargas WHERE token = %s", (str(token),))
    if not f or float(f["expira"]) < time.time():
        return None
    return f["codigo"]


# ---------------------------------------------------------------------------
# Sesiones de la app web (sobreviven a F5, cerrar la app y reinicios del servidor)
# ---------------------------------------------------------------------------
DURACION_SESION_HORAS = {"usuario": 24 * 30, "admin": 24, "super": 12}


def crear_sesion(datos, rol="usuario"):
    token = secrets.token_urlsafe(24)
    ahora = time.time()
    horas = DURACION_SESION_HORAS.get(rol, 24)
    ejecutar("DELETE FROM sesiones WHERE expira < %s", (ahora,))
    ejecutar("INSERT INTO sesiones (token, rol, datos, creado, expira) VALUES (%s, %s, %s, %s, %s)",
             (token, rol, json.dumps(datos, ensure_ascii=False), ahora, ahora + horas * 3600))
    return token


def leer_sesion(token):
    """Datos de la sesión (con 'rol' y 'token') o None si no existe o venció.
    Las de usuario se renuevan solas cada vez que se usan."""
    if not token:
        return None
    f = uno("SELECT rol, datos, expira FROM sesiones WHERE token = %s", (str(token),))
    if not f or float(f["expira"]) < time.time():
        return None
    try:
        datos = json.loads(f["datos"])
    except Exception:
        return None
    if f["rol"] == "usuario":
        ejecutar("UPDATE sesiones SET expira = %s WHERE token = %s",
                 (time.time() + DURACION_SESION_HORAS["usuario"] * 3600, str(token)))
    datos.update(rol=f["rol"], token=str(token))
    return datos


def borrar_sesion(token):
    if token:
        ejecutar("DELETE FROM sesiones WHERE token = %s", (str(token),))


# ---------------------------------------------------------------------------
# Encargos: canciones que hay que subir a la nube (las baja un TV o PC con la app)
# ---------------------------------------------------------------------------
ENCARGO_PLAZO_SEG = 5 * 60      # si quien la tomó no avisa en 5 min, otro la puede tomar
ENCARGO_INTENTOS = 3
ENCARGO_VIGENCIA_SEG = 3 * 3600  # los encargos viejos ya no se reparten


def encargar(video_id, titulo, canal, codigo, pedido=True):
    """Pide que la canción quede en la nube. Devuelve el estado: pendiente, tomado o fallo.
    Las que un cliente pidió (pedido=True) van antes que las aleatorias del relleno."""
    ahora = time.time()
    prioridad = 1 if pedido else 0
    f = uno("SELECT estado, tomado, creado, prioridad FROM encargos WHERE video_id = %s", (video_id,))
    if f is None:
        ejecutar("""INSERT INTO encargos (video_id, titulo, canal, codigo, creado, prioridad)
                    VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (video_id) DO NOTHING""",
                 (video_id, str(titulo)[:300], str(canal)[:200], str(codigo), ahora, prioridad))
        return "pendiente"
    if prioridad > int(f["prioridad"] or 0):
        ejecutar("UPDATE encargos SET prioridad = %s WHERE video_id = %s", (prioridad, video_id))
    estado = f["estado"]
    # "listo" pero no está en la nube (se borró o la subida falló), o un fallo viejo, o un
    # encargo que nadie tomó a tiempo: se vuelve a pedir.
    viejo = ahora - float(f["creado"] or 0) > ENCARGO_VIGENCIA_SEG
    if (estado == "listo" and ahora - float(f["tomado"] or 0) > 120) or             (estado == "fallo" and ahora - float(f["tomado"] or 0) > 6 * 3600) or             (estado in ("pendiente", "tomado") and viejo):
        ejecutar("""UPDATE encargos SET estado = 'pendiente', intentos = 0, creado = %s, error = '',
                    codigo = %s WHERE video_id = %s""", (ahora, str(codigo), video_id))
        return "pendiente"
    return "listo" if estado == "listo" else estado


def tomar_encargo(quien):
    """Un TV/PC con la app se ofrece a bajar una canción: se le da la más antigua pendiente
    (o una que otro tomó y no terminó). {} si no hay."""
    ahora = time.time()
    ejecutar("""UPDATE encargos SET estado = 'fallo', error = 'nadie la pudo bajar'
                WHERE estado = 'tomado' AND tomado < %s AND intentos >= %s""",
             (ahora - ENCARGO_PLAZO_SEG, ENCARGO_INTENTOS))
    f = consultar("""UPDATE encargos SET estado = 'tomado', tomado = %s, tomado_por = %s,
                         intentos = intentos + 1
                     WHERE video_id = (
                         SELECT video_id FROM encargos
                         WHERE (estado = 'pendiente' OR (estado = 'tomado' AND tomado < %s))
                           AND intentos < %s AND creado > %s
                         ORDER BY prioridad DESC, creado LIMIT 1 FOR UPDATE SKIP LOCKED)
                     RETURNING video_id, titulo, canal""",
                  (ahora, str(quien)[:80], ahora - ENCARGO_PLAZO_SEG, ENCARGO_INTENTOS,
                   ahora - ENCARGO_VIGENCIA_SEG))
    return dict(f[0]) if f else {}


def terminar_encargo(video_id, ok, error=""):
    if ok:
        ejecutar("UPDATE encargos SET estado = 'listo', tomado = %s, error = '' WHERE video_id = %s",
                 (time.time(), video_id))
        return
    ejecutar("""UPDATE encargos SET error = %s,
                    estado = CASE WHEN intentos >= %s THEN 'fallo' ELSE 'pendiente' END
                WHERE video_id = %s""", (str(error)[:300], ENCARGO_INTENTOS, video_id))


def borrar_encargos_viejos():
    ejecutar("DELETE FROM encargos WHERE creado < %s", (time.time() - 7 * 86400,))
