"""
API de PlayBar GO para los reproductores de los bares (servicio aparte en Railway).

Cada reproductor se identifica con la LLAVE de su negocio (encabezado X-Llave).
La contraseña de la base de datos nunca sale de Railway; si un PC se pierde, el super
administrador regenera la llave de ese negocio y la vieja deja de servir.

Arranque en Railway:   python -m api.servidor      (usa la variable PORT)
"""
import os
import time
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from api import pagos
from services import cola, db, exportar
from services import playbar_service as ps
from services import respaldo
from services import suscripcion as sus

_cache_llaves = {}  # llave -> (cliente, hora)


def _cliente_de(request):
    llave = request.headers.get("x-llave", "").strip()
    if not llave:
        return None
    c = _cache_llaves.get(llave)
    if c and time.time() - c[1] < 60:
        return c[0]
    cli = db.cliente_por_llave(llave)
    _cache_llaves[llave] = (cli, time.time())
    return cli


def _protegido(fn):
    """La función protegida es normal (no async): corre en un hilo aparte, así una
    consulta lenta a la base no frena a los demás bares."""
    async def envoltura(request):
        try:
            cli = await run_in_threadpool(_cliente_de, request)
        except Exception as ex:
            print(f"❌ API llave: {ex}")
            return JSONResponse({"ok": False, "error": "BASE_NO_DISPONIBLE"}, status_code=503)
        if not cli:
            return JSONResponse({"ok": False, "error": "LLAVE_INVALIDA"}, status_code=401)
        cuerpo = await _json(request) if request.method == "POST" else {}
        try:
            return await run_in_threadpool(fn, request, cli, cuerpo)
        except Exception as ex:
            print(f"❌ API {request.url.path}: {type(ex).__name__}: {ex}")
            return JSONResponse({"ok": False, "error": str(ex)}, status_code=500)
    return envoltura


async def _json(request):
    try:
        return await request.json()
    except Exception:
        return {}


# ---------------------------------------------------------------------------
async def salud(request):
    import asyncio
    try:
        await asyncio.wait_for(run_in_threadpool(db.asegurar), timeout=15)
        return JSONResponse({"ok": True, "servicio": "playbar-api", "hora": ps.ahora_local_txt()})
    except Exception as ex:
        print(f"❌ API salud: {type(ex).__name__}: {ex}")
        try:
            diag = await asyncio.wait_for(run_in_threadpool(db.diagnostico), timeout=12)
        except Exception as ex2:
            diag = {"conexion": f"{type(ex2).__name__}: {ex2}"}
        print(f"🩺 Diagnóstico base: {diag}")
        return JSONResponse({"ok": False, "error": f"{type(ex).__name__}: {ex}",
                             "diagnostico": diag}, status_code=503)


@_protegido
def config(request, cli, cuerpo):
    return JSONResponse({"ok": True, "codigo": cli["codigo"], "nombre": cli["nombre"],
                         "playlist": cli["playlist"], "logo": cli["logo"]})


@_protegido
def instantanea(request, cli, cuerpo):
    return JSONResponse({"ok": True, **cola.a_dict(cola.instantanea(cli["codigo"]))})


@_protegido
def aleatorio(request, cli, cuerpo):
    items = cola.aleatorio(cli["codigo"])
    if request.query_params.get("filtrar") == "1":
        # Reproductor del navegador: el filtro de géneros/artistas del admin se aplica aquí
        # (los reproductores instalados lo aplican ellos mismos). Si no queda ninguna, todas.
        from services import generos as G
        texto = (db.control(cli["codigo"]) or {}).get("generos", "")
        gen, art = G.lista(texto), G.artistas(texto)
        if gen or art:
            items = [i for i in items
                     if (gen and G.clasificar(i.titulo, i.canal) in gen)
                     or G.es_de_artistas(i.titulo, i.canal, art)] or items
    return JSONResponse({"ok": True, "items": [
        {"video_id": i.video_id, "titulo": i.titulo, "canal": i.canal} for i in items
    ]})


