"""
Lista desplegable con selección múltiple (panel del administrador: géneros y artistas).

Cerrada ocupa una línea con el resumen; al tocarla se abre debajo con casillas. Lo que se
marca queda en "borrador" hasta tocar ✔ Aplicar (ahí se guarda y se cierra); Cancelar deja
todo como estaba. Cada toque actualiza SOLO esta lista (no la página entera): así responde
rápido aunque el panel tenga una cola larga.
"""
import unicodedata

import flet as ft

MAX_FILAS = 80  # con buscador: se muestran las primeras que coincidan


def _sin_tildes(texto):
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def selector(todos_txt, elegidos, al_aplicar, buscador=False, ancho=320, vacio_txt=""):
    """`elegidos`: set de claves (se modifica al aplicar). `al_aplicar()` se llama después.
    Devuelve (control, poner_opciones) — poner_opciones([(clave, nombre, cantidad), ...])."""
    estado = {"abierta": False, "opciones": [], "filtro": ""}
    borrador = set(elegidos)

    resumen = ft.Text("", color="white", size=14, expand=True,
                      overflow=ft.TextOverflow.ELLIPSIS, max_lines=1)
    flecha = ft.Icon(ft.Icons.ARROW_DROP_DOWN, color="white")
    filas = ft.Column(spacing=0, tight=True, scroll=ft.ScrollMode.AUTO)
    caja_filas = ft.Container(content=filas)
    campo = ft.TextField(
        hint_text="Buscar…", dense=True, height=44, width=ancho - 24, color="white",
        border_color="#334155", focused_border_color="#00D4FF", cursor_color="#00D4FF",
        hint_style=ft.TextStyle(color="#64748b"), prefix_icon=ft.Icons.SEARCH,
        visible=buscador)

    def nombres_elegidos():
        nombres = {k: n for k, n, _ in estado["opciones"]}
        return [nombres.get(k, k) for k in sorted(elegidos, key=lambda k: nombres.get(k, k))]

    def pintar():
        def fila(clave, nombre, n):
            activo = (clave in borrador) if clave else not borrador
            return ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=8), ink=True,
                bgcolor="#0e7490" if activo else None,
                on_click=lambda e, k=clave: tocar(k),
                content=ft.Row(spacing=10, controls=[
                    ft.Icon(ft.Icons.CHECK_BOX if activo else ft.Icons.CHECK_BOX_OUTLINE_BLANK,
                            color="white" if activo else "#00D4FF", size=20),
                    ft.Text(nombre, color="white", size=14, expand=True,
                            weight=ft.FontWeight.BOLD if activo else None),
                    ft.Text(str(n) if n else "", color="#CBD5E1", size=13),
                ]))

        filtro = _sin_tildes(estado["filtro"]).strip()
        visibles = [o for o in estado["opciones"]
                    if not filtro or filtro in _sin_tildes(o[1]) or o[0] in borrador]
        controles = [fila("", todos_txt, sum(o[2] or 0 for o in estado["opciones"]))]
        controles += [fila(*o) for o in visibles[:MAX_FILAS]]
        if not estado["opciones"] and vacio_txt:
            controles.append(ft.Container(padding=12, content=ft.Text(
                vacio_txt, color="#94A3B8", size=13)))
        elif filtro and not visibles:
            controles.append(ft.Container(padding=12, content=ft.Text(
                "Nada coincide con la búsqueda.", color="#94A3B8", size=13)))
        filas.controls = controles
        caja_filas.height = min(340, 40 * len(controles) + 4)
        panel.visible = estado["abierta"]
        flecha.icon = ft.Icons.ARROW_DROP_UP if estado["abierta"] else ft.Icons.ARROW_DROP_DOWN
        resumen.value = ", ".join(nombres_elegidos()) if elegidos else todos_txt

    def refrescar():
        pintar()
        try:
            control.update()
        except Exception:
            pass  # todavía no está en pantalla

    def abrir(e=None):
        estado["abierta"] = not estado["abierta"]
        borrador.clear()
        borrador.update(elegidos)
        estado["filtro"] = campo.value = ""
        refrescar()

    def tocar(clave):
        if not clave:
            borrador.clear()
        elif clave in borrador:
            borrador.discard(clave)
        else:
            borrador.add(clave)
        refrescar()

    def buscar(e):
        estado["filtro"] = campo.value or ""
        refrescar()

    def aplicar(e=None):
        elegidos.clear()
        elegidos.update(borrador)
        estado["abierta"] = False
        refrescar()
        al_aplicar()

    campo.on_change = buscar
    panel = ft.Container(
        visible=False, width=ancho, bgcolor="#1e293b", border_radius=12,
        border=ft.Border.all(1, "#334155"), padding=ft.Padding.symmetric(vertical=6),
        content=ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            campo,
            caja_filas,
            ft.Row(alignment=ft.MainAxisAlignment.CENTER, spacing=10, controls=[
                ft.TextButton(content=ft.Text("Cancelar", color="#CBD5E1", size=14),
                              on_click=abrir),
                ft.Container(
                    width=150, height=40, border_radius=12,
                    gradient=ft.LinearGradient(colors=["#00D4FF", "#B44CFF"]),
                    content=ft.TextButton(
                        content=ft.Text("✔ Aplicar", color="white", size=15,
                                        weight=ft.FontWeight.BOLD),
                        on_click=aplicar)),
            ]),
        ]))
    control = ft.Column(spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER, controls=[
        ft.Container(
            width=ancho, bgcolor="#0f172a", border_radius=12, border=ft.Border.all(1, "#334155"),
            padding=ft.Padding.symmetric(horizontal=14, vertical=10), ink=True,
            on_click=abrir,
            content=ft.Row([resumen, flecha], spacing=6)),
        panel,
    ])

    def poner_opciones(opciones):
        estado["opciones"] = list(opciones)
        refrescar()

    pintar()
    return control, poner_opciones
