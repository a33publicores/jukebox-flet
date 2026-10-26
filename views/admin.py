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

URL_CLIENTES = os.getenv("URL_CLIENTES", "https://play.alnovix.com/bar/")
REFRESCO_SEG = 6
MAX_HORAS_PANEL = 16  # tope de seguridad (una jornada larga); antes 3 h dejaba el panel "pegado"
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
    return False, intento_fallido()


def intento_fallido():
    """Cuenta un intento malo; al quinto bloquea un minuto. Devuelve el mensaje."""
    _intentos["n"] += 1
    if _intentos["n"] >= 5:
        _intentos["n"] = 0
        _intentos["hasta"] = time.time() + 60
    return "Usuario o contraseña incorrectos"


def es_super(usuario, clave):
    """True si son las credenciales del super administrador (respeta el bloqueo)."""
    if time.time() < _intentos["hasta"] or not str(usuario or "").strip():
        return False
    try:
        from services import db
        return db.validar_super(usuario, clave)
    except Exception as ex:
        print("⚠️ No se pudo validar el super admin:", ex)
        return False


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

    async def _a_clave(e):
        await clave.focus()

    usuario.on_submit = _a_clave
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

    cola_vista = {"filas": [], "pausa_hasta": 0.0}

    def mover(desde, hasta):
        """Cambia el orden de la playlist (el reproductor usa el mismo orden)."""
        filas = list(cola_vista["filas"])
        if not (0 <= desde < len(filas)) or not (0 <= hasta < len(filas)) or desde == hasta:
            return
        filas.insert(hasta, filas.pop(desde))
        cola_vista["filas"] = filas
        cola_vista["pausa_hasta"] = time.time() + 2  # que el refresco no deshaga el cambio

        def _run():
            try:
                cola.reordenar(codigo, filas)
                aviso.value = "Orden cambiado ✔ (el reproductor lo toma en segundos)"
            except Exception as ex:
                print("❌ reordenar:", ex)
                aviso.value = "No se pudo cambiar el orden"
            refrescar()
        threading.Thread(target=_run, daemon=True).start()

    def flecha(icono, tip, on_click, apagado):
        return ft.IconButton(icon=icono, icon_size=22, tooltip=tip, disabled=apagado,
                             icon_color="#334155" if apagado else "#00D4FF",
                             on_click=on_click, width=34, height=34)

    def refrescar():
        if time.time() < cola_vista["pausa_hasta"]:
            return
        try:
            st = cola.estado_reproductor(codigo)
        except Exception as ex:
            estado_txt.value = "Sin conexión con la hoja"
            print("❌ estado admin:", ex)
            page.update()
            return
        ultimo["estado"] = st["estado"]
        # Si nada cambió desde la última vez, no se reconstruye la lista ni se manda nada al
        # navegador (antes se rehacía la cola completa cada 6 s: lento en servidor y celular).
        firma = (st["online"], st["estado"], st["actual"], st["siguiente"],
                 bool(st["comando_pendiente"]),
                 tuple((it.fila, it.titulo) for it in st["cola"][:30]))
        if firma == ultimo.get("firma"):
            return
        ultimo["firma"] = firma
        punto.color = "#22c55e" if st["online"] else "#ef4444"
        estado_txt.value = (
            {"reproduciendo": "Reproduciendo", "pausado": "Pausado", "relleno": "Sonando relleno",
             "esperando": "Esperando canciones"}.get(st["estado"], st["estado"] or "—")
            if st["online"] else "Reproductor desconectado"
        )
        actual_txt.value = st["actual"] or "—"
        sigue_txt.value = st["siguiente"] or "No hay más canciones en cola"
        btn_pausa.icon = ft.Icons.PLAY_CIRCLE if st["estado"] == "pausado" else ft.Icons.PAUSE_CIRCLE
        visibles = st["cola"][:30]
        cola_vista["filas"] = [it.fila for it in st["cola"]]
        ultimo_i = len(visibles) - 1
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
                    ft.Column([
                        ft.Row([
                            flecha(ft.Icons.KEYBOARD_DOUBLE_ARROW_UP, "Poner de primera",
                                   lambda e, i=n - 1: mover(i, 0), n == 1),
                            flecha(ft.Icons.ARROW_UPWARD, "Subir",
                                   lambda e, i=n - 1: mover(i, i - 1), n == 1),
                        ], spacing=0, tight=True),
                        ft.Row([
                            flecha(ft.Icons.ARROW_DOWNWARD, "Bajar",
                                   lambda e, i=n - 1: mover(i, i + 1), n - 1 == ultimo_i),
                            ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#94a3b8",
                                          tooltip="Quitar de la cola", icon_size=22,
                                          width=34, height=34,
                                          on_click=lambda e, f=it.fila: quitar(f)),
                        ], spacing=0, tight=True),
                    ], spacing=0, tight=True),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            )
            for n, it in enumerate(visibles, start=1)
        ]
        if st["comando_pendiente"]:
            aviso.value = "Esperando al reproductor…"
        try:
            page.update()
        except Exception:
            vivo["v"] = False  # el navegador se cerró: dejar de consultar la hoja

    def bucle():
        # Sigue actualizando mientras la pestaña esté abierta (antes paraba a las 3 h y el
        # panel se quedaba mostrando una canción vieja). Se detiene al cerrar la pestaña.
        fin = time.time() + MAX_HORAS_PANEL * 3600
        sin_conexion = None
        while vivo["v"] and time.time() < fin:
            try:
                conectada = page.session.connection is not None
            except RuntimeError:
                return  # la sesión ya no existe (pestaña cerrada hace rato)
            if not conectada:
                # pestaña cerrada o celular bloqueado: no se consulta la base; si vuelve,
                # sigue; si no vuelve en 20 min, se termina.
                sin_conexion = sin_conexion or time.time()
                if time.time() - sin_conexion > 20 * 60:
                    return
                time.sleep(2)
                continue
            if sin_conexion:
                sin_conexion = None
                ultimo.pop("firma", None)  # al volver, se repinta todo
            try:
                refrescar()
            except Exception as ex:
                texto = str(ex).lower()
                if "session closed" in texto or "destroyed" in texto or "disconnected" in texto:
                    return  # cerraron la pestaña
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

    # --- Relleno (lo que suena cuando nadie pide): géneros y artistas ----------------
    from services import generos as G
    from views.selector_multiple import selector
    elegidos, artistas_elegidos = set(), set()
    try:
        from services import db as _db
        _txt = (_db.control(codigo) or {}).get("generos", "")
        elegidos = G.lista(_txt)
        artistas_elegidos = G.artistas(_txt)
    except Exception as ex:
        print("⚠️ géneros:", ex)
    nota_generos = ft.Text("", color="#94A3B8", size=12, text_align=ft.TextAlign.CENTER,
                           width=380)

    def pintar_nota():
        nota_generos.value = ("Suena de todo cuando nadie pide." if not (elegidos or artistas_elegidos)
                              else "Cuando nadie pide solo suena lo marcado (géneros y artistas). "
                                   "Lo que pidan los clientes suena siempre.")

    def guardar_generos():
        pintar_nota()
        try:
            nota_generos.update()
        except Exception:
            pass

        def _guardar():
            try:
                from services import db as _db
                _db.poner_generos(codigo, G.guardar_texto(elegidos, artistas_elegidos))
                aviso.value = "Relleno guardado ✔ (el reproductor lo toma en segundos)"
            except Exception as ex:
                print("❌ géneros:", ex)
                aviso.value = "No se pudo guardar el relleno"
            try:
                aviso.update()
            except Exception:
                pass
        threading.Thread(target=_guardar, daemon=True).start()

    # Los géneros salen de una vez (no esperan a contar el historial); los números llegan después.
    lista_generos, opciones_generos = selector("🎵 Todos los géneros", elegidos, guardar_generos)
    opciones_generos([(k, nombre, 0) for k, nombre in G.GENEROS])
    lista_artistas, opciones_artistas = selector(
        "🎤 Todos los artistas", artistas_elegidos, guardar_generos, buscador=True,
        vacio_txt="Cargando los artistas que han sonado en el bar…")
    pintar_nota()

    def contar_generos():
        """Cuántas canciones del historial hay de cada género y de cada artista."""
        try:
            from services import db as _db
            from services.playbar_service import inicio_jornada
            cuantos, por_artista, nombre_de = {}, {}, {}
            for f in _db.aleatorio(codigo, inicio_jornada()):
                g = G.clasificar(f["titulo"], f["canal"])
                cuantos[g] = cuantos.get(g, 0) + 1
                a = G.artista_de(f["titulo"], f["canal"])
                if len(a) >= 2:
                    clave = a.lower()
                    por_artista[clave] = por_artista.get(clave, 0) + 1
                    nombre_de.setdefault(clave, a)
            opciones_generos([(k, nombre, cuantos.get(k, 0)) for k, nombre in G.GENEROS])
            # un artista ya elegido conserva su nombre guardado (aunque cambien mayúsculas)
            nombre_de.update({a.lower(): a for a in artistas_elegidos})
            arts = sorted(por_artista.items(), key=lambda x: (-x[1], x[0]))
            opciones = [(nombre_de[k], nombre_de[k], n) for k, n in arts]
            # los ya elegidos siempre aparecen (aunque ya no estén en el historial)
            opciones += [(a, a, 0) for a in sorted(artistas_elegidos)
                         if a.lower() not in por_artista]
            opciones_artistas(opciones)
        except Exception as ex:
            print("⚠️ contar géneros:", ex)
            opciones_artistas([(a, a, 0) for a in sorted(artistas_elegidos)])

    async def salir(e):
        vivo["v"] = False
        from services.session_manager import cerrar_sesion
        from views.acceso import ir_a_portada
        cerrar_sesion(page)
        await ir_a_portada()

    def boton(icono, tooltip, cmd):
        return ft.IconButton(icon=icono, icon_size=44, icon_color="white", tooltip=tooltip,
                             on_click=lambda e: mandar(cmd))

    page.add(ft.Container(
        padding=16, content=ft.Column(
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10,
            controls=[
                ft.Image(src="/logohallowen.png", width=110),
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
                ft.Text("PLAYLIST · ⏫ de primera · ⬆⬇ mover · 🗑 quitar", color="#94A3B8",
                        size=13, weight=ft.FontWeight.BOLD),
                lista,
                ft.Container(height=6),
                ft.Text("🎚️ MÚSICA DE RELLENO (cuando nadie pide)", color="#94A3B8", size=13,
                        weight=ft.FontWeight.BOLD),
                lista_generos,
                lista_artistas,
                nota_generos,
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
                ft.Text(f"Enlace para tus clientes: {URL_CLIENTES}{codigo}", color="#94A3B8",
                        size=13, selectable=True, text_align=ft.TextAlign.CENTER),
                ft.TextButton("Cerrar sesión", on_click=salir),
            ],
        ),
    ))
    page.update()
    threading.Thread(target=bucle, daemon=True).start()
    threading.Thread(target=contar_generos, daemon=True).start()