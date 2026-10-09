import flet as ft


def seleccionar_modo_view(page, codigo, nombre, logo):
    page.clean()
    page.bgcolor = "#020617"
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    def abrir(modo):
        from views.login import login_view
        login_view(page, codigo, nombre, logo, modo)

    titulo = ft.Text(
        "¿Qué deseas hacer?",
        size=30,
        weight=ft.FontWeight.BOLD,
        color="white",
        text_align=ft.TextAlign.CENTER,
    )

    subtitulo = ft.Text(
        "Selecciona una opción para continuar",
        size=16,
        color="#94A3B8",
        text_align=ft.TextAlign.CENTER,
    )

    def boton(texto, modo, icono):
        return ft.Container(
            width=290,
            height=70,
            border_radius=18,
            gradient=ft.LinearGradient(colors=["#00D4FF", "#B44CFF"]),
            shadow=ft.BoxShadow(blur_radius=25, color="#00D4FF55", spread_radius=1),
            content=ft.TextButton(
                content=ft.Row(
                    [
                        ft.Text(icono, size=26),
                        ft.Text(
                            texto,
                            color="white",
                            size=20,
                            weight=ft.FontWeight.BOLD,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                on_click=lambda e: abrir(modo),
            ),
        )

    def abrir_admin(e):
        from views.admin import admin_view, pedir_pin
        from services.session_manager import guardar_sesion

        def entrar_admin():
            guardar_sesion(page, {"codigo": codigo, "cliente": nombre, "logo": logo,
                                  "telefono": "ADMIN", "modo": "admin"}, rol="admin")
            admin_view(page, codigo, nombre, logo)

        pedir_pin(page, entrar_admin, codigo)

    page.add(
        ft.Image(src="/logohallowen.png", width=150),
        ft.Container(height=20),
        titulo,
        subtitulo,
        ft.Container(height=30),
        boton("Música", "musica", "🎵"),
        ft.Container(height=15),
        boton("Karaoke", "karaoke", "🎤"),
        ft.Container(height=25),
        ft.TextButton("🔧 Administrador", on_click=abrir_admin,
                      style=ft.ButtonStyle(color="#64748b")),
    )
    page.update()
