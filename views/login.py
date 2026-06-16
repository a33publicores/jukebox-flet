import flet as ft
import json
import os

from views.jukebox import jukebox_view


def login_view(
    page,
    codigo,
    cliente,
    logo_url
):

    page.clean()

    page.bgcolor = "#020617"

    telefono = ft.TextField(
        label="Número telefónico",
        width=350,
        height=60,
        keyboard_type=ft.KeyboardType.PHONE,
        text_align=ft.TextAlign.CENTER,
        border_radius=15,
        bgcolor="#1A1A1A",

        color="white",

        border_color="#00D4FF",
        focused_border_color="#B44CFF",

        cursor_color="#00D4FF",

        text_style=ft.TextStyle(
            color="white",
            size=18,
            weight=ft.FontWeight.W_500
        ),

        label_style=ft.TextStyle(
            color="#94A3B8",
            size=14
        ),

        hint_text="Ingresa tu número",
        hint_style=ft.TextStyle(
            color="#64748B"
        )
    )

    def entrar(e):

        numero = telefono.value.strip()

        if not numero:
            return

        os.makedirs(
            "data",
            exist_ok=True
        )

        with open(
            "data/session.json",
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                {
                    "codigo": codigo,
                    "cliente": cliente,
                    "logo": logo_url,
                    "telefono": numero
                },
                f,
                ensure_ascii=False,
                indent=4
            )

        jukebox_view(
            page,
            codigo,
            cliente,
            numero,
            logo_url
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
                "Entrar",
                color="white",
                weight=ft.FontWeight.BOLD,
                size=16
            ),
            on_click=entrar
        )
    )

    page.add(
        ft.Image(
            src=logo_url,
            width=250
        ),

        ft.Text(
            "Ingresa tu número",
            size=32,
            weight=ft.FontWeight.BOLD,
            color="#22d3ee"
        ),

        ft.Text(
            "Para solicitar canciones",
            size=18,
            color="#94a3b8"
        ),

        ft.Container(height=30),

        telefono,

        ft.Container(height=40),

        btn
    )

    page.update()