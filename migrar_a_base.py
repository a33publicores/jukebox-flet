"""
Copia TODO lo de Google Sheets (hoja Jukebox) a la base PostgreSQL de Railway. Se corre
UNA vez, en tu PC, con  MIGRAR_A_BASE.bat.

Copia:
    CLIENTES  -> negocios (y les crea su llave para el reproductor)
    ADMINS    -> administradores (las claves quedan cifradas)
    pestaña de cada negocio (A33, BAR01...) -> pedidos (historial para el aleatorio)

Se puede volver a correr: los negocios se actualizan, los admins repetidos se saltan y
los pedidos de un negocio que ya tiene pedidos en la base NO se duplican
(usa  --forzar  para copiarlos otra vez).
Al final escribe llaves_bares.txt con el código y la llave de cada bar (no se sube a GitHub).
"""
import html
import os
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))

SPREADSHEET_ID = "1F1SMAyyY1iUKRX5QjiyrrMmv7W4z27gBsRMS8ZVGNS0"


ALCANCE = ["https://www.googleapis.com/auth/spreadsheets.readonly"]


def _abrir_hoja():
    import gspread
    from google.oauth2 import service_account
    b64 = os.environ.get("GOOGLE_CREDENTIALS_B64", "").strip()
    if b64:  # en Railway: la misma variable que usaba la app con Sheets
        import base64
        import json
        info = json.loads(base64.b64decode(b64).decode("utf-8"))
        creds = service_account.Credentials.from_service_account_info(info, scopes=ALCANCE)
        print("🔑 Credenciales: variable GOOGLE_CREDENTIALS_B64")
        return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
    for d in (AQUI, AQUI.parent, Path.home() / "PlayBarGo"):
        f = d / "credenciales.json"
        if f.is_file():
            creds = service_account.Credentials.from_service_account_file(str(f), scopes=ALCANCE)
            print(f"🔑 Credenciales: {f}")
            return gspread.authorize(creds).open_by_key(SPREADSHEET_ID)
    raise SystemExit("❌ No encontré credenciales.json (en esta carpeta o en la de arriba).")


def _col(row, i):
    return str(row[i]).strip() if len(row) > i and row[i] is not None else ""


def _num(t):
    try:
        return float(str(t).replace(",", "."))
    except (TypeError, ValueError):
        return None


def migrar(ss, forzar=False, pausa=1.2):
    from services import db
    from services import playbar_service as ps

    db.asegurar()
    resumen = {"negocios": 0, "admins": 0, "pedidos": 0, "saltados": []}

    # ---------------------------------------------------------------- CLIENTES
    clientes = ss.worksheet("CLIENTES").get_all_records()
    negocios = []
    for r in clientes:
        codigo = str(r.get("Codigo", r.get("codigo", ""))).strip()
        nombre = str(r.get("Nombre", r.get("nombre", ""))).strip()
        if not codigo or not nombre:
            continue
        activo = str(r.get("Activo", r.get("activo", ""))).upper().strip() in ("TRUE", "1", "SI", "SÍ")
        fila = db.guardar_cliente(codigo, nombre, str(r.get("Logo", r.get("logo", "")) or ""),
                                  str(r.get("Playlist", r.get("playlist", "")) or ""), activo)
        negocios.append(fila)
        resumen["negocios"] += 1
        print(f"🏪 {codigo} · {nombre} · {'activo' if activo else 'inactivo'}")

    # ------------------------------------------------------------------ ADMINS
    try:
        filas = ss.worksheet("ADMINS").get_all_values()[1:]
    except Exception:
        filas = []
    existentes = {(a["codigo"], a["usuario"].lower()) for a in db.admins()}
    for row in filas:
        cod, usr, clave, activo, nota = (_col(row, i) for i in range(5))
        if cod.endswith(".0"):
            cod = cod[:-2]
        if clave.endswith(".0") and clave[:-2].isdigit():
            clave = clave[:-2]
        if not cod or not usr or not clave or (cod, usr.lower()) in existentes:
            continue
        a = db.agregar_admin(cod, usr, clave, nota=nota or "importado de Sheets")
        if activo.upper() in ("FALSE", "NO", "0"):
            db.cambiar_admin(a["id"], activo=False)
        existentes.add((cod, usr.lower()))
        resumen["admins"] += 1
        print(f"👤 admin {usr} ({cod})")

    # ------------------------------------------------- pedidos de cada negocio
    for n in negocios:
        if not forzar and db.contar_pedidos(n["codigo"]):
            resumen["saltados"].append(n["nombre"])
            print(f"⏭️ {n['nombre']}: ya tiene pedidos en la base (usa --forzar para copiarlos otra vez)")
            continue
        try:
            valores = ss.worksheet(n["nombre"]).get_values("A:I")
        except Exception as ex:
            print(f"⚠️ {n['nombre']}: no se pudo leer su pestaña ({ex})")
            continue
        lote, ahora = [], time.time()
        for row in valores[1:]:
            vid = _col(row, 5)
            if not vid:
                continue
            ts = ps.epoch_local(_col(row, 0)) or ahora
            estado, estado2 = _col(row, 6) or "Agregado", _col(row, 7)
            if estado in ("Pendiente", "Procesando"):  # del modo viejo (playlist de YouTube)
                estado = "Agregado"
                estado2 = estado2 or ("Siguiente" if ts >= ps.inicio_jornada() else "Reproducido")
            lote.append((
                n["codigo"], float(ts), _col(row, 2), html.unescape(_col(row, 3)),
                html.unescape(_col(row, 4)), vid, estado, estado2, _num(_col(row, 8)),
            ))
        total = db.importar_pedidos(lote)
        resumen["pedidos"] += total
        print(f"🎵 {n['nombre']}: {total} pedidos copiados")
        time.sleep(pausa)  # no gastar la cuota de lectura de Google

    # Lo viejo que quedó "En reproduccion"/"Siguiente" pasa a Reproducido.
    for n in negocios:
        db.cerrar_atascadas(n["codigo"], ps.inicio_jornada())
    return resumen, negocios