@_protegido
def marcar(request, cli, cuerpo):
    d = cuerpo
    cola.marcar(cli["codigo"], int(d["fila"]), estado2=d.get("estado2"), estado=d.get("estado"))
    return JSONResponse({"ok": True})


@_protegido
def estado(request, cli, cuerpo):
    d = cuerpo
    # Un solo reproductor por bar: si otro equipo tiene el control, este no publica y se
    # entera para mostrar "Se está usando en otro equipo · Usar aquí". Los reproductores
    # viejos (sin "instancia") siguen funcionando como antes.
    # Con varios televisores (clientes.televisores), solo el principal publica; los
    # espejos reciben lo que suena en el principal para seguirlo.
    if d.get("instancia"):
        r = db.reproductor(cli["codigo"], d["instancia"], d.get("equipo", ""),
                           espejo=bool(d.get("espejo")))
        if not r["activo"]:
            return JSONResponse({"ok": True, "activo": False, "equipo": r["equipo"]})
        if r["rol"] == "espejo":
            return JSONResponse({"ok": True, "activo": True, "rol": "espejo",
                                 "equipo": r["equipo"], "sigue": db.estado_principal(cli["codigo"])})
    video = d.get("video") if isinstance(d.get("video"), dict) else None
    cola.publicar_estado(cli["codigo"], d.get("estado", ""), d.get("actual", ""),
                         d.get("siguiente", ""), d.get("ack"), video)
    return JSONResponse({"ok": True, "activo": True, "rol": "principal"})


@_protegido
def reclamar(request, cli, cuerpo):
    """Al abrir el reproductor (o al tocar "Usar aquí", con forzar): ¿este equipo tiene el control?"""
    d = cuerpo
    if not d.get("instancia"):
        return JSONResponse({"ok": False, "error": "falta instancia"}, status_code=400)
    info = d.get("info") if isinstance(d.get("info"), dict) else None
    r = db.reproductor(cli["codigo"], d["instancia"], d.get("equipo", ""),
                       bool(d.get("forzar")), info, espejo=bool(d.get("espejo")))
    if r["rol"] == "espejo":
        r["sigue"] = db.estado_principal(cli["codigo"])
    return JSONResponse({"ok": True, **r})


@_protegido
def nube(request, cli, cuerpo):
    """Direcciones firmadas para bajar/subir una canción de la nube (R2).
    {"archivo": "<video_id>_<altura>.mp4"} -> {"activo", "get", "put"}."""
    from services import nube as N
    return JSONResponse({"ok": True, **N.direcciones(str((cuerpo or {}).get("archivo") or ""))})


@_protegido
def reordenar(request, cli, cuerpo):
    d = cuerpo
    cola.reordenar(cli["codigo"], [int(x) for x in d.get("filas", [])])
    return JSONResponse({"ok": True})


@_protegido
def suscripcion(request, cli, cuerpo):
    """El reproductor pregunta cada minuto si puede seguir sonando."""
    e = sus.estado(cli["codigo"], db.cliente(cli["codigo"]))
    e["url_pago"] = f"{pagos.base_publica(request)}/pago/elegir?t={sus.token_pago(cli)}"
    return JSONResponse({"ok": True, **e})


@_protegido
def tabla(request, cli, cuerpo):
    dias = float(request.query_params.get("dias", "0") or 0)
    limite = min(int(request.query_params.get("limite", "1000") or 1000), 5000)
    desde = ps.inicio_jornada() - (dias - 1) * 86400 if dias > 0 else 0
    filas = db.tabla(cli["codigo"], desde, limite)
    return JSONResponse({"ok": True, "filas": filas, "total": db.contar_pedidos(cli["codigo"])})


async def descargar_excel(request):
    """Enlace temporal creado por el super admin en la app web."""
    return await run_in_threadpool(_excel, request)


