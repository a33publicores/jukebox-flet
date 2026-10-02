import flet as ft


def karaoke_card(cancion, agregar):

    return ft.Container(

        margin=10,

        padding=15,

        bgcolor="#111827",

        border_radius=15,

        content=ft.Row(

            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,

            vertical_alignment=ft.CrossAxisAlignment.CENTER,

            controls=[

                ft.Column(

                    expand=True,

                    spacing=5,

                    controls=[

                        ft.Text(
                            cancion["titulo"],
                            size=18,
                            weight=ft.FontWeight.BOLD,
                            color="white",
                            max_lines=1
                        ),

                        ft.Text(
                            f"👤 {cancion['artista']}",
                            size=14,
                            color="#94A3B8"
                        )

                    ]

                ),

                ft.IconButton(

                    icon=ft.Icons.ADD,

                    icon_color="#00D4FF",

                    icon_size=30,

                    tooltip="Agregar a la cola",

                    on_click=lambda e: agregar(cancion)

                )

            ]

        )

    )