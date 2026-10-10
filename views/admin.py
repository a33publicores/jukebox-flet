"""
Panel de administrador de PlayBar GO.

Entra con usuario y contraseña creados por el super administrador (tabla admins de la base). Desde aquí se controla el
reproductor del lugar: pausar/reanudar, siguiente, anterior, y se ve qué suena,
qué sigue y la playlist (con opción de quitar canciones de la cola).

El panel no reproduce nada: manda comandos (tabla control) y el reproductor
de escritorio los ejecuta en pocos segundos.
"""
import hmac
import os
import threading
import time

import flet as ft

from services import cola

REFRESCO_SEG = 6
MAX_HORAS_PANEL = 3  # el panel deja de consultar solo después de esto
_intentos = {"n": 0, "hasta": 0.0}


def credenciales_correctas(usuario, clave, codigo=None):
    """Valida contra la tabla admins de la base (los crea el super administrador).
    Respaldo: variables ADMIN_USER / ADMIN_PASS de Railway. Devuelve (ok, mensaje)."""
    if time.time() < _intentos["hasta"]:
        return False, "Demasiados intentos. Espera un minuto."
    codigo = str(codigo or "").strip()
    ok, hay = False, False
    try:
        from services import db
        ok, hay = db.validar_admin(codigo, usuario, clave)
    except Exception as ex:
        print("⚠️ No se pudo validar el admin en la base:", ex)
        return False, "No se pudo conectar con la base. Intenta de nuevo."

    if not ok:
        esp_user = os.environ.get("ADMIN_USER", "").strip()
        esp_pass = os.environ.get("ADMIN_PASS", "").strip()
        if esp_user and esp_pass:
            hay = True
            ok = (hmac.compare_digest(str(usuario or "").strip().lower().encode(),
                                      esp_user.lower().encode())
                  and hmac.compare_digest(str(clave or "").strip().encode(), esp_pass.encode()))

    print(f"🔐 Admin lugar={codigo!r} usuario={str(usuario or '').strip()!r} ok={ok} hay={hay}")
    if not hay:
        return False, f"No hay administradores para el lugar {codigo}"
    if ok:
        _intentos["n"] = 0
        return True, ""
    _intentos["n"] += 1
    if _intentos["n"] >= 5:
        _intentos["n"] = 0
        _intentos["hasta"] = time.time() + 60
    return False, "Usuario o contraseña incorrectos"


def pedir_pin(page, al_entrar, codigo=None):
    """Diálogo de usuario y contraseña; si son correctos llama a al_entrar()."""
    usuario = ft.TextField(label="Usuario", autofocus=True, color="white",
                           border_color="#00D4FF", autocorrect=False,
                           enable_suggestions=False,
                           capitalization=ft.TextCapitalization.NONE)
    clave = ft.TextField(label="Contraseña", password=True, can_reveal_password=True,
                         color="white", border_color="#00D4FF")
    error = ft.Text("", color="#f87171", size=13)

    def cerrar(e=None):
        dlg.open = False
        try:
            dlg.update()
        except Exception:
            pass
        page.update()

    def entrar(e):
        ok, msg = credenciales_correctas(usuario.value, clave.value, codigo)
        if ok:
            cerrar()
            al_entrar()
        else:
            error.value = msg
            clave.value = ""
            page.update()

    usuario.on_submit = lambda e: clave.focus()
    clave.on_submit = entrar
    dlg = ft.AlertDialog(
        modal=True, bgcolor="#111827",
        title=ft.Text("🔧 Administrador", color="#22d3ee"),
        content=ft.Column([usuario, clave, error], tight=True, width=280),
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
        try:
            page.update()
        except Exception:
            vivo["v"] = False  # el navegador se cerró: dejar de consultar la hoja

    def bucle():
        fin = time.time() + MAX_HORAS_PANEL * 3600
        while vivo["v"] and time.time() < fin:
            try:
                refrescar()
            except Exception as ex:
                print("⚠️ panel admin:", ex)
            for _ in range(REFRESCO_SEG * 2):
                if not vivo["v"]:
                    return
                time.sleep(0.5)

    def colocar_musica(e):
        """El admin pide canciones sin escribir teléfono."""
        vivo["v"] = False
        from services.session_manager import guardar_sesion
        guardar_sesion(page, {"codigo": codigo, "cliente": nombre, "logo": logo,
                              "telefono": "ADMIN", "modo": "musica_admin"}, rol="admin")
        from views.jukebox import jukebox_view
        jukebox_view(page, codigo, nombre, "ADMIN", logo, es_admin=True)

    def mi_plan(e):
        vivo["v"] = False
        from views.plan import plan_view
        plan_view(page, codigo, nombre, logo)

    # Aviso del plan (prueba gratis que se acaba, plan vencido...)
    banner = ft.Container(visible=False)
    try:
        from services import suscripcion
        est = suscripcion.estado(codigo)
        if est["aviso"] or not est["permitido"]:
            banner = ft.Container(
                width=380, padding=14, border_radius=14,
                bgcolor="#7f1d1d" if not est["permitido"] else "#713f12",
                on_click=mi_plan,
                content=ft.Column([
                    ft.Text(("🔒 " if not est["permitido"] else "⏳ ") + est["titulo"],
                            color="white", size=16, weight=ft.FontWeight.BOLD),
                    ft.Text(est["mensaje"], color="#fde68a", size=13),
                    ft.Text("Toca aquí para adquirir tu plan →", color="white", size=13,
                            weight=ft.FontWeight.BOLD),
                ], spacing=4),
            )
    except Exception as ex:
        print("⚠️ estado del plan:", ex)

    def salir(e):
        vivo["v"] = False
        from services.session_manager import cerrar_sesion
        cerrar_sesion(page)
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
                banner,
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
                ft.Container(
                    width=260, height=52, border_radius=16,
                    gradient=ft.LinearGradient(colors=["#00D4FF", "#B44CFF"]),
                    content=ft.TextButton(
                        content=ft.Text("🎵 Colocar música", color="white", size=17,
                                        weight=ft.FontWeight.BOLD),
                        on_click=colocar_musica,
                    ),
                ),
                ft.OutlinedButton("💳 Mi plan", on_click=mi_plan, width=260),
                ft.TextButton("← Salir del modo administrador", on_click=salir),
            ],
        ),
    ))
    page.update()
    threading.Thread(target=bucle, daemon=True).start()
