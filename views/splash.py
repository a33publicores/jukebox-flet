import flet as ft
import time

def splash_view(page):

    page.clean()

    page.bgcolor = "#020617"

    logo = ft.Image(
        src="splash.png",
        width=120
    )

    page.add(
        ft.Column(
            controls=[logo],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True
        )
    )

    page.update()

    # Animación manual
    time.sleep(0.2)
    logo.width = 180
    page.update()

    time.sleep(0.2)
    logo.width = 260
    page.update()

    time.sleep(0.2)
    logo.width = 220
    page.update()

    time.sleep(1)

    from views.codigo import codigo_view

    codigo_view(page)
