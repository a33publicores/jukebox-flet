import flet as ft
import os
import json
from services.api_client import APIClient
import threading


def jukebox_view(
    page,
    codigo,
    cliente,
    telefono,
    logo_url
):

    page.clean()

    page.bgcolor = "#020617"
    
    page.scroll = ft.ScrollMode.AUTO
    page.update()

    page.horizontal_alignment = (
        ft.CrossAxisAlignment.CENTER
    )

    buscador = ft.TextField(
        label="Nombre de canción o artista",
        width=350,
        height=60,
        border_radius=15,
        bgcolor="#1A1A1A",

        color="white",

        border_color="#00D4FF",
        focused_border_color="#B44CFF",

        cursor_color="#00D4FF",

        text_style=ft.TextStyle(
            color="white",
            size=18
        ),

        label_style=ft.TextStyle(
            color="#94A3B8"
        )
    )

    resultados = ft.Column(
    )
    
    logo_playbar = ft.Image(
        src="logo.png",
        width=140
    )

    logo_local = ft.Image(
        src=f"logos/{logo_url}",
        width=100
    )
    
    def cerrar_sesion(e):

        try:

            if os.path.exists(
                "data/session.json"
            ):
                os.remove(
                    "data/session.json"
                )

        except Exception as ex:

            print(ex)

        from views.codigo import codigo_view

        codigo_view(page)

    if not logo_url:
        logo_local = ft.Container()

    ultima_cancion_text = ft.Text(
        "Sin canciones",
        color="#22d3ee",
        size=16,
        text_align=ft.TextAlign.CENTER
    )

    def confirmar(e, item, ventana):

        ventana.open = False
        page.update()

        def enviar_cancion():
            resultado = APIClient.agregar_cancion(
                cliente=codigo,
                telefono=telefono,
                titulo=item["snippet"]["title"],
                canal=item["snippet"]["channelTitle"],
                video_id=item["id"]["videoId"]
            )

        threading.Thread(
            target=enviar_cancion,
            daemon=True
        ).start()

        ultima_cancion_text.value = item["snippet"]["title"]

        exito = ft.AlertDialog(
            modal=False,
            bgcolor="#111827",
            title=ft.Text(
                "✅ Canción agregada",
                color="#22d3ee"
            ),
            content=ft.Text(
                item["snippet"]["title"],
                color="white"
            )
        )

        page.overlay.append(exito)
        exito.open = True

        page.update()

    def buscar(e):

        resultados.controls.clear()

        data = APIClient.buscar(
            buscador.value
        )

        for item in data.get(
            "items",
            []
        ):

            titulo = item["snippet"]["title"]

            canal = item["snippet"][
                "channelTitle"
            ]

            thumbnail = item["snippet"][
                "thumbnails"
            ]["high"]["url"]

            def agregar(e, item=item):

                page.overlay.clear()

                confirmacion = ft.AlertDialog(
                    modal=True,
                    bgcolor="#111827",
                    title=ft.Text(
                        "¿Deseas agregar esta canción?",
                        color="white"
                    ),
                    content=ft.Text(
                        item["snippet"]["title"],
                        color="#22d3ee"
                    ),
                    actions=[
                        ft.TextButton(
                            "Aceptar",
                            on_click=lambda ev: confirmar(
                                ev,
                                item,
                                confirmacion
                            )
                        ),
                        ft.TextButton(
                        "Cancelar",
                        on_click=lambda ev: (
                            setattr(confirmacion, "open", False),
                        page.update()
                    )
                )
                    ]
                )

                page.overlay.append(confirmacion)
                confirmacion.open = True
                page.update()

            resultados.controls.append(

                ft.Container(

                    margin=10,

                    padding=10,

                    border_radius=15,

                    bgcolor="#111827",

                    on_click=agregar,

                    content=ft.Column(

                        controls=[

                            ft.Image(
                                src=thumbnail,
                                width=380,
                                height=210
                            ),

                            ft.Container(
                                height=5
                            ),

                            ft.Text(
                                titulo,
                                color="white",
                                size=16,
                                weight=ft.FontWeight.BOLD
                            ),

                            ft.Text(
                                canal,
                                color="#94a3b8",
                                size=13
                            )

                        ]
                    )
                )
            )
            
        page.update()
        

        try:
            page.scroll_to(offset=600, duration=300)
        except:
            pass

    page.add(

        ft.Container(
            expand=True,

            content=ft.Column(

                horizontal_alignment=ft.CrossAxisAlignment.CENTER,

                controls=[

                    logo_playbar,

                    ft.Container(height=2),

                    logo_local,

                    ft.Container(height=2),

                    ft.Text(
                        cliente,
                        size=30,
                        color="white",
                        weight=ft.FontWeight.BOLD
                    ),

                    ft.Row(
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[
                            ft.Text("👤", size=18),
                            ft.Text(
                                telefono,
                                color="#94a3b8",
                                size=18
                            )
                        ]   
                    ),

                    ft.Container(height=10),

                    ft.Container(
                        width=220,
                        height=45,
                        border_radius=15,
                        gradient=ft.LinearGradient(
                            colors=[
                                "#00D4FF",
                                "#B44CFF"
                            ]
                        ),
                        shadow=ft.BoxShadow(
                            blur_radius=20,
                            color="#00D4FF55",
                            spread_radius=1
                        ),
                        content=ft.TextButton(
                            "Cerrar sesión",
                            on_click=cerrar_sesion,
                            style=ft.ButtonStyle(
                            color="white"
                        )
                    )
                ),

                    ft.Container(height=20),
                    
                    ft.Text(
                        "🎵 Última canción agregada",
                            color="#22d3ee",
                            size=20,
                            weight=ft.FontWeight.BOLD
                        ),

                    ft.Container(height=5),

                    ultima_cancion_text,

                    ft.Container(height=15),

                    buscador,

                    ft.Container(
                        width=180,
                        height=50,
                        border_radius=15,
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
                            content=ft.Row(
                                [
                                    ft.Text("🔍", size=18),
                                    ft.Text(
                                        "Buscar",
                                        color="white",
                                        weight=ft.FontWeight.BOLD
                                        )
                                    ],
                                alignment=ft.MainAxisAlignment.CENTER
                            ),
                            on_click=buscar
                        )
                    ),
                    
                    ft.Text(
                        "Resultados encontrados",
                        color="#22d3ee",
                        size=18,
                        weight=ft.FontWeight.BOLD
                        ),

                    ft.Container(
                        resultados
                    )

                ]
            )
        )
    )

    page.update()
