"""
Servidor web de PlayBar GO: la app Flet de siempre + la portada pública.

    play.alnovix.com/            portada (HTML liviano: carga al instante, sin Flet)
    play.alnovix.com/admin       panel del administrador      (app Flet)
    play.alnovix.com/comprar     compra del plan y registro   (app Flet)
    play.alnovix.com/bar/1234    clientes del bar 1234        (app Flet)
    cualquier-dominio/inicio     la portada en cualquier dominio (para revisarla)
    /portada/...                 imágenes y videos de la portada

En los demás dominios (jukebox-flet-production.up.railway.app, el de los QR ya impresos)
la raíz sigue abriendo "Ingresa el código del lugar", igual que antes.

PORTADA_HOSTS (variable de Railway, opcional): dominios donde "/" muestra la portada,
separados por coma. Por defecto: play.alnovix.com
"""
import html
import os
import threading
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
CARPETA_PORTADA = AQUI / "portada"
PLANTILLA = CARPETA_PORTADA / "index.html"
WHATSAPP = "573016130044"
CACHE_SEG = 60

_cache = {"html": None, "hasta": 0.0}
_lock = threading.Lock()


def hosts_portada():
    valor = os.getenv("PORTADA_HOSTS", "play.alnovix.com")
    return {h.strip().lower() for h in valor.split(",") if h.strip()}


def _host(scope):
    for nombre, valor in scope.get("headers") or []:
        if nombre == b"x-forwarded-host":
            return valor.decode("latin-1").split(",")[0].strip().lower()
    for nombre, valor in scope.get("headers") or []:
        if nombre == b"host":
            return valor.decode("latin-1").strip().lower()
    return ""


def _es_dominio_portada(scope):
    host = _host(scope)
    hosts = hosts_portada()
    return "*" in hosts or host in hosts or host.split(":")[0] in hosts


def _pesos(n):
    return "$" + f"{int(n):,}".replace(",", ".")


def _tarjetas_planes():
    """Los planes reales de la base (los mismos de "Mi plan"). Sin base: aviso por WhatsApp."""
    try:
        from services import suscripcion as sus
        planes = [p for p in sus.planes() if not (p.get("solo_para") or "").strip()]
    except Exception as ex:
        print("⚠️ portada: no se pudieron leer los planes:", ex)
        planes = []
    if not planes:
        return ('<div class="plan"><p class="plan-nombre">Planes</p>'
                '<p class="plan-dias">Escríbenos y te contamos el precio para tu bar.</p></div>')
    tarjetas = []
    for i, p in enumerate(planes):
        dias = int(p.get("dias") or 30)
        periodo = "al mes" if dias in (30, 31) else ("al año" if dias in (365, 366) else f"por {dias} días")
        clase = "plan destacado" if i == len(planes) - 1 and len(planes) > 1 else "plan"
        tarjetas.append(
            f'<div class="{clase}"><p class="plan-nombre">{html.escape(p["nombre"])}</p>'
            f'<p class="plan-precio">{_pesos(p["precio"])}</p>'
            f'<p class="plan-dias">{periodo}, por bar · música sin límite</p>'
            f'<a class="boton boton-cian" href="/comprar?plan={int(p["id"])}">Comprar</a></div>')
    return "\n".join(tarjetas)


def html_portada():
    with _lock:
        if _cache["html"] and time.time() < _cache["hasta"]:
            return _cache["html"]
    texto = PLANTILLA.read_text("utf-8").replace("<!--PLANES-->", _tarjetas_planes())
    with _lock:
        _cache.update(html=texto, hasta=time.time() + CACHE_SEG)
    return texto


async def _enviar_html(send, cuerpo, estado=200):
    datos = cuerpo.encode("utf-8")
    await send({"type": "http.response.start", "status": estado, "headers": [
        (b"content-type", b"text/html; charset=utf-8"),
        (b"content-length", str(len(datos)).encode()),
        (b"cache-control", b"public, max-age=60"),
    ]})
    await send({"type": "http.response.body", "body": datos})


def crear_app(flet_app):
    """Envuelve la app ASGI de Flet: la portada y sus archivos van aparte, todo lo demás
    (la app, sus rutas /admin, /comprar, /bar/..., /super y el websocket) sigue en Flet."""
    from starlette.applications import Starlette
    from starlette.concurrency import run_in_threadpool
    from starlette.routing import Mount
    from starlette.staticfiles import StaticFiles

    estaticos = Starlette(routes=[Mount("/portada", StaticFiles(directory=str(CARPETA_PORTADA)))])

    async def app(scope, receive, send):
        if scope["type"] == "http" and scope.get("method") in ("GET", "HEAD"):
            ruta = scope.get("path") or "/"
            if ruta.startswith("/portada/"):
                await estaticos(scope, receive, send)
                return
            if ruta == "/inicio" or (ruta == "/" and _es_dominio_portada(scope)):
                await _enviar_html(send, await run_in_threadpool(html_portada))
                return
        await flet_app(scope, receive, send)

    return app


def iniciar(main):
    """Igual que ft.run(main, assets_dir="assets"), pero en el servidor web le suma la portada."""
    import flet as ft
    from flet.utils import get_bool_env_var, is_linux_server

    if not (get_bool_env_var("FLET_FORCE_WEB_SERVER") or is_linux_server()):
        ft.run(main, assets_dir="assets")  # app de escritorio / pruebas: como siempre
        return

    import uvicorn

    flet_app = ft.run(main, assets_dir="assets", export_asgi_app=True)
    puerto = int(os.getenv("FLET_SERVER_PORT") or 8000)
    host = os.getenv("FLET_SERVER_IP") or "0.0.0.0"
    print(f"🌐 PlayBar GO web en el puerto {puerto} · portada en: {', '.join(sorted(hosts_portada()))}")
    uvicorn.run(crear_app(flet_app), host=host, port=puerto, ws="websockets-sansio",
                proxy_headers=True, forwarded_allow_ips="*")
