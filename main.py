import json
import os
import flet as ft

from views.splash import splash_view
from views.jukebox import jukebox_view


def main(page: ft.Page):

    page.title = "PlayBar GO"

    page.window_width = 450
    page.window_height = 850

    codigo = page.session.get("codigo")

    if codigo:

        jukebox_view(
            page,
            codigo,
            page.session.get("cliente"),
            page.session.get("telefono"),
            page.session.get("logo")
        )

        return

    splash_view(page)


ft.run(
    main,
    assets_dir="assets"
)
