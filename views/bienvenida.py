import flet as ft


def bienvenida_view(page, codigo, nombre, logo):
    page.clean()
    page.bgcolor = "#020617"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    logo_local = ft.Image(
        src=f"logos/{logo}",
        width=220,
        height=220,
    )

    titulo = ft.Text(
        nombre,
        size=35,
        color="white",
        weight=ft.FontWeight.BOLD,
        text_align=ft.TextAlign.CENTER,
    )

    subtitulo = ft.Text(
        "¿Qué deseas hacer?",
        size=24,
        color="#22d3ee",
        weight=ft.FontWeight.BOLD,
        text_align=ft.TextAlign.CENTER,
    )

    def continuar(e):
        from views.seleccionar_modo import seleccionar_modo_view
        seleccionar_modo_view(page, codigo, nombre, logo)

    btn = ft.Container(
        width=240,
        height=58,
        border_radius=18,
        gradient=ft.LinearGradient(colors=["#00D4FF", "#B44CFF"]),
        shadow=ft.BoxShadow(blur_radius=25, color="#00D4FF66", spread_radius=1),
        content=ft.TextButton(
            content=ft.Text(
                "CONTINUAR",
                color="white",
                weight=ft.FontWeight.BOLD,
                size=16,
            ),
            on_click=continuar,
        ),
    )

    page.add(
        logo_local,
        ft.Container(height=20),
        titulo,
        ft.Container(height=15),
        subtitulo,
        ft.Container(height=25),
        btn,
    )
    page.update()
