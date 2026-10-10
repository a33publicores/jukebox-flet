"""
Páginas de pago de PlayBar GO (servicio playbar-api), igual que ALNOVIX con Wompi:

    GET  /pago/elegir?t=...   planes del negocio (enlace sin contraseña del reproductor)
    POST /pago/crear          crea la orden PENDIENTE y lleva a Wompi
    GET  /pago/ir/{ref}       abre el Web Checkout de Wompi (firma hecha aquí)
    GET  /pago/resultado      Wompi vuelve aquí (?id=transacción): se confirma y se activa
    POST /wompi/webhook       eventos de Wompi (si la cuenta apunta aquí)

Además, cada minuto se revisan solas las órdenes pendientes (con la llave privada), así el
plan se activa aunque la persona cierre el navegador antes de volver.
"""
import html
import threading
import time

from starlette.concurrency import run_in_threadpool
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

from services import suscripcion as sus
from services import wompi

ESTADOS_FINALES = {"DECLINED": "RECHAZADO", "ERROR": "ERROR", "VOIDED": "ANULADO"}


def base_publica(request):
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    esquema = request.headers.get("x-forwarded-proto") or ("http" if host.startswith(("localhost", "127.")) else "https")
    return f"{esquema}://{host}"


def procesar(tx):
    """Aplica una transacción de Wompi a su orden. Devuelve (orden, estado_texto)."""
    o = sus.orden(tx.get("reference"))
    if not o:
        return None, "NO_ES_NUESTRA"
    if o["estado"] == "APROBADO":
        return o, "APROBADO"
    if not wompi.coincide(o, tx):
        print(f"⚠️ Wompi: la transacción {tx.get('id')} NO coincide con {o['referencia']}")
        return o, "NO_COINCIDE"
    st = tx.get("status")
    if st == "APPROVED":
        return sus.aplicar_aprobado(o["referencia"], tx.get("id")), "APROBADO"
    if st in ESTADOS_FINALES:
        sus.marcar_orden(o["referencia"], ESTADOS_FINALES[st], tx.get("id"))
        return sus.orden(o["referencia"]), ESTADOS_FINALES[st]
    return o, "PENDIENTE"


