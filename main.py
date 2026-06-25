import flet as ft

from views.splash import splash_view
from views.jukebox import jukebox_view


def main(page: ft.Page):

    page.title = "PlayBar GO"

    page.window_width = 450
    page.window_height = 850
    
    print(dir(page))
    
    print(type(page.shared_preferences))
    print(dir(page.shared_preferences))

    # Verificar si existe una sesión guardada
    if page.session.store.contains_key("codigo"):

        codigo = page.shared_preferences.get("codigo")

        if codigo:

            jukebox_view(
                page,
                codigo,
                page.shared_preferences.get("cliente"),
                page.shared_preferences.get("telefono"),
                page.shared_preferences.get("logo")
            )

            return

        splash_view(page)


ft.run(
    main,
    assets_dir="assets"
)
