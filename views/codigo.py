import flet as ft
import os
from services.api_client import APIClient
from views.bienvenida import bienvenida_view
import time

def codigo_view(page: ft.Page):

    page.clean()

    page.bgcolor = "#020617"

    page.horizontal_alignment = (
        ft.CrossAxisAlignment.CENTER
    )

    page.vertical_alignment = (
        ft.MainAxisAlignment.CENTER
    )

    logo = ft.Image(
        src="/logo.png",
        width=220,
        height=220
    )

    titulo = ft.Text(
        "Ingresa el código del lugar",
        size=26,
        weight=ft.FontWeight.BOLD,
        color="#22d3ee",
        text_align=ft.TextAlign.CENTER
    )

    subtitulo = ft.Text(
        "Conéctate y controla la música",
        size=16,
        color="#94A3B8",
        text_align=ft.TextAlign.CENTER
    )

    codigo = ft.TextField(
        width=350,
        height=60,
        text_align=ft.TextAlign.CENTER,
        border_radius=15,
        bgcolor="#1A1A1A",
        color="white",
        border_color="#00D4FF",
        focused_border_color="#B44CFF",
        keyboard_type=ft.KeyboardType.NUMBER,
        input_filter=ft.NumbersOnlyInputFilter(),
        hint_text="Código del lugar",
        hint_style=ft.TextStyle(
            color="#94A3B8"
        )
    )
    
    def validar(e):

        codigo_local = codigo.value.strip()

        if not codigo_local:
            page.snack_bar = ft.SnackBar(
                content=ft.Text("Ingresa un código")
            )

            page.snack_bar.open = True

            page.update()
            return

        try:

            respuesta = APIClient.validar_cliente(
                codigo_local
            )

            if respuesta.get("ok"):

                bienvenida_view(
                    page,
                    codigo_local,
                    respuesta["nombre"],
                    respuesta["logo"]
                )

            else:

                page.snack_bar = ft.SnackBar(
                    content=ft.Text(
                        "Código inválido"
                    )
                )

                page.snack_bar.open = True

            page.update()

            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    f"Cliente: {respuesta}"
                )
            )

            page.snack_bar.open = True

            page.update()

        except Exception as ex:

            page.snack_bar = ft.SnackBar(
                content=ft.Text(
                    f"Error: {ex}"
                )
            )

            page.snack_bar.open = True

            page.update()

    btn_entrar = ft.Container(
        width=250,
        height=55,
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
                "ENTRAR",
                color="white",
                weight=ft.FontWeight.BOLD,
                size=16
            ),
            on_click=validar
        )
    )

    page.add(
        logo,
        ft.Container(height=20),
        titulo,
        ft.Container(height=8),
        subtitulo,
        ft.Container(height=25),
        codigo,
        ft.Container(height=25),
        btn_entrar
    )

    page.update()
    
