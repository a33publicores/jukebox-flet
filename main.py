import json
import os
import flet as ft
import views.codigo as codigo
from views.jukebox import jukebox_view


def main(page: ft.Page):

    page.title = "PlayBar GO"

    page.window_width = 450
    page.window_height = 850

    if os.path.exists("data/session.json"):

        try:

            with open(
                "data/session.json",
                "r",
                encoding="utf-8"
            ) as f:

                session = json.load(f)

            jukebox_view(
                page,
                session["codigo"],
                session["cliente"],
                session["telefono"],
                session["logo"]
            )

            return

        except:
            pass

    codigo.codigo_view(page)


ft.run(
    main,
    assets_dir="assets"
)
