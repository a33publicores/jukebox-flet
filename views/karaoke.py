import flet as ft

from services.karaoke_scanner import KaraokeScanner
from services.karaoke_search import KaraokeSearch
from services.karaoke_queue import KaraokeQueue
from components.karaoke_card import karaoke_card
from services.session_manager import cerrar_sesion as eliminar_sesion


def karaoke_view(page, codigo, cliente, telefono, logo_url):
    page.clean()
    page.bgcolor = "#020617"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    scanner = KaraokeScanner()
    canciones = scanner.escanear()
    total = len(canciones)

    lista = ft.ListView(expand=True, spacing=10, auto_scroll=False)

    buscar = ft.TextField(
        hint_text="Buscar canción o artista...",
        prefix_icon=ft.Icons.SEARCH,
        border_radius=15,
        bgcolor="#1F2937",
        border_color="#00D4FF",
        focused_border_color="#B44CFF",
        color="white",
    )

    def agregar(cancion):
        posicion = KaraokeQueue.agregar(cliente, telefono, cancion)
        page.snack_bar = ft.SnackBar(
            content=ft.Text(f"🎤 Canción agregada\nPosición #{posicion}")
        )
        page.snack_bar.open = True
        page.update()

    def cargar_lista(items):
        lista.controls.clear()
        for cancion in items:
            lista.controls.append(karaoke_card(cancion, agregar))
        page.update()

    def buscar_cancion(e):
        cargar_lista(KaraokeSearch.buscar(canciones, buscar.value))

    def cerrar_sesion(e):
        eliminar_sesion(page)
        from views.codigo import codigo_view
        codigo_view(page)

    buscar.on_change = buscar_cancion
    cargar_lista(canciones[:40])

    aviso = None
    if not canciones:
        aviso = ft.Container(
            padding=15,
            bgcolor="#1F2937",
            border_radius=12,
            content=ft.Text(
                "No hay canciones de Karaoke disponibles en la ruta configurada.",
                color="#FBBF24",
                text_align=ft.TextAlign.CENTER,
            ),
        )

    controles = [
        ft.Text(f"{total} canciones disponibles", color="#22d3ee", size=18),
        ft.Container(height=10),
        buscar,
    ]
    if aviso:
        controles += [ft.Container(height=10), aviso]
    controles += [ft.Container(height=15), lista]

    btn_cerrar = ft.Container(
        width=220,
        height=45,
        border_radius=15,
        gradient=ft.LinearGradient(
            colors=["#00D4FF", "#B44CFF"]
        ),
        shadow=ft.BoxShadow(
            blur_radius=20,
            color="#00D4FF55",
            spread_radius=1
        ),
        content=ft.TextButton(
            "Cerrar sesión",
            on_click=cerrar_sesion,
            style=ft.ButtonStyle(color="white"),
        ),
    )

    page.add(
        ft.Container(height=20),
        ft.Image(src=logo_url, width=180),
        ft.Text("🎤 PLAYBAR GO KARAOKE", size=30, weight=ft.FontWeight.BOLD, color="white"),
        ft.Text(cliente, color="#22d3ee", size=18),
        ft.Text(f"📱 {telefono}", color="white70"),
        ft.Container(height=12),
        btn_cerrar,
        ft.Container(height=15),
        ft.Container(
            width=380,
            height=600,
            padding=20,
            bgcolor="#111827",
            border_radius=15,
            content=ft.Column(expand=True, controls=controles),
        ),
    )
    page.update()