def _excel(request):
    codigo = db.usar_descarga(request.query_params.get("t", ""))
    if not codigo:
        return Response("Enlace vencido. Vuelve a pedir la descarga desde el panel.", status_code=403)
    cli = db.cliente(codigo) or {"nombre": codigo}
    datos = exportar.excel_bytes(db.tabla(codigo, 0, 100000), cli["nombre"])
    nombre = f"pedidos_{cli['nombre']}_{time.strftime('%Y%m%d')}.xlsx".replace(" ", "_")
    return Response(datos, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})


# ---------------------------------------------------------------------------
# Copia para el servidor de respaldo (ver services/respaldo.py)
# ---------------------------------------------------------------------------
def _token_valido(request):
    import hmac
    t = request.headers.get("x-respaldo-token", "")
    return bool(respaldo.TOKEN) and bool(t) and hmac.compare_digest(t, respaldo.TOKEN)


async def respaldo_exportar(request):
    if not _token_valido(request):
        return JSONResponse({"error": "No autorizado"}, status_code=403)
    if respaldo.ES_RESPALDO:
        return JSONResponse({"error": "Este servidor es el respaldo"}, status_code=409)
    ruta = await run_in_threadpool(respaldo.exportar_a_archivo)
    from starlette.background import BackgroundTask
    from starlette.responses import FileResponse
    return FileResponse(ruta, media_type="application/zip", filename="playbar_respaldo.zip",
                        background=BackgroundTask(os.remove, ruta))


async def respaldo_estado(request):
    if not _token_valido(request):
        return JSONResponse({"error": "No autorizado"}, status_code=403)
    datos = {"rol": respaldo.ROL}
    if respaldo.ES_RESPALDO:
        datos.update(await run_in_threadpool(respaldo.leer_estado))
    return JSONResponse(datos)


async def respaldo_sincronizar(request):
    if not _token_valido(request):
        return JSONResponse({"error": "No autorizado"}, status_code=403)
    if not respaldo.ES_RESPALDO:
        return JSONResponse({"error": "Este servidor es el principal"}, status_code=409)
    return JSONResponse({"resultado": await run_in_threadpool(respaldo.sincronizar_una_vez)})


@asynccontextmanager
async def _vida(app):
    if respaldo.ES_RESPALDO:
        # En el respaldo no se revisan pagos (lo hace el principal); solo se copian sus datos.
        respaldo.iniciar_sincronizacion()
    else:
        pagos.iniciar_revisor()  # confirma solos los pagos pendientes de Wompi
    yield


app = Starlette(routes=[
    Route("/", salud),
    Route("/api/salud", salud),
    Route("/sistema/respaldo/exportar", respaldo_exportar),
    Route("/sistema/respaldo/estado", respaldo_estado),
    Route("/sistema/respaldo/sincronizar", respaldo_sincronizar, methods=["POST"]),
    Route("/api/v1/config", config),
    Route("/api/v1/instantanea", instantanea),
    Route("/api/v1/aleatorio", aleatorio),
    Route("/api/v1/marcar", marcar, methods=["POST"]),
    Route("/api/v1/estado", estado, methods=["POST"]),
    Route("/api/v1/reclamar", reclamar, methods=["POST"]),
    Route("/api/v1/reordenar", reordenar, methods=["POST"]),
    Route("/api/v1/nube", nube, methods=["POST"]),
    Route("/api/v1/tabla", tabla),
    Route("/api/v1/excel", descargar_excel),
    Route("/api/v1/suscripcion", suscripcion),
    *pagos.RUTAS,
], lifespan=_vida)
app.add_middleware(GZipMiddleware, minimum_size=1000)
# El reproductor del navegador (play.alnovix.com/pantalla, para TV Samsung/LG sin Android)
# llama a esta API desde la página. PANTALLA_ORIGENES (opcional): dominios permitidos.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv(
        "PANTALLA_ORIGENES", "https://play.alnovix.com").split(",") if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["X-Llave", "Content-Type"],
    max_age=86400,
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")
