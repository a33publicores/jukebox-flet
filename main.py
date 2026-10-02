import asyncio

import flet as ft

from services.session_manager import cargar_sesion, estado
from views.splash import splash_view

# Etiqueta de versión: aparece en el título de la pestaña del navegador para
# confirmar que Railway está sirviendo este código.
BUILD = "sesion-v3"


def _abrir_jukebox(page, session):
    from views.jukebox import jukebox_view

    jukebox_view(
        page,
        session["codigo"],
        session.get("cliente", ""),
        session["telefono"],
        session.get("logo", ""),
    )


async def main(page: ft.Page):

    page.title = f"PlayBar GO [{BUILD}]"

    page.window_width = 450
    page.window_height = 850

    print(f"🚀 PlayBarGo build {BUILD} iniciado")

    # La sesión se guarda en el dispositivo (no en el servidor), por eso
    # sobrevive a F5, cerrar la app o cambiar de app.
    session = await cargar_sesion(page)

    if session:
        page.title = f"PlayBar GO [{BUILD}] sesión restaurada"
        try:
            await asyncio.to_thread(_abrir_jukebox, page, session)
            return
        except Exception as ex:
            print(f"⚠️ Error restaurando sesión: {ex}")

    if estado["error"]:
        page.title = f"PlayBar GO [{BUILD}] error almacenamiento"
    else:
        page.title = f"PlayBar GO [{BUILD}] sin sesión"

    await asyncio.to_thread(splash_view, page)


ft.run(
    main,
    assets_dir="assets"
)
