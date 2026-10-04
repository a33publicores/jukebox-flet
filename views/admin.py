"""
Panel de administrador de PlayBar GO.

Entra con el PIN de la variable ADMIN_PIN (Railway). Desde aquí se controla el
reproductor del lugar: pausar/reanudar, siguiente, anterior, y se ve qué suena,
qué sigue y la playlist (con opción de quitar canciones de la cola).

El panel no reproduce nada: manda comandos a la hoja CONTROL y el reproductor
de escritorio los ejecuta en pocos segundos.
"""
import hmac
import os
import threading
import time

import flet as ft

from services import cola

REFRESCO_SEG = 4
_intentos = {"n": 0, "hasta": 0.0}


def pin_correcto(pin):
    """Compara contra ADMIN_PIN. Devuelve (ok, mensaje_de_error)."""
    esperado = os.environ.get("ADMIN_PIN", "").strip()
    if not esperado:
        return False, "ADMIN_PIN no está configurado en Railway"
    if time.time() < _intentos["hasta"]:
        return False, "Demasiados intentos. Espera un minuto."
    if hmac.compare_digest(str(pin or "").strip().encode(), esperado.encode()):
        _intentos["n"] = 0
        return True, ""
    _intentos["n"] += 1
    if _intentos["n"] >= 5:
        _intentos["n"] = 0
        _intentos["hasta"] = time.time() + 60
    return False, "PIN incorrecto"


def pedir_pin(page, al_entrar):
    """Muestra el diálogo del PIN; si es correcto llama a al_entrar()."""
    campo = ft.TextField(
        label="PIN de administrador", password=True, can_reveal_password=True,
        autofocus=True, keyboard_type=ft.KeyboardType.NUMBER, color="white",
        border_color="#00D4FF",
    )
    error = ft.Text("", color="#f87171", size=13)

    def cerrar(e=None):
        dlg.open = False
        page.update()

    def entrar(e):
        ok, msg = pin_correcto(campo.value)
        if ok:
            cerrar()
            al_entrar()
        else:
            error.value = msg
            campo.value = ""
            page.update()

    campo.on_submit = entrar
    dlg = ft.AlertDialog(
        modal=True, bgcolor="#111827",
        title=ft.Text("🔧 Administrador", color="#22d3ee"),
        content=ft.Column([campo, error], tight=True, width=280),
        actions=[ft.TextButton("Cancelar", on_click=cerrar),
                 ft.FilledButton("Entrar", on_click=entrar)],
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


def admin_view(page, codigo, nombre, logo):
    page.clean()
    page.bgcolor = "#020617"
    page.scroll = ft.ScrollMode.AUTO
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START

    vivo = {"v": True}
    ultimo = {"estado": ""}

    punto = ft.Text("●", size=16, color="#64748b")
    estado_txt = ft.Text("Conectando…", color="#94A3B8", size=14)
    actual_txt = ft.Text("—", color="white", size=20, weight=ft.FontWeight.BOLD,
                         text_align=ft.TextAlign.CENTER)
    sigue_txt = ft.Text("—", color="#cbd5e1", size=16, text_align=ft.TextAlign.CENTER)
    aviso = ft.Text("", color="#facc15", size=13, text_align=ft.TextAlign.CENTER)
    lista = ft.Column(spacing=8)
    btn_pausa = ft.IconButton(icon=ft.Icons.PAUSE_CIRCLE, icon_size=56, icon_color="#00D4FF")

    def mandar(cmd):
        def _run():
            try:
                cola.enviar_comando(codigo, cmd)
                aviso.value = "Comando enviado ✔"
            except Exception as ex:
                print("❌ comando admin:", ex)
                aviso.value = "No se pudo enviar el comando"
            page.update()
        threading.Thread(target=_run, daemon=True).start()

    def toggle(e):
        mandar("reanudar" if ultimo["estado"] == "pausado" else "pausar")

    btn_pausa.on_click = toggle

    def quitar(fila):
        def _run():
            try:
                cola.eliminar_de_cola(codigo, fila)
            except Exception as ex:
                print("❌ eliminar:", ex)
            refrescar()
        threading.Thread(target=_run, daemon=True).start()

    def refrescar():
        try:
            st = cola.estado_reproductor(codigo)
        except Exception as ex:
            estado_txt.value = "Sin conexión con la hoja"
            print("❌ estado admin:", ex)
            page.update()
            return
        ultimo["estado"] = st["estado"]
        punto.color = "#22c55e" if st["online"] else "#ef4444"
        estado_txt.value = (
            {"reproduciendo": "Reproduciendo", "pausado": "Pausado", "relleno": "Sonando relleno",
             "esperando": "Esperando canciones"}.get(st["estado"], st["estado"] or "—")
            if st["online"] else "Reproductor desconectado"
        )
        actual_txt.value = st["actual"] or "—"
        sigue_txt.value = st["siguiente"] or "No hay más canciones en cola"
        btn_pausa.icon = ft.Icons.PLAY_CIRCLE if st["estado"] == "pausado" else ft.Icons.PAUSE_CIRCLE
        lista.controls = [
            ft.Container(
                padding=10, border_radius=12, bgcolor="#111827", width=380,
                content=ft.Row([
                    ft.Text(f"{n}", color="#00D4FF", weight=ft.FontWeight.BOLD, width=24),
                    ft.Column([
                        ft.Text(it.titulo, color="white", size=14, max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(it.canal, color="#94a3b8", size=11),
                    ], spacing=2, expand=True),
                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#94a3b8",
                                  tooltip="Quitar de la cola",
                                  on_click=lambda e, f=it.fila: quitar(f)),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
            for n, it in enumerate(st["cola"][:30], start=1)
        ]
        if st["comando_pendiente"]:
            aviso.value = "Esperando al reproductor…"
        page.update()

    def bucle():
        while vivo["v"]:
            refrescar()
            for _ in range(REFRESCO_SEG * 2):
                if not vivo["v"]:
                    return
                time.sleep(0.5)

    def salir(e):
        vivo["v"] = False
        from views.seleccionar_modo import seleccionar_modo_view
        seleccionar_modo_view(page, codigo, nombre, logo)

    def boton(icono, tooltip, cmd):
        return ft.IconButton(icon=icono, icon_size=44, icon_color="white", tooltip=tooltip,
                             on_click=lambda e: mandar(cmd))

    page.add(ft.Container(
        padding=16, content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10,
            controls=[
                ft.Image(src="/logomundial.png", width=110),
                ft.Text(f"Administrador · {nombre}", size=22, color="white",
                        weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                ft.Row([punto, estado_txt], alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(height=6),
                ft.Text("▶ EN REPRODUCCIÓN", color="#22d3ee", size=13, weight=ft.FontWeight.BOLD),
                actual_txt,
                ft.Text("⏭ SIGUE", color="#B44CFF", size=13, weight=ft.FontWeight.BOLD),
                sigue_txt,
                ft.Row([boton(ft.Icons.SKIP_PREVIOUS, "Anterior", "anterior"), btn_pausa,
                        boton(ft.Icons.SKIP_NEXT, "Siguiente", "siguiente")],
                       alignment=ft.MainAxisAlignment.CENTER),
                aviso,
                ft.Text("PLAYLIST", color="#94A3B8", size=13, weight=ft.FontWeight.BOLD),
                lista,
                ft.Container(height=10),
                ft.TextButton("← Salir del modo administrador", on_click=salir),
            ],
        ),
    ))
    page.update()
    threading.Thread(target=bucle, daemon=True).start()
