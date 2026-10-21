"""
PlayBar GO - Servidor de respaldo (Fly.io), igual que el de ALNOVIX.

Variable ROL_PLAYBAR:
  principal (por defecto, Railway): la API entrega una copia completa de la base en
      GET /sistema/respaldo/exportar (cabecera X-Respaldo-Token = PLAYBAR_RESPALDO_TOKEN).
  respaldo (Fly.io): la API descarga esa copia cada hora (PLAYBAR_RESPALDO_INTERVALO_MIN)
      desde PLAYBAR_PRIMARIO_URL y la carga en su propia base. En el respaldo no corre el
      revisor de pagos de Wompi ni la migración automática.

Si Railway se cae y el tráfico pasa al respaldo, en cuanto la base del respaldo recibe
cambios (pedidos, pagos...) se deja de copiar, para no borrarlos, hasta devolverlos al
principal. Se detecta con los contadores de PostgreSQL (pg_stat_user_tables).
"""
from __future__ import annotations

import gzip
import io
import json
import os
import shutil
import tempfile
import threading
import time
import urllib.request
import zipfile
from datetime import datetime, timezone

ROL = os.getenv("ROL_PLAYBAR", "principal").strip().lower()
ES_RESPALDO = ROL == "respaldo"
TOKEN = os.getenv("PLAYBAR_RESPALDO_TOKEN", "").strip()
PRIMARIO_URL = os.getenv("PLAYBAR_PRIMARIO_URL", "").strip().rstrip("/")
TABLA_ESTADO = "sistema_respaldo_estado"


def _intervalo_seg():
    try:
        return max(5, int(os.getenv("PLAYBAR_RESPALDO_INTERVALO_MIN", "60"))) * 60
    except ValueError:
        return 3600


def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _q(nombre):
    return '"' + nombre.replace('"', '""') + '"'


def _conectar():
    import psycopg
    return psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=15)


def _tablas(cur):
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' "
                "AND table_type='BASE TABLE' ORDER BY table_name")
    return [t for (t,) in cur.fetchall() if t != TABLA_ESTADO]


def _columnas(cur, tabla):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' "
                "AND table_name=%s ORDER BY ordinal_position", (tabla,))
    return [c for (c,) in cur.fetchall()]


# ---------------------------------------------------------------------------
# Exportar (principal)
# ---------------------------------------------------------------------------
def exportar_a_archivo():
    tmp = tempfile.NamedTemporaryFile(prefix="playbar_respaldo_", suffix=".zip", delete=False)
    tmp.close()
    manifest = {"fecha": _ahora(), "tablas": {}}
    with _conectar() as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cur = conn.cursor()
        with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_STORED) as z:
            for tabla in _tablas(cur):
                columnas = _columnas(cur, tabla)
                datos = io.BytesIO()
                with gzip.GzipFile(fileobj=datos, mode="wb", compresslevel=6) as gz:
                    with cur.copy(f"COPY {_q(tabla)} ({', '.join(map(_q, columnas))}) TO STDOUT WITH (FORMAT csv)") as copia:
                        for trozo in copia:
                            gz.write(trozo)
                z.writestr(f"{tabla}.csv.gz", datos.getvalue())
                manifest["tablas"][tabla] = columnas
            z.writestr("manifest.json", json.dumps(manifest))
        conn.rollback()
    return tmp.name


# ---------------------------------------------------------------------------
# Estado del respaldo (tabla propia; no se exporta ni se sobrescribe)
# ---------------------------------------------------------------------------
def _asegurar_estado(conn):
    conn.execute(f"CREATE TABLE IF NOT EXISTS {TABLA_ESTADO} (clave VARCHAR(60) PRIMARY KEY, valor TEXT)")


def leer_estado():
    with _conectar() as conn:
        _asegurar_estado(conn)
        filas = conn.execute(f"SELECT clave, valor FROM {TABLA_ESTADO}").fetchall()
        conn.commit()
    return {k: v for k, v in filas}


def guardar_estado(**valores):
    with _conectar() as conn:
        _asegurar_estado(conn)
        for clave, valor in valores.items():
            conn.execute(f"INSERT INTO {TABLA_ESTADO} (clave, valor) VALUES (%s, %s) "
                         "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor",
                         (clave, None if valor is None else str(valor)))
        conn.commit()


def _contador_cambios(conn):
    """Total de filas insertadas/actualizadas/borradas en la base (sin la tabla de estado)."""
    fila = conn.execute("SELECT COALESCE(SUM(n_tup_ins + n_tup_upd + n_tup_del), 0) FROM pg_stat_user_tables "
                        "WHERE relname <> %s", (TABLA_ESTADO,)).fetchone()
    return int(fila[0])


