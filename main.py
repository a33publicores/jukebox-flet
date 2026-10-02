import asyncio

import flet as ft

from services.playbar_service import iniciar_procesador
from services.session_manager import cargar_sesion, estado
from views.splash import splash_view

BUILD = "flet-musica-karaoke-v4"


async def main(page: ft.Page):
    page.title = f"PlayBar GO [{BUILD}]"
    page.window_width = 450
    page.window_height = 850

    print(f"🚀 PlayBar GO build {BUILD} iniciado")
    iniciar_procesador()

    session = await cargar_sesion(page)

    if session:
        page.title = f"PlayBar GO [{BUILD}] sesión restaurada"
        try:
            modo = session.get("modo", "musica")
            if modo == "karaoke":
                from views.karaoke import karaoke_view
                await asyncio.to_thread(
                    karaoke_view, page,
                    session["codigo"],
                    session.get("cliente", ""),
                    session["telefono"],
                    session.get("logo", ""),
                )
            else:
                from views.jukebox import jukebox_view
                await asyncio.to_thread(
                    jukebox_view, page,
                    session["codigo"],
                    session.get("cliente", ""),
                    session["telefono"],
                    session.get("logo", ""),
                )
            return
        except Exception as ex:
            print(f"⚠️ Error restaurando sesión: {ex}")

    page.title = (
        f"PlayBar GO [{BUILD}] error almacenamiento"
        if estado["error"]
        else f"PlayBar GO [{BUILD}] sin sesión"
    )
    await asyncio.to_thread(splash_view, page)


ft.run(main, assets_dir="assets")
