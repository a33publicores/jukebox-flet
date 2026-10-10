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


def nueva_llave():
    return "pbg_" + secrets.token_urlsafe(24)


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
    return uno("SELECT * FROM clientes WHERE llave = %s AND activo", (str(llave).strip(),))


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
    for f in consultar("SELECT usuario, clave FROM admins WHERE activo AND rol = 'super'"):
        if f["usuario"].strip().lower() == u and clave_correcta(c, f["clave"]):
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


def aleatorio(codigo, antes_de, limite=3000):
    """Repertorio para cuando nadie pide: canciones de fechas anteriores, sin repetir."""
    return consultar(
        """SELECT video_id, MAX(titulo) AS titulo, MAX(canal) AS canal, MAX(ts) AS ts
           FROM pedidos WHERE codigo = %s AND ts < %s AND estado <> 'Error'
             AND estado2 NOT IN ('Eliminado', 'Error')
           GROUP BY video_id ORDER BY MAX(ts) DESC LIMIT %s""",
        (str(codigo), float(antes_de), int(limite)),
    )


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


def enviar_comando(codigo, comando, param=""):
    _asegurar_control(codigo)
    cid = f"{int(time.time())}-{secrets.token_hex(3)}"
    ejecutar("UPDATE control SET comando = %s, comando_id = %s, param = %s WHERE codigo = %s",
             (comando, cid, str(param or ""), str(codigo)))
    return cid


def publicar_estado(codigo, estado, actual="", siguiente="", ack=None):
    _asegurar_control(codigo)
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
