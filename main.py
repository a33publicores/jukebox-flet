import asyncio

import flet as ft

from services.playbar_service import iniciar_procesador
from services.session_manager import cargar_sesion, estado, preparar_prefs
from views.splash import splash_view
from web_boot import preparar_index_web

BUILD = "flet-musica-karaoke-v8-splash"


async def main(page: ft.Page):
    page.title = "PlayBar GO"

    print(f"🚀 PlayBar GO build {BUILD} iniciado")
    iniciar_procesador()

    # La sesión se consulta mientras se muestra el splash.
    # Así el usuario siempre ve el arranque de PlayBar GO, incluso
    # cuando existe una sesión restaurable.
    # Entrada directa del super administrador:  https://<app>/super
    if str(getattr(page, "route", "") or "").rstrip("/").endswith("/super"):
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

    if session:
        page.title = "PlayBar GO"
        try:
            modo = session.get("modo", "musica")
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

ft.run(main, assets_dir="assets")
