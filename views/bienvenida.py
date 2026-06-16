import flet as ft


def bienvenida_view(
    page,
    codigo,
    nombre,
    logo
):

    page.clean()

    page.bgcolor = "#020617"

    page.horizontal_alignment = (
        ft.CrossAxisAlignment.CENTER
    )

    logo_local = ft.Image(
    src=logo,
    width=250,
    height=250,
    fit=ft.ImageFit.CONTAIN
    )

    titulo = ft.Text(
        nombre,
        size=35,
        color="white",
        weight=ft.FontWeight.BOLD
    )

    subtitulo = ft.Text(
        "🎵 Tú eliges la música 🎵",
        size=22,
        color="#22d3ee",
        text_align=ft.TextAlign.CENTER
    )

    def continuar(e):

        from views.login import login_view

        login_view(
            page,
            codigo,
            nombre,
            logo
        )

    btn = ft.Container(
        width=220,
        height=60,
        border_radius=18,
        gradient=ft.LinearGradient(
            colors=[
                "#00D4FF",
                "#B44CFF"
            ]
        ),
        shadow=ft.BoxShadow(
            blur_radius=25,
            color="#00D4FF66",
            spread_radius=1
        ),
        content=ft.TextButton(
            content=ft.Text(
                "CONTINUAR",
                color="white",
                weight=ft.FontWeight.BOLD,
                size=16
            ),
            on_click=continuar
        )
    )

    page.add(
        ft.Container(height=40),
        logo_local,
        titulo,
        subtitulo,
        ft.Container(height=30),
        btn
    )

    page.update()
