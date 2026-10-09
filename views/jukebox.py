import asyncio
import threading

import flet as ft

from services.playbar_service import buscar as buscar_canciones, agregar_cancion
from services.session_manager import cerrar_sesion as eliminar_sesion

CYAN = "#00D4FF"
VIOLETA = "#B44CFF"


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
    logo_url,
    es_admin=False,
):

    page.clean()

    page.bgcolor = "#020617"

    page.scroll = None  # solo los resultados se desplazan; el encabezado queda fijo
    page.padding = 0
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

    def volver_admin(e):
        from services.session_manager import guardar_sesion
        from views.admin import admin_view
        guardar_sesion(page, {"codigo": codigo, "cliente": cliente, "logo": logo_url,
                              "telefono": "ADMIN", "modo": "admin"}, rol="admin")
        admin_view(page, codigo, cliente, logo_url)

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
                            ("🔧 Administrador" if es_admin else f"👤 {telefono}"),
                            size=12,
                            color="#94a3b8",
                            text_align=ft.TextAlign.CENTER,
                        ),
                        ft.Container(height=6),
                        (_boton("🔧 Volver al panel", volver_admin, ancho=170, alto=36)[0]
                         if es_admin else
                         _boton("Cerrar sesión", cerrar_sesion, ancho=150, alto=36)[0]),
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
        scroll=ft.ScrollMode.AUTO,
        expand=True,
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
                await resultados.scroll_to(offset=0, duration=300)
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
        # "medium" (320x180) pesa ~4 veces menos que "high": 50 resultados cargan rápido
        thumbnail = (miniaturas.get("medium") or miniaturas.get("high") or miniaturas.get("default"))["url"]
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
        texto_ = (buscador.value or "").strip()
        if len(texto_) >= 3:
            # Marca "buscando" ya (evita toques repetidos) y avisa al instante;
            # la búsqueda en sí corre en segundo plano para que la pantalla
            # alcance a pintar "Buscando…" antes de esperar a YouTube.
            buscando["activo"] = True
            boton_buscar.visible = False
            ring_boton.visible = True
            buscador.disabled = True
            resultados.controls.clear()
            mostrar_estado(f"🔎 Buscando “{texto_}”…", cargando=True)
            threading.Thread(target=_buscar_en_segundo_plano, args=(texto_,), daemon=True).start()
            return
        resultados.controls.clear()
        mostrar_estado("Escribe al menos 3 letras para buscar", visible=True)

    def _buscar_en_segundo_plano(texto):
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
            boton_buscar.visible = True
            ring_boton.visible = False
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

    ring_boton = ft.Container(
        visible=False,
        width=56,
        height=56,
        border_radius=28,
        bgcolor=VIOLETA,
        alignment=ft.Alignment.CENTER,
        content=ft.ProgressRing(width=24, height=24, stroke_width=3, color="white"),
    )

    barra_busqueda = ft.Container(
        width=ancho_tarjeta() + 20,
        content=ft.Row(spacing=8, controls=[buscador, boton_buscar, ring_boton]),
    )

    # ------------------------------------------------------------------
    # Agregar canción: UN solo diálogo que cambia de estado
    #   ¿Deseas agregar?  ->  Agregando…  ->  ✅ Agregada / ℹ️ Ya está / ❌ Error
    # (antes se cerraba uno y se abría otro al mismo tiempo, y en el celular la
    #  pantalla quedaba oscura y bloqueada en "Aceptar")
    # ------------------------------------------------------------------
    dialogo_abierto = {"valor": False}

    def _cerrar_dialogo(dlg):
        dialogo_abierto["valor"] = False
        try:
            page.pop_dialog()
        except Exception:
            dlg.open = False
            page.update()

    def abrir_confirmacion(item):
        if dialogo_abierto["valor"]:  # varios toques rápidos: un solo diálogo
            return
        dialogo_abierto["valor"] = True
        titulo_cancion = item["snippet"]["title"]
        estado = {"enviando": False}

        texto_titulo = ft.Text("¿Deseas agregar esta canción?", color="white")
        texto_cancion = ft.Text(titulo_cancion, color="#22d3ee")
        texto_detalle = ft.Text("", color="white", visible=False)
        progreso = ft.Row(
            visible=False,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=10,
            controls=[
                ft.ProgressRing(width=20, height=20, stroke_width=3, color=CYAN),
                ft.Text("Agregando…", color="#94a3b8"),
            ],
        )

        def cancelar(ev):
            if not estado["enviando"]:
                _cerrar_dialogo(confirmacion)

        def listo(ev):
            _cerrar_dialogo(confirmacion)

        async def aceptar(ev):
            if estado["enviando"]:  # doble toque: una sola solicitud
                return
            estado["enviando"] = True
            boton_aceptar_btn.disabled = True
            boton_cancelar_btn.disabled = True
            progreso.visible = True
            page.update()
            try:
                resultado = await asyncio.wait_for(asyncio.to_thread(
                    agregar_cancion,
                    cliente=codigo,
                    telefono=telefono,
                    titulo=titulo_cancion,
                    canal=item["snippet"]["channelTitle"],
                    video_id=item["id"]["videoId"],
                ), timeout=25)
            except asyncio.TimeoutError:
                resultado = {"ok": False, "error": "tiempo agotado"}
            except Exception as ex:
                resultado = {"ok": False, "error": str(ex)}

            progreso.visible = False
            texto_detalle.visible = True
            if resultado.get("ok") and resultado.get("duplicado"):
                texto_titulo.value, texto_titulo.color = "ℹ️ Ya está en la cola", "#facc15"
                texto_detalle.value = "Ya la pidieron y está esperando su turno."
            elif resultado.get("ok"):
                texto_titulo.value, texto_titulo.color = "✅ Canción agregada", "#22d3ee"
                texto_detalle.value = "Sonará cuando llegue su turno."
                ultima_cancion_text.value = titulo_cancion
                ultima_cancion.visible = True
            else:
                print("❌ No se pudo agregar:", resultado)
                texto_titulo.value, texto_titulo.color = "❌ No se pudo agregar", "#f87171"
                texto_detalle.value = "Revisa tu internet e intenta de nuevo en unos segundos."
            # el mismo diálogo queda con un solo botón para cerrar
            confirmacion.actions = [ft.Row([boton_listo], alignment=ft.MainAxisAlignment.CENTER)]
            page.update()

        boton_aceptar, boton_aceptar_btn = _boton("Aceptar", aceptar)
        boton_cancelar, boton_cancelar_btn = _boton("Cancelar", cancelar)
        boton_listo, _ = _boton("Aceptar", listo, ancho=140)

        confirmacion = ft.AlertDialog(
            modal=True,
            bgcolor="#111827",
            title=texto_titulo,
            content=ft.Column(tight=True, controls=[texto_cancion, texto_detalle, progreso]),
            actions=[
                ft.Row(
                    controls=[boton_cancelar, boton_aceptar],
                    width=280,
                    spacing=15,
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            ],
            on_dismiss=lambda e: dialogo_abierto.update(valor=False),
        )
        page.show_dialog(confirmacion)

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
                expand=True,
            ),
        )
    )

    page.update()
