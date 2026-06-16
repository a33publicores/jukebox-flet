import flet as ft
import views.codigo as codigo


def main(page: ft.Page):

    page.title = "PlayBar GO"

    page.window_width = 450
    page.window_height = 850

    codigo.codigo_view(page)


ft.app(
    target=main,
    assets_dir="assets"
)
