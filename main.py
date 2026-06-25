import flet as ft

from views.splash import splash_view
from views.jukebox import jukebox_view


def main(page: ft.Page):

    page.title = "PlayBar GO"

    page.window_width = 450
    page.window_height = 850

    # Verificar si existe una sesión guardada
    if page.session.store.contains_key("codigo"):

        codigo = page.session.store.get("codigo")

        jukebox_view(
            page,
            codigo,
            page.session.store.get("cliente"),
            page.session.store.get("telefono"),
            page.session.store.get("logo")
        )

        return

    splash_view(page)


ft.run(
    main,
    assets_dir="assets"
)
