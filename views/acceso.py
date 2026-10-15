"""
🔐 Entrada del administrador del bar:  play.alnovix.com/admin

Separada de la app de los clientes: pide el código del bar, el usuario y la contraseña
(los mismos de antes) y abre el panel. Si el bar todavía no ha pagado, el panel muestra
"Mi plan" para terminar el pago.
"""
import asyncio
import os

import flet as ft

CYAN = "#00D4FF"
VIOLETA = "#B44CFF"
FONDO = "#020617"
URL_PORTADA = os.getenv("PORTADA_URL", "https://play.alnovix.com/")


def boton_degradado(texto, on_click, ancho=320):
    return ft.Container(
        width=ancho, height=56, border_radius=16,
        gradient=ft.LinearGradient(colors=[CYAN, VIOLETA]),
        shadow=ft.BoxShadow(blur_radius=25, color="#00D4FF55", spread_radius=1),
        content=ft.TextButton(content=ft.Text(texto, color="white", size=16,
                                              weight=ft.FontWeight.BOLD), on_click=on_click),
    )


def campo(etiqueta, **kw):
    return ft.TextField(
        label=etiqueta, width=320, border_radius=14, bgcolor="#0b1220", color="white",
        border_color="#334155", focused_border_color=CYAN, cursor_color=CYAN,
        label_style=ft.TextStyle(color="#94A3B8"), **kw)


async def ir_a_portada(e=None):
    await ft.UrlLauncher().launch_url(URL_PORTADA, web_only_window_name="_self")


def acceso_admin_view(page, codigo_inicial=""):
    from views.admin import admin_view, credenciales_correctas
    from services.playbar_service import validar_cliente
    from services.session_manager import guardar_sesion

    page.clean()
    page.bgcolor = FONDO
    page.scroll = ft.ScrollMode.AUTO
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    codigo = campo("Código del bar", value=str(codigo_inicial or ""),
                   keyboard_type=ft.KeyboardType.NUMBER,
                   input_filter=ft.NumbersOnlyInputFilter(), autofocus=not codigo_inicial)
    usuario = campo("Usuario", autocorrect=False, enable_suggestions=False,
                    capitalization=ft.TextCapitalization.NONE, autofocus=bool(codigo_inicial))
    clave = campo("Contraseña", password=True, can_reveal_password=True)
    error = ft.Text("", color="#f87171", size=13, width=320, text_align=ft.TextAlign.CENTER)

    def entrar(e=None):
        cod = (codigo.value or "").strip()
        if not cod or not (usuario.value or "").strip() or not (clave.value or "").strip():
            error.value = "Escribe el código del bar, tu usuario y tu contraseña."
            page.update()
            return
        datos = validar_cliente(cod)
        if not datos.get("ok"):
            error.value = ("No encontramos ese código de bar." if "error" not in datos
                           else "No se pudo conectar. Intenta de nuevo.")
            page.update()
            return
        ok, msg = credenciales_correctas(usuario.value, clave.value, cod)
        if not ok:
            error.value = msg
            clave.value = ""
            page.update()
            return
        guardar_sesion(page, {"codigo": cod, "cliente": datos["nombre"], "logo": datos["logo"],
                              "telefono": "ADMIN", "modo": "admin"}, rol="admin")
        admin_view(page, cod, datos["nombre"], datos["logo"])

    codigo.on_submit = lambda e: usuario.focus()
    usuario.on_submit = lambda e: clave.focus()
    clave.on_submit = entrar

    def comprar(e):
        from views.comprar import comprar_view
        comprar_view(page)

    page.add(ft.Container(width=380, padding=ft.Padding.symmetric(horizontal=16, vertical=24),
                          content=ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14, controls=[
            ft.Image(src="/logo.png", width=170, height=120, fit=ft.BoxFit.CONTAIN),
            ft.Text("Panel del administrador", size=26, weight=ft.FontWeight.BOLD,
                    color="white", text_align=ft.TextAlign.CENTER),
            ft.Text("Entra con el código de tu bar, tu usuario y tu contraseña.",
                    size=14, color="#94A3B8", text_align=ft.TextAlign.CENTER),
            ft.Container(height=4),
            codigo, usuario, clave, error,
            boton_degradado("Entrar al panel", entrar),
            ft.Container(height=6),
            ft.TextButton("¿Aún no tienes PlayBar GO? Comprar", on_click=comprar,
                          style=ft.ButtonStyle(color=CYAN)),
            ft.TextButton("← Volver al inicio", on_click=ir_a_portada,
                          style=ft.ButtonStyle(color="#94A3B8")),
        ])))
    page.update()


async def abrir_desde_ruta(page, session):
    """/admin: si este dispositivo ya tiene la sesión de un admin, entra directo."""
    if session and session.get("rol") == "admin" and session.get("codigo"):
        from views.admin import admin_view
        await asyncio.to_thread(admin_view, page, session["codigo"],
                                session.get("cliente", ""), session.get("logo", ""))
        return
    await asyncio.to_thread(acceso_admin_view, page)
