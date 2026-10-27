"""
Servidor web de PlayBar GO: la app Flet de siempre + la portada pública.

    play.alnovix.com/            portada (HTML liviano: carga al instante, sin Flet)
    play.alnovix.com/admin       panel del administrador      (app Flet)
    play.alnovix.com/comprar     compra del plan y registro   (app Flet)
    play.alnovix.com/bar/1234    clientes del bar 1234        (app Flet)
    cualquier-dominio/inicio     la portada en cualquier dominio (para revisarla)
    /portada/...                 imágenes y videos de la portada
    play.alnovix.com/pantalla    reproductor en el navegador del TV (Samsung, LG... sin Android)
    play.alnovix.com/tv          baja el APK; desde un TV Samsung/LG abre /pantalla

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
# play.alnovix.com/tv (o /apk): dirección corta para bajar el reproductor del TV con la app
# Downloader. DOWNLOADER_CODIGO (variable de Railway, opcional): el número registrado en
# Downloader (aftv.news) que apunta a esa dirección; se muestra en la portada.
APK_TV_URL = os.getenv("TV_APK_URL",
                       "https://github.com/a33publicores/jukebox-flet/releases/download/tv-apk/PlayBarGO_TV.apk")
RUTAS_APK = ("/tv", "/apk", "/tv/", "/apk/")
RUTAS_PANTALLA = ("/pantalla", "/pantalla/")
PANTALLA = CARPETA_PORTADA / "pantalla.html"
# Navegadores de TV que no instalan apps de Android (Samsung Tizen, LG webOS...).
TV_SIN_ANDROID = ("tizen", "web0s", "webos", "smart-tv", "smarttv", "netcast", "hbbtv")


def _agente(scope):
    for nombre, valor in scope.get("headers") or []:
        if nombre == b"user-agent":
            return valor.decode("latin-1").lower()
    return ""


def _es_tv_sin_android(scope):
    ua = _agente(scope)
    return "android" not in ua and any(m in ua for m in TV_SIN_ANDROID)


async def _redirigir(send, destino):
    await send({"type": "http.response.start", "status": 302, "headers": [
        (b"location", destino.encode()),
        (b"cache-control", b"no-store"),
        (b"content-length", b"0"),
    ]})
    await send({"type": "http.response.body", "body": b""})

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


def _promo(p):
    return bool(int(p.get("promo_precio") or 0) and int(p.get("promo_pagos") or 0)
                and int(p["promo_precio"]) < int(p["precio"]))


def _meses(p):
    n = int(p.get("promo_pagos") or 0)
    return "el primer mes" if n == 1 else f"los primeros {n} meses"


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
            f'<p class="plan-precio">{_pesos(p["promo_precio"] if _promo(p) else p["precio"])}</p>'
            f'<p class="plan-dias">{periodo}, por bar · música sin límite</p>'
            + (f'<p class="plan-promo">🔥 Promoción: {_meses(p)} a {_pesos(p["promo_precio"])}, '
               f'luego {_pesos(p["precio"])} {periodo}</p>' if _promo(p) else "")
            + f'<a class="boton boton-cian" href="/comprar?plan={int(p["id"])}">Comprar</a></div>')
    return "\n".join(tarjetas)


def _paso_downloader():
    codigo = html.escape(os.getenv("DOWNLOADER_CODIGO", "1878480").strip())  # aftv.news/1878480
    if codigo:
        return (f'escribe el código <span class="codigo">{codigo}</span> '
                f'(o la dirección <span class="codigo">play.alnovix.com/tv</span>)')
    return 'escribe la dirección <span class="codigo">play.alnovix.com/tv</span>'


def html_portada():
    with _lock:
        if _cache["html"] and time.time() < _cache["hasta"]:
            return _cache["html"]
    texto = PLANTILLA.read_text("utf-8").replace("<!--PLANES-->", _tarjetas_planes())
    texto = texto.replace("<!--DOWNLOADER-->", _paso_downloader())
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
            if ruta in RUTAS_APK:  # el TV baja el instalador (Downloader o navegador)
                # Un TV Samsung/LG no instala el APK: se le abre el reproductor del navegador.
                await _redirigir(send, "/pantalla" if _es_tv_sin_android(scope) else APK_TV_URL)
                return
            if ruta in RUTAS_PANTALLA:
                await _enviar_html(send, await run_in_threadpool(PANTALLA.read_text, "utf-8"))
                return
            if ruta == "/inicio" or (ruta == "/" and _es_dominio_portada(scope)):
                await _enviar_html(send, await run_in_threadpool(html_portada))
                return
        if scope["type"] == "http" and scope.get("path") == "/assets/FontManifest.json":
            await _manifiesto_fuentes(flet_app, scope, receive, send)
            return
        if scope["type"] == "http" and (scope.get("path") or "").startswith(CACHE_LARGO):
            await flet_app(scope, receive, _con_cache(send))
            return
        await flet_app(scope, receive, send)

    return app


# Archivos pesados de Flet que solo cambian al cambiar la versión de Flet (fijada en
# requirements): el navegador los guarda 7 días en vez de volver a preguntar en cada visita.
CACHE_LARGO = ("/canvaskit/", "/assets/fonts/", "/assets/packages/", "/icons/")


async def _manifiesto_fuentes(flet_app, scope, receive, send):
    """La lista de fuentes de Flet sin las de fórmulas matemáticas (KaTeX): PlayBar no las
    usa y el navegador bajaba ~20 archivos de más antes de mostrar la app."""
    import json
    partes = {"inicio": None, "cuerpo": b""}

    async def guardar(mensaje):
        if mensaje["type"] == "http.response.start":
            partes["inicio"] = mensaje
        elif mensaje["type"] == "http.response.body":
            partes["cuerpo"] += mensaje.get("body", b"")

    alcance = {**scope, "headers": [(k, v) for k, v in scope.get("headers", [])
                                    if k.lower() not in (b"accept-encoding", b"if-none-match",
                                                         b"if-modified-since")]}
    await flet_app(alcance, receive, guardar)
    cuerpo = partes["cuerpo"]
    try:
        fuentes = [f for f in json.loads(cuerpo) if "KaTeX" not in str(f.get("family", ""))]
        cuerpo = json.dumps(fuentes).encode()
    except Exception:
        pass  # si no se entiende, se manda tal cual
    estado = (partes["inicio"] or {}).get("status", 200)
    await send({"type": "http.response.start", "status": estado, "headers": [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(cuerpo)).encode()),
        (b"cache-control", b"public, max-age=3600"),
    ]})
    await send({"type": "http.response.body", "body": cuerpo})


def _con_cache(send):
    async def enviar(mensaje):
        if mensaje.get("type") == "http.response.start" and mensaje.get("status") == 200:
            cabeceras = [(k, v) for k, v in mensaje.get("headers", []) if k.lower() != b"cache-control"]
            cabeceras.append((b"cache-control", b"public, max-age=604800"))
            mensaje = {**mensaje, "headers": cabeceras}
        await send(mensaje)
    return enviar


def iniciar(main):
    """Igual que ft.run(main, assets_dir="assets"), pero en el servidor web le suma la portada."""
    import flet as ft
    from flet.utils import get_bool_env_var, is_linux_server

    if not (get_bool_env_var("FLET_FORCE_WEB_SERVER") or is_linux_server()):
        ft.run(main, assets_dir="assets")  # app de escritorio / pruebas: como siempre
        return

    import uvicorn

    flet_app = ft.run(main, assets_dir="assets", export_asgi_app=True)
    from services import flet_seguro
    flet_seguro.aplicar()  # que una respuesta tardía no congele la pestaña
    puerto = int(os.getenv("FLET_SERVER_PORT") or 8000)
    host = os.getenv("FLET_SERVER_IP") or "0.0.0.0"
    print(f"🌐 PlayBar GO web en el puerto {puerto} · portada en: {', '.join(sorted(hosts_portada()))}")
    uvicorn.run(crear_app(flet_app), host=host, port=puerto, ws="websockets-sansio",
                proxy_headers=True, forwarded_allow_ips="*")
