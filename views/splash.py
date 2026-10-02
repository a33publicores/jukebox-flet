import time
import flet as ft


def splash_view(page):
    page.clean()
    page.bgcolor = "#020617"

    logo = ft.Image(
        src="/logo.png",
        width=260,
        fit=ft.ImageFit.CONTAIN,
    )

    page.add(
        ft.Column(
            controls=[logo],
            alignment=ft.MainAxisAlignment.CENTER,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            expand=True,
        )
    )

    page.update()

    time.sleep(0.25)
    logo.width = 300
    page.update()

    time.sleep(0.25)
    logo.width = 280
    page.update()

    time.sleep(0.8)

    from views.codigo import codigo_view

    codigo_view(page)
