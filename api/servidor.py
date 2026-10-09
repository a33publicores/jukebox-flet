"""
API de PlayBar GO para los reproductores de los bares (servicio aparte en Railway).

Cada reproductor se identifica con la LLAVE de su negocio (encabezado X-Llave).
La contraseña de la base de datos nunca sale de Railway; si un PC se pierde, el super
administrador regenera la llave de ese negocio y la vieja deja de servir.

Arranque en Railway:   python -m api.servidor      (usa la variable PORT)
"""
import os
import time

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.gzip import GZipMiddleware
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from services import cola, db, exportar
from services import playbar_service as ps

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
        return JSONResponse({"ok": False, "error": f"{type(ex).__name__}: {ex}"}, status_code=503)


@_protegido
def config(request, cli, cuerpo):
    return JSONResponse({"ok": True, "codigo": cli["codigo"], "nombre": cli["nombre"],
                         "playlist": cli["playlist"], "logo": cli["logo"]})


@_protegido
def instantanea(request, cli, cuerpo):
    return JSONResponse({"ok": True, **cola.a_dict(cola.instantanea(cli["codigo"]))})


@_protegido
def aleatorio(request, cli, cuerpo):
    return JSONResponse({"ok": True, "items": [
        {"video_id": i.video_id, "titulo": i.titulo, "canal": i.canal}
        for i in cola.aleatorio(cli["codigo"])
    ]})


@_protegido
def marcar(request, cli, cuerpo):
    d = cuerpo
    cola.marcar(cli["codigo"], int(d["fila"]), estado2=d.get("estado2"), estado=d.get("estado"))
    return JSONResponse({"ok": True})


@_protegido
def estado(request, cli, cuerpo):
    d = cuerpo
    cola.publicar_estado(cli["codigo"], d.get("estado", ""), d.get("actual", ""),
                         d.get("siguiente", ""), d.get("ack"))
    return JSONResponse({"ok": True})


@_protegido
def reordenar(request, cli, cuerpo):
    d = cuerpo
    cola.reordenar(cli["codigo"], [int(x) for x in d.get("filas", [])])
    return JSONResponse({"ok": True})


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


app = Starlette(routes=[
    Route("/", salud),
    Route("/api/salud", salud),
    Route("/api/v1/config", config),
    Route("/api/v1/instantanea", instantanea),
    Route("/api/v1/aleatorio", aleatorio),
    Route("/api/v1/marcar", marcar, methods=["POST"]),
    Route("/api/v1/estado", estado, methods=["POST"]),
    Route("/api/v1/reordenar", reordenar, methods=["POST"]),
    Route("/api/v1/tabla", tabla),
    Route("/api/v1/excel", descargar_excel),
])
app.add_middleware(GZipMiddleware, minimum_size=1000)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="info")
