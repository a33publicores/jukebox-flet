import asyncio

import flet as ft

from backend_runner import iniciar_backend
from services.session_manager import cargar_sesion, estado
from views.splash import splash_view


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

    session = await cargar_sesion(page)

    if session:
        page.title = f"PlayBar GO [{BUILD}] sesión restaurada"

        try:
            await asyncio.to_thread(
                _abrir_jukebox,
                page,
                session
            )
            return

        except Exception as ex:
            print(
                f"⚠️ Error restaurando sesión: {ex}"
            )

    if estado["error"]:
        page.title = (
            f"PlayBar GO [{BUILD}] "
            f"error almacenamiento"
        )
    else:
        page.title = (
            f"PlayBar GO [{BUILD}] "
            f"sin sesión"
        )

    await asyncio.to_thread(
        splash_view,
        page
    )


# ============================================================
# BACKEND INTERNO
# ============================================================

print("🔧 Iniciando backend interno...")
iniciar_backend()


# ============================================================
# FLET
# ============================================================

ft.run(
    main,
    assets_dir="assets"
)