# ---------------------------------------------------------------------------
# Páginas (HTML sencillo con los colores de PlayBar GO)
# ---------------------------------------------------------------------------
def _pagina(titulo, cuerpo, color="#22d3ee"):
    return HTMLResponse(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PlayBar GO · {html.escape(titulo)}</title>
<style>
 body{{margin:0;background:#020617;color:#e2e8f0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
 .caja{{max-width:460px;margin:0 auto;padding:28px 16px}}
 h1{{color:{color};font-size:24px;margin:8px 0 4px}}
 .logo{{font-weight:800;letter-spacing:2px;color:#fff}} .logo span{{color:#B44CFF}}
 .tarjeta{{background:#0f172a;border:1px solid #1e293b;border-radius:16px;padding:16px;margin:14px 0}}
 .precio{{font-size:28px;font-weight:800;color:#fff}} .gris{{color:#94a3b8;font-size:14px}}
 button,.boton{{display:block;width:100%;box-sizing:border-box;border:0;border-radius:14px;padding:14px;
   margin-top:12px;font-size:17px;font-weight:700;color:#fff;text-align:center;text-decoration:none;
   background:linear-gradient(90deg,#00D4FF,#B44CFF);cursor:pointer}}
</style></head><body><div class="caja"><div class="logo">PLAYBAR <span>GO</span></div>
<h1>{html.escape(titulo)}</h1>{cuerpo}</div></body></html>""")


def _pesos(n):
    return "$" + f"{int(n):,}".replace(",", ".")


def _elegir(request):
    t = request.query_params.get("t", "")
    c = sus.cliente_de_token(t)
    if not c:
        return _pagina("Enlace no válido", "<p>Abre el pago desde el reproductor o el panel del bar.</p>", "#f87171")
    e = sus.estado(c["codigo"], c)
    tarjetas = "".join(f"""<div class="tarjeta"><div><b>{html.escape(p['nombre'])}</b></div>
<div class="precio">{_pesos(p['precio'])}</div><div class="gris">{p['dias']} días de música sin límite</div>
<form method="post" action="/pago/crear"><input type="hidden" name="t" value="{html.escape(t)}">
<input type="hidden" name="plan" value="{p['id']}"><button>Pagar con Wompi</button></form></div>"""
                       for p in sus.planes_para(c["codigo"]))
    return _pagina(f"Plan de {c['nombre']}", f"""<div class="tarjeta"><b>{html.escape(e['titulo'])}</b>
<div class="gris">{html.escape(e['mensaje'])}</div></div>{tarjetas or '<p>No hay planes disponibles.</p>'}
<p class="gris">Pagas con tarjeta, PSE, Nequi o Bancolombia en la página segura de Wompi.
El plan se activa solo apenas se apruebe el pago.</p>""")


async def elegir(request):
    return await run_in_threadpool(_elegir, request)


async def crear(request):
    # formulario simple (sin depender de python-multipart)
    from urllib.parse import parse_qs
    datos = parse_qs((await request.body()).decode("utf-8", "ignore"))
    form = {k: v[0] for k, v in datos.items() if v}

    def _crear():
        c = sus.cliente_de_token(form.get("t", ""))
        if not c:
            return _pagina("Enlace no válido", "<p>Vuelve a abrir el pago.</p>", "#f87171")
        try:
            o = sus.crear_orden(c["codigo"], int(form.get("plan", 0)))
        except Exception as ex:
            return _pagina("No se pudo crear el pago", f"<p>{html.escape(str(ex))}</p>", "#f87171")
        return RedirectResponse(f"/pago/ir/{o['referencia']}", status_code=303)
    return await run_in_threadpool(_crear)


async def ir(request):
    ref = request.path_params["ref"]

    def _ir():
        o = sus.orden(ref)
        if not o:
            return _pagina("Pago no encontrado", "<p>Vuelve a intentarlo desde PlayBar GO.</p>", "#f87171")
        if o["estado"] == "APROBADO":
            return _pagina("Este pago ya está aprobado ✅", "<p>Tu plan ya está activo.</p>")
        if o["estado"] != "PENDIENTE":
            return _pagina("Este pago ya se cerró", "<p>Crea uno nuevo desde PlayBar GO.</p>", "#facc15")
        if not wompi.configurado():
            return _pagina("Pagos no configurados", "<p>Falta configurar Wompi en el servidor.</p>", "#f87171")
        url = wompi.checkout_url(o["referencia"], o["monto"],
                                 redirect_url=f"{base_publica(request)}/pago/resultado")
        return RedirectResponse(url, status_code=303)
    return await run_in_threadpool(_ir)


async def resultado(request):
    tid = request.query_params.get("id", "")

    def _resultado():
        try:
            tx = wompi.consultar_transaccion(tid)
            o, est = procesar(tx)
        except Exception as ex:
            print("⚠️ resultado Wompi:", ex)
            return _pagina("Estamos confirmando tu pago",
                           "<p>Si se aprobó, tu plan se activará solo en unos minutos.</p>", "#facc15")
        if est == "APROBADO" and o:
            e = sus.estado(o["codigo"])
            return _pagina("¡Pago aprobado! ✅", f"""<div class="tarjeta"><b>{html.escape(o['plan_nombre'])}</b>
<div class="precio">{_pesos(o['monto'])}</div><div class="gris">{html.escape(e['mensaje'])}</div></div>
<p>La música ya quedó activa. Puedes cerrar esta página y volver a PlayBar GO.</p>
<p class="gris">Referencia {html.escape(o['referencia'])}</p>""")
        if est in ("RECHAZADO", "ERROR", "ANULADO"):
            return _pagina("El pago no se aprobó", "<p>No se hizo ningún cobro. Puedes intentarlo de nuevo "
                           "desde PlayBar GO con otro medio de pago.</p>", "#f87171")
        if est == "PENDIENTE":
            return _pagina("Pago en proceso ⏳", "<p>Wompi todavía lo está confirmando (PSE o Nequi pueden "
                           "tardar unos minutos). El plan se activa solo cuando se apruebe.</p>", "#facc15")
        return _pagina("No pudimos validar este pago", "<p>Escríbenos con la referencia del pago.</p>", "#f87171")
    return await run_in_threadpool(_resultado)


async def webhook(request):
    try:
        evento = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "JSON no válido"}, status_code=400)
    if not isinstance(evento, dict) or not wompi.ambiente_evento_ok(evento):
        return JSONResponse({"ok": False, "error": "evento no válido"}, status_code=400)
    if not wompi.firma_evento_valida(evento, request.headers.get("x-event-checksum")):
        return JSONResponse({"ok": False, "error": "firma inválida"}, status_code=401)
    tx = wompi.transaccion_de_evento(evento)
    if not tx:
        return JSONResponse({"ok": True, "procesado": False})
    o, est = await run_in_threadpool(procesar, tx)
    return JSONResponse({"ok": True, "procesado": bool(o), "estado": est})


# ---------------------------------------------------------------------------
# Revisión automática de pagos pendientes
# ---------------------------------------------------------------------------
def _revisar_pendientes():
    for o in sus.pendientes():
        try:
            for tx in wompi.buscar_por_referencia(o["referencia"]):
                _, est = procesar(tx)
                if est != "PENDIENTE":
                    break
        except Exception as ex:
            print(f"⚠️ revisando {o['referencia']}: {ex}")


def iniciar_revisor(intervalo=60):
    import os
    if not os.getenv("WOMPI_PRIVATE_KEY", "").strip():
        print("ℹ️ Sin WOMPI_PRIVATE_KEY: los pagos se confirman al volver de Wompi (o por webhook)")
        return

    def bucle():
        while True:
            time.sleep(intervalo)
            try:
                _revisar_pendientes()
            except Exception as ex:
                print("⚠️ revisor de pagos:", ex)
    threading.Thread(target=bucle, daemon=True).start()
    print(f"💳 Revisor de pagos Wompi activo ({wompi.ambiente()})")


RUTAS = [
    Route("/pago/elegir", elegir),
    Route("/pago/crear", crear, methods=["POST"]),
    Route("/pago/ir/{ref}", ir),
    Route("/pago/resultado", resultado),
    Route("/wompi/webhook", webhook, methods=["POST"]),
]
