import flet as ft

from services.session_manager import guardar_sesion


def login_view(page, codigo, cliente, logo_url, modo="musica"):
    page.clean()
    page.bgcolor = "#020617"

    titulo = "Ingresa tu número"
    subtitulo = (
        "Para solicitar canciones" if modo == "musica"
        else "Para ingresar a Karaoke"
    )

    telefono = ft.TextField(
        label="Número telefónico",
        width=350,
        height=60,
        keyboard_type=ft.KeyboardType.NUMBER,
        input_filter=ft.NumbersOnlyInputFilter(),
        max_length=10,
        counter=ft.Container(width=0, height=0),
        text_align=ft.TextAlign.CENTER,
        border_radius=15,
        bgcolor="#1A1A1A",
        color="white",
        border_color="#00D4FF",
        focused_border_color="#B44CFF",
        cursor_color="#00D4FF",
        text_style=ft.TextStyle(color="white", size=18, weight=ft.FontWeight.W_500),
        label_style=ft.TextStyle(color="#94A3B8", size=14),
        hint_text="3001234567",
        hint_style=ft.TextStyle(color="#64748B"),
    )

    def entrar(e):
        numero = "".join(c for c in (telefono.value or "") if c.isdigit())
        if len(numero) == 12 and numero.startswith("57"):
            numero = numero[2:]  # pegaron el número con +57
        if not (len(numero) == 10 and numero.startswith("3")):
            telefono.error = "Celular de 10 dígitos que empiece por 3 (sin +57)"
            page.update()
            return
        telefono.error = None

        guardar_sesion(page, {
            "codigo": codigo,
            "cliente": cliente,
            "logo": logo_url,
            "telefono": numero,
            "modo": modo,
        })

        if modo == "karaoke":
            from views.karaoke import karaoke_view
            karaoke_view(page, codigo, cliente, numero, logo_url)
        else:
            from views.jukebox import jukebox_view
            jukebox_view(page, codigo, cliente, numero, logo_url)

    btn = ft.Container(
        width=220,
        height=60,
        border_radius=18,
        gradient=ft.LinearGradient(colors=["#00D4FF", "#B44CFF"]),
        shadow=ft.BoxShadow(blur_radius=25, color="#00D4FF66", spread_radius=1),
        content=ft.TextButton(
            content=ft.Text("Entrar", color="white", weight=ft.FontWeight.BOLD, size=16),
            on_click=entrar,
        ),
    )

    def volver(e):
        from views.seleccionar_modo import seleccionar_modo_view
        seleccionar_modo_view(page, codigo, cliente, logo_url)

    page.add(
        ft.Image(src=logo_url, width=250),
        ft.Text(titulo, size=32, weight=ft.FontWeight.BOLD, color="#22d3ee"),
        ft.Text(subtitulo, size=18, color="#94a3b8"),
        ft.Container(height=30),
        telefono,
        ft.Container(height=40),
        btn,
        ft.Container(height=16),
        ft.TextButton("← Volver", on_click=volver, style=ft.ButtonStyle(color="#94A3B8")),
    )
    page.update()