def migrar_automatica():
    """En Railway, al arrancar la app: si la base está vacía y existe
    GOOGLE_CREDENTIALS_B64, copia todo desde Sheets sin que nadie corra nada."""
    from services import db
    try:
        if db.clientes():
            return  # ya hay datos: nunca se repite
        if not os.environ.get("GOOGLE_CREDENTIALS_B64", "").strip():
            print("ℹ️ Base vacía y sin GOOGLE_CREDENTIALS_B64: crea los negocios desde /super")
            return
        print("🚚 Base vacía: copiando automáticamente desde Google Sheets…")
        resumen, _ = migrar(_abrir_hoja())
        print(f"✅ Migración automática: {resumen['negocios']} negocios, {resumen['admins']} admins, "
              f"{resumen['pedidos']} pedidos. Las llaves se ven en /super.")
    except Exception as ex:
        print(f"❌ Migración automática falló: {type(ex).__name__}: {ex}")


def _guardar_llaves(negocios):
    from services import db
    lineas = ["Llaves de los reproductores PlayBar GO (NO compartir ni subir a GitHub)", ""]
    for n in negocios:
        c = db.cliente(n["codigo"])
        lineas.append(f"{c['codigo']:<8} {c['nombre']:<20} {c['llave']}")
    destino = AQUI / "llaves_bares.txt"
    destino.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return destino, lineas


def main():
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("Pega la dirección de la base (en Railway: PostgreSQL → Variables → "
              "DATABASE_PUBLIC_URL) y presiona Enter:")
        url = input("> ").strip()
    if not url.startswith("postgres"):
        raise SystemExit("❌ Esa no parece la dirección de PostgreSQL (empieza por postgresql://).")
    if "railway.internal" in url:
        raise SystemExit("❌ Esa es la dirección INTERNA (solo funciona dentro de Railway).\n"
                         "   Usa DATABASE_PUBLIC_URL (la que dice ...proxy.rlwy.net:NÚMERO).")
    os.environ["DATABASE_URL"] = url
    resumen, negocios = migrar(_abrir_hoja(), forzar="--forzar" in sys.argv)
    destino, lineas = _guardar_llaves(negocios)
    print("\n" + "\n".join(lineas))
    print(f"\n✅ Listo: {resumen['negocios']} negocios, {resumen['admins']} admins, "
          f"{resumen['pedidos']} pedidos copiados.")
    print(f"🔑 Llaves guardadas en {destino}")


if __name__ == "__main__":
    main()
