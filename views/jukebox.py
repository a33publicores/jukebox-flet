import threading

import flet as ft

from services.playbar_service import buscar as buscar_canciones, agregar_cancion
from services.session_manager import cerrar_sesion as eliminar_sesion

CYAN = "#00D4FF"
VIOLETA = "#B44CFF"
CLAVE_RESULTADOS = "resultados"


def _boton(texto, on_click, ancho=125, alto=45):
    """Botón con el degradado de PlayBar GO. Devuelve (contenedor, botón)."""
    boton = ft.TextButton(
        content=ft.Text(texto, color="white", weight=ft.FontWeight.BOLD),
        on_click=on_click,
        style=ft.ButtonStyle(color="white"),
    )
    contenedor = ft.Container(
        width=ancho,
        height=alto,
        border_radius=15,
        gradient=ft.LinearGradient(colors=[CYAN, VIOLETA]),
        shadow=ft.BoxShadow(blur_radius=20, color="#00D4FF55", spread_radius=1),
        content=boton,
    )
    return contenedor, boton


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

    # ------------------------------------------------------------------
    # Medidas que se adaptan al ancho del celular
    # ------------------------------------------------------------------
    def ancho_tarjeta():
        ancho = page.width or 360  # aún no medido: se asume un celular
        return max(240, min(380, ancho - 48))

    # ------------------------------------------------------------------
    # Encabezado compacto: logo PlayBar | nombre y teléfono | logo del lugar
    # ------------------------------------------------------------------
    def cerrar_sesion(e):

        eliminar_sesion(page)

        from views.codigo import codigo_view

        codigo_view(page)

    logo_playbar = ft.Image(
        src="/logohallowen.png",
        height=56,
        fit=ft.BoxFit.CONTAIN,
    )

    logo_local = (
        ft.Image(src=f"logos/{logo_url}", height=56, fit=ft.BoxFit.CONTAIN)
        if logo_url else ft.Container(width=0)
    )

    encabezado = ft.Container(
        width=ancho_tarjeta() + 20,
        padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        border_radius=18,
        bgcolor="#0b1220",
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                logo_playbar,
                ft.Column(
                    spacing=0,
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(
                            cliente,
                            size=18,
                            color="white",
                            weight=ft.FontWeight.BOLD,
                            max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Text(
                            f"👤 {telefono}",
                            size=12,
                            color="#94a3b8",
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.TextButton(
                            "Cerrar sesión",
                            on_click=cerrar_sesion,
                            style=ft.ButtonStyle(color="#64748b", padding=0),
                        ),
                    ],
                ),
                logo_local,
            ],
        ),
    )

    # ------------------------------------------------------------------
    # Última canción agregada (solo aparece cuando ya agregó una)
    # ------------------------------------------------------------------
    ultima_cancion_text = ft.Text(
        "",
        color="#22d3ee",
        size=14,
        text_align=ft.TextAlign.CENTER,
        max_lines=2,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    ultima_cancion = ft.Container(
        visible=False,
        width=ancho_tarjeta() + 20,
        padding=10,
        border_radius=12,
        bgcolor="#0b1220",
        content=ft.Column(
            spacing=2,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            controls=[
                ft.Text("🎵 Última canción agregada", color="#94a3b8", size=12),
                ultima_cancion_text,
            ],
        ),
    )

    # ------------------------------------------------------------------
    # Buscador + estado de la búsqueda
    # ------------------------------------------------------------------
    estado_ring = ft.ProgressRing(width=22, height=22, stroke_width=3, color=CYAN, visible=False)
    estado_texto = ft.Text("", size=14, color="#94a3b8", text_align=ft.TextAlign.CENTER)
    estado_busqueda = ft.Container(
        visible=False,
        width=ancho_tarjeta() + 20,
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        border_radius=12,
        bgcolor="#0b1220",
        content=ft.Row(
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            controls=[estado_ring, ft.Container(content=estado_texto, expand=True)],
        ),
    )

    resultados = ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        key=ft.ScrollKey(CLAVE_RESULTADOS),
    )

    buscando = {"activo": False}

    def mostrar_estado(texto, cargando=False, visible=True):
        estado_texto.value = texto
        estado_ring.visible = cargando
        estado_busqueda.visible = visible
        page.update()

    def bajar_a_resultados():
        """En el celular, lleva la pantalla a los resultados."""
        async def _ir():
            try:
                await page.scroll_to(scroll_key=CLAVE_RESULTADOS, duration=350)
            except Exception as ex:
                print("ℹ️ No se pudo desplazar a los resultados:", ex)

        try:
            page.run_task(_ir)
        except Exception as ex:
            print("ℹ️ scroll a resultados:", ex)

    def construir_tarjeta(item):
        titulo = item["snippet"]["title"]
        canal = item["snippet"]["channelTitle"]
        miniaturas = item["snippet"]["thumbnails"]
        thumbnail = (miniaturas.get("high") or miniaturas.get("medium") or miniaturas.get("default"))["url"]
        ancho = ancho_tarjeta()

        return ft.Container(
            margin=ft.Margin.symmetric(horizontal=0, vertical=6),
            padding=10,
            border_radius=15,
            bgcolor="#111827",
            on_click=lambda e, item=item: abrir_confirmacion(item),
            content=ft.Column(
                spacing=4,
                controls=[
                    ft.Image(
                        src=thumbnail,
                        width=ancho,
                        height=int(ancho * 9 / 16),
                        fit=ft.BoxFit.COVER,
                        border_radius=10,
                    ),
                    ft.Container(width=ancho,
                                 content=ft.Text(titulo, color="white", size=15,
                                                 weight=ft.FontWeight.BOLD)),
                    ft.Text(canal, color="#94a3b8", size=13),
                ],
            ),
        )

    def buscar(e):
        if buscando["activo"]:
            return
        texto = (buscador.value or "").strip()
        if len(texto) < 3:
            resultados.controls.clear()
            mostrar_estado("Escribe al menos 3 letras para buscar", visible=True)
            return

        buscando["activo"] = True
        boton_buscar.disabled = True
        buscador.disabled = True
        resultados.controls.clear()
        mostrar_estado(f"Buscando “{texto}”…", cargando=True)

        try:
            data = buscar_canciones(texto)
            items = data.get("items", [])
        except Exception as ex:
            print("❌ Error buscando:", ex)
            items = []
            data = None

        try:
            for item in items:
                resultados.controls.append(construir_tarjeta(item))

            if data is None:
                mostrar_estado("No se pudo buscar ahora. Intenta de nuevo.", visible=True)
            elif not items:
                mostrar_estado(f"No encontramos resultados para “{texto}”. Prueba con otro nombre.")
            else:
                mostrar_estado(
                    f"{len(items)} {'resultado' if len(items) == 1 else 'resultados'}"
                    " · toca una canción para agregarla"
                )
                bajar_a_resultados()
        finally:
            buscando["activo"] = False
            boton_buscar.disabled = False
            buscador.disabled = False
            page.update()

    buscador = ft.TextField(
        hint_text="Canción o artista",
        expand=True,
        height=56,
        border_radius=15,
        bgcolor="#1A1A1A",
        color="white",
        border_color=CYAN,
        focused_border_color=VIOLETA,
        cursor_color=CYAN,
        text_style=ft.TextStyle(color="white", size=17),
        hint_style=ft.TextStyle(color="#94A3B8"),
        on_submit=buscar,  # el botón "Ir" del teclado del celular también busca
    )

    boton_buscar = ft.IconButton(
        icon=ft.Icons.SEARCH,
        icon_color="white",
        icon_size=26,
        width=56,
        height=56,
        bgcolor=VIOLETA,
        tooltip="Buscar",
        on_click=buscar,
    )

    barra_busqueda = ft.Container(
        width=ancho_tarjeta() + 20,
        content=ft.Row(spacing=8, controls=[buscador, boton_buscar]),
    )

    # ------------------------------------------------------------------
    # Avisos con botón Aceptar
    # ------------------------------------------------------------------
    def mostrar_aviso(titulo, mensaje, color):
        def cerrar(ev):
            aviso.open = False
            try:
                page.overlay.remove(aviso)
            except ValueError:
                pass
            page.update()

        boton_ok, _ = _boton("Aceptar", cerrar, ancho=140)
        aviso = ft.AlertDialog(
            modal=True,
            bgcolor="#111827",
            title=ft.Text(titulo, color=color),
            content=ft.Text(mensaje, color="white"),
            actions=[boton_ok],
            actions_alignment=ft.MainAxisAlignment.CENTER,
        )
        page.overlay.append(aviso)
        aviso.open = True
        page.update()

    def confirmar(item, ventana, aviso_progreso):
        """Envía la canción; el diálogo queda abierto mostrando 'Agregando…'."""
        titulo_cancion = item["snippet"]["title"]

        def enviar_cancion():
            try:
                resultado = agregar_cancion(
                    cliente=codigo,
                    telefono=telefono,
                    titulo=titulo_cancion,
                    canal=item["snippet"]["channelTitle"],
                    video_id=item["id"]["videoId"]
                )
            except Exception as ex:
                resultado = {"ok": False, "error": str(ex)}

            ventana.open = False
            page.update()

            if resultado.get("ok") and resultado.get("duplicado"):
                mostrar_aviso(
                    "ℹ️ Ya está en la cola",
                    titulo_cancion + "\n\nYa la pidieron y está esperando su turno.",
                    "#facc15",
                )
            elif resultado.get("ok"):
                ultima_cancion_text.value = titulo_cancion
                ultima_cancion.visible = True
                mostrar_aviso("✅ Canción agregada", titulo_cancion, "#22d3ee")
            else:
                print("❌ No se pudo agregar:", resultado)
                mostrar_aviso(
                    "❌ No se pudo agregar",
                    "Intenta de nuevo en unos segundos.",
                    "#f87171",
                )

        threading.Thread(target=enviar_cancion, daemon=True).start()

    def abrir_confirmacion(item):
        # Evita que varios clics rápidos abran varios diálogos a la vez.
        page.overlay.clear()

        procesando = {"valor": False}

        def cancelar_dialogo(ev):
            if procesando["valor"]:
                return
            confirmacion.open = False
            page.update()

        def aceptar_dialogo(ev):
            # Bloqueo inmediato: el primer clic desactiva Aceptar, así un
            # doble clic no puede disparar dos solicitudes.
            if procesando["valor"]:
                return
            procesando["valor"] = True
            boton_aceptar_btn.disabled = True
            boton_cancelar_btn.disabled = True
            progreso.visible = True
            page.update()
            confirmar(item, confirmacion, progreso)

        boton_aceptar, boton_aceptar_btn = _boton("Aceptar", aceptar_dialogo)
        boton_cancelar, boton_cancelar_btn = _boton("Cancelar", cancelar_dialogo)

        progreso = ft.Row(
            visible=False,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
            controls=[
                ft.ProgressRing(width=20, height=20, stroke_width=3, color=CYAN),
                ft.Text("Agregando…", color="#94a3b8"),
            ],
        )

        confirmacion = ft.AlertDialog(
            modal=True,
            bgcolor="#111827",
            title=ft.Text("¿Deseas agregar esta canción?", color="white"),
            content=ft.Column(
                tight=True,
                controls=[
                    ft.Text(item["snippet"]["title"], color="#22d3ee"),
                    progreso,
                ],
            ),
            actions=[
                ft.Row(
                    controls=[boton_cancelar, boton_aceptar],
                    width=280,
                    spacing=15,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            ],
        )

        page.overlay.append(confirmacion)
        confirmacion.open = True
        page.update()

    # ------------------------------------------------------------------
    # Pantalla
    # ------------------------------------------------------------------
    page.add(
        ft.Container(
            expand=True,
            padding=ft.Padding.symmetric(horizontal=8, vertical=8),
            content=ft.Column(
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=10,
                controls=[
                    encabezado,
                    ultima_cancion,
                    barra_busqueda,
                    estado_busqueda,
                    resultados,
                ],
            ),
        )
    )

    page.update()