# ---------------------------------------------------------------------------
# Importar (respaldo)
# ---------------------------------------------------------------------------
def importar_archivo(ruta):
    resumen = {"tablas": 0, "omitidas": []}
    with _conectar() as conn:
        cur = conn.cursor()
        with zipfile.ZipFile(ruta) as z:
            manifest = json.loads(z.read("manifest.json"))
            locales = set(_tablas(cur))
            tablas = [t for t in manifest["tablas"] if t in locales]
            resumen["omitidas"] = [t for t in manifest["tablas"] if t not in locales]
            cur.execute("SET session_replication_role = replica")
            if tablas:
                cur.execute("TRUNCATE " + ", ".join(map(_q, tablas)) + " CASCADE")
            for tabla in tablas:
                columnas = manifest["tablas"][tabla]
                if not set(columnas) <= set(_columnas(cur, tabla)):
                    resumen["omitidas"].append(tabla)
                    continue
                datos = gzip.decompress(z.read(f"{tabla}.csv.gz"))
                with cur.copy(f"COPY {_q(tabla)} ({', '.join(map(_q, columnas))}) FROM STDIN WITH (FORMAT csv)") as copia:
                    copia.write(datos)
                resumen["tablas"] += 1
            cur.execute("SET session_replication_role = DEFAULT")
            cur.execute("""SELECT c.table_name, c.column_name, pg_get_serial_sequence(quote_ident(c.table_name), c.column_name)
                           FROM information_schema.columns c
                           WHERE c.table_schema='public' AND c.column_default LIKE 'nextval(%%'""")
            for tabla, columna, secuencia in cur.fetchall():
                if secuencia and tabla in tablas:
                    cur.execute(f"SELECT setval(%s, COALESCE((SELECT MAX({_q(columna)}) FROM {_q(tabla)}), 0) + 1, false)",
                                (secuencia,))
        conn.commit()
    return resumen


def sincronizar_una_vez():
    if not PRIMARIO_URL or not TOKEN:
        return "Falta PLAYBAR_PRIMARIO_URL o PLAYBAR_RESPALDO_TOKEN."
    try:
        from services import db
        db.asegurar()  # crea las tablas si es la primera vez
    except Exception as ex:  # noqa: BLE001
        print("RESPALDO: no se pudo preparar la base:", ex)
    estado = leer_estado()
    if estado.get("con_cambios_desde"):
        return ("El respaldo recibió cambios desde " + estado["con_cambios_desde"]
                + ": no se sobrescribe hasta devolverlos al principal.")
    with _conectar() as conn:
        actual = _contador_cambios(conn)
    base = estado.get("contador_tras_copia")
    if base is not None and actual > int(base):
        guardar_estado(con_cambios_desde=_ahora())
        return "El respaldo recibió cambios: se deja de copiar para no borrarlos."
    req = urllib.request.Request(PRIMARIO_URL + "/sistema/respaldo/exportar",
                                 headers={"X-Respaldo-Token": TOKEN, "User-Agent": "PlayBar-Respaldo/1.0"})
    tmp = tempfile.NamedTemporaryFile(prefix="playbar_copia_", suffix=".zip", delete=False)
    tmp.close()
    inicio = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r, open(tmp.name, "wb") as f:
            shutil.copyfileobj(r, f)
        tamano = os.path.getsize(tmp.name)
        resumen = importar_archivo(tmp.name)
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass
    time.sleep(3)  # los contadores de PostgreSQL se actualizan un instante después
    with _conectar() as conn:
        despues = _contador_cambios(conn)
    guardar_estado(ultima_sincronizacion=_ahora(), ultimo_tamano=tamano, ultimas_tablas=resumen["tablas"],
                   contador_tras_copia=despues, ultimo_error="")
    return f"Copia cargada: {resumen['tablas']} tablas, {tamano / 1e6:.1f} MB, {time.time() - inicio:.0f} s."


def iniciar_sincronizacion():
    def ciclo():
        time.sleep(20)
        while True:
            try:
                print("RESPALDO:", sincronizar_una_vez())
            except Exception as ex:  # noqa: BLE001
                print("RESPALDO: error copiando desde el principal:", repr(ex)[:300])
                try:
                    guardar_estado(ultimo_error=f"{_ahora()} {repr(ex)[:300]}")
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(_intervalo_seg())

    threading.Thread(target=ciclo, daemon=True, name="respaldo-sync").start()
    print(f"RESPALDO: copia automática cada {_intervalo_seg() // 60} min desde {PRIMARIO_URL or '(sin configurar)'}.")
