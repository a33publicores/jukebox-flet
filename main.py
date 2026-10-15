import asyncio
import urllib.parse

import flet as ft

from services.playbar_service import iniciar_procesador
from services.session_manager import cargar_sesion, estado, preparar_prefs
from servidor_web import iniciar
from views.splash import splash_view
from web_boot import preparar_index_web

BUILD = "flet-musica-karaoke-v9-portada"


def _ruta(page):
    """('/bar/1234', {'plan': ['3']}) a partir de page.route."""
    partes = urllib.parse.urlsplit(str(getattr(page, "route", "") or "/"))
    return "/" + partes.path.strip("/").lower(), urllib.parse.parse_qs(partes.query)


async def main(page: ft.Page):
    page.title = "PlayBar GO"

    print(f"🚀 PlayBar GO build {BUILD} iniciado")
    iniciar_procesador()

    # La sesión se consulta mientras se muestra el splash.
    # Así el usuario siempre ve el arranque de PlayBar GO, incluso
    # cuando existe una sesión restaurable.
    # Entrada directa del super administrador:  https://<app>/super
    ruta, consulta = _ruta(page)
    if ruta.endswith("/super"):
        from views.super_admin import super_login_view
        await asyncio.to_thread(super_login_view, page)
        return

    preparar_prefs(page)
    session_task = asyncio.create_task(cargar_sesion(page))

    try:
        await splash_view(page)
    except Exception as ex:
        # El splash nunca debe impedir que arranque la aplicación.
        print(f"⚠️ Error en splash visual: {ex}")

    session = await session_task

    # Direcciones que abre la portada (play.alnovix.com): el panel del administrador,
    # la compra y el bar de un QR (/bar/1234).
    if ruta == "/admin":
        from views.acceso import abrir_desde_ruta
        await abrir_desde_ruta(page, session)
        return
    if ruta == "/comprar":
        from views.comprar import comprar_view
        await asyncio.to_thread(comprar_view, page, (consulta.get("plan") or [None])[0])
        return
    codigo_bar = ruta[len("/bar/"):] if ruta.startswith("/bar/") else ""
    if codigo_bar and session and str(session.get("codigo")) != codigo_bar:
        session = None  # la sesión guardada es de otro bar: manda el QR que escaneó
    if codigo_bar and not session:
        from services.playbar_service import validar_cliente
        datos = await asyncio.to_thread(validar_cliente, codigo_bar)
        if datos.get("ok"):
            from views.seleccionar_modo import seleccionar_modo_view
            await asyncio.to_thread(seleccionar_modo_view, page, codigo_bar,
                                    datos["nombre"], datos["logo"])
            return

    if session:
        page.title = "PlayBar GO"
        try:
            modo = session.get("modo", "musica")
            rol = session.get("rol", "usuario")
            if rol == "super":
                from views import super_admin

                super_admin._sesiones_super.add(id(page))
                await asyncio.to_thread(super_admin.super_inicio, page)
                return
            if rol == "admin" and modo == "admin":
                from views.admin import admin_view

                await asyncio.to_thread(admin_view, page, session["codigo"],
                                        session.get("cliente", ""), session.get("logo", ""))
                return
            if rol == "admin":  # el admin estaba en "Colocar música"
                from views.jukebox import jukebox_view

                await asyncio.to_thread(jukebox_view, page, session["codigo"],
                                        session.get("cliente", ""), "ADMIN",
                                        session.get("logo", ""), True)
                return
            if modo == "karaoke":
                from views.karaoke import karaoke_view

                await asyncio.to_thread(
                    karaoke_view,
                    page,
                    session["codigo"],
                    session.get("cliente", ""),
                    session["telefono"],
                    session.get("logo", ""),
                )
            else:
                from views.jukebox import jukebox_view

                await asyncio.to_thread(
                    jukebox_view,
                    page,
                    session["codigo"],
                    session.get("cliente", ""),
                    session["telefono"],
                    session.get("logo", ""),
                )
            return
        except Exception as ex:
            print(f"⚠️ Error restaurando sesión: {ex}")

    page.title = "PlayBar GO"

    from views.codigo import codigo_view

    await asyncio.to_thread(codigo_view, page)


# Genera assets/index.html con el splash/favicon de PlayBar GO (solo web).
preparar_index_web()

# Como ft.run(main, assets_dir="assets"); en el servidor web le suma la portada
# de play.alnovix.com (ver servidor_web.py).
iniciar(main)
