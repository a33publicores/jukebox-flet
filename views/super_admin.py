"""
Panel del SUPER ADMINISTRADOR de PlayBar GO (app web).

Entrada oculta: tocar 5 veces seguidas el logo de la pantalla del código, o abrir
la dirección  /super  de la app. Usuario y clave: variables SUPERADMIN_USER y
SUPERADMIN_PASS de Railway (o un admin con rol "super" creado aquí mismo).

Desde aquí se hace todo lo que antes se hacía a mano en Google Sheets:
    * crear y editar negocios (código, nombre, logo, playlist, activo)
    * ver / copiar / regenerar la LLAVE del reproductor de cada negocio
    * crear administradores de cada negocio (usuario y clave) y super admins
    * ver los pedidos de cada negocio y descargarlos en Excel
"""
import asyncio
import os
import time

import flet as ft

from services import db
from services import playbar_service as ps
from services.exportar import fecha_local

CYAN = "#00D4FF"
VIOLETA = "#B44CFF"
FONDO = "#020617"
PANEL = "#0f172a"
API_URL = os.getenv("PLAYBAR_API_URL", "").strip().rstrip("/")
_intentos = {"n": 0, "hasta": 0.0}
_sesiones_super = set()  # páginas (pestañas) que ya entraron como super admin


# ---------------------------------------------------------------------------
# Piezas
# ---------------------------------------------------------------------------
def _boton(texto, on_click, ancho=None, alto=44, apagado=False):
    return ft.Container(
        width=ancho, height=alto, border_radius=14,
        padding=ft.Padding.symmetric(horizontal=14),
        gradient=None if apagado else ft.LinearGradient(colors=[CYAN, VIOLETA]),
        bgcolor="#1e293b" if apagado else None,
        content=ft.TextButton(
            content=ft.Text(texto, color="white", weight=ft.FontWeight.BOLD, size=14),
            on_click=on_click,
        ),
    )


def _aviso(page, texto, error=False):
    page.show_dialog(ft.SnackBar(
        content=ft.Text(texto, color="white"), bgcolor="#7f1d1d" if error else "#14532d",
    ))


def _campo(etiqueta, valor="", clave=False, ancho=340, numeros=False, disabled=False):
    return ft.TextField(
        label=etiqueta, value=str(valor or ""), width=ancho, color="white",
        border_color=CYAN, password=clave, can_reveal_password=clave, disabled=disabled,
        input_filter=ft.NumbersOnlyInputFilter() if numeros else None,
        keyboard_type=ft.KeyboardType.NUMBER if numeros else None,
        autocorrect=False, enable_suggestions=False,
        capitalization=ft.TextCapitalization.NONE,
    )


def _cerrar_dialogo(page):
    try:
        page.pop_dialog()
    except Exception:
        pass


def _dialogo(page, titulo, controles, acciones):
    page.show_dialog(ft.AlertDialog(
        modal=True, bgcolor="#111827",
        title=ft.Text(titulo, color="#22d3ee", weight=ft.FontWeight.BOLD),
        content=ft.Column(controles, tight=True, spacing=12, width=360, scroll=ft.ScrollMode.AUTO),
        actions=acciones,
    ))


def _encabezado(page, titulo, volver=None):
    fila = [ft.Text(titulo, size=22, color="white", weight=ft.FontWeight.BOLD, expand=True)]
    if volver:
        fila.insert(0, ft.IconButton(icon=ft.Icons.ARROW_BACK, icon_color="white",
                                     on_click=lambda e: volver(page), tooltip="Volver"))
    return ft.Row(fila, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _preparar(page):
    page.clean()
    page.bgcolor = FONDO
    page.scroll = ft.ScrollMode.AUTO
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START


# ---------------------------------------------------------------------------
# Entrada
# ---------------------------------------------------------------------------
def super_login_view(page):
    _preparar(page)
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    usuario = _campo("Usuario")
    clave = _campo("Clave", clave=True)
    error = ft.Text("", color="#f87171")

    def entrar(e):
        if time.time() < _intentos["hasta"]:
            error.value = "Demasiados intentos. Espera un minuto."
            page.update()
            return
        try:
            ok = db.validar_super(usuario.value, clave.value)
        except Exception as ex:
            error.value = f"No se pudo conectar con la base: {ex}"
            page.update()
            return
        if ok:
            _intentos["n"] = 0
            _sesiones_super.add(id(page))
            super_inicio(page)
            return
        _intentos["n"] += 1
        if _intentos["n"] >= 5:
            _intentos.update(n=0, hasta=time.time() + 60)
        error.value = "Usuario o clave incorrectos"
        clave.value = ""
        page.update()

    def volver(e):
        from views.codigo import codigo_view
        codigo_view(page)

    usuario.on_submit = lambda e: clave.focus()
    clave.on_submit = entrar
    page.add(ft.Column([
        ft.Text("👑", size=48),
        ft.Text("Super administrador", size=26, color="white", weight=ft.FontWeight.BOLD),
        ft.Text("PlayBar GO", color="#94A3B8"),
        ft.Container(height=10), usuario, clave, error,
        _boton("Entrar", entrar, ancho=220),
        ft.TextButton("← Volver", on_click=volver),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=10))
    page.update()


def _es_super(page):
    return id(page) in _sesiones_super


# ---------------------------------------------------------------------------
# Negocios
# ---------------------------------------------------------------------------
def super_inicio(page):
    if not _es_super(page):
        return super_login_view(page)
    _preparar(page)
    try:
        negocios = db.clientes()
    except Exception as ex:
        page.add(ft.Text(f"No se pudo leer la base: {ex}", color="#f87171"))
        page.update()
        return

    def salir(e):
        _sesiones_super.discard(id(page))
        from views.codigo import codigo_view
        codigo_view(page)

    def tarjeta(c):
        def cambiar_activo(e):
            db.guardar_cliente(c["codigo"], c["nombre"], c["logo"], c["playlist"], e.control.value)
            ps.olvidar_cliente(c["codigo"])
            _aviso(page, f"{c['nombre']}: {'activo' if e.control.value else 'inactivo'}")

        return ft.Container(
            width=520, padding=14, border_radius=16, bgcolor=PANEL,
            border=ft.Border.all(1, "#1e293b"),
            content=ft.Column([
                ft.Row([
                    ft.Column([
                        ft.Text(c["nombre"], size=18, color="white", weight=ft.FontWeight.BOLD),
                        ft.Text(f"Código {c['codigo']}" + (" · playlist ✔" if c["playlist"] else ""),
                                color="#94A3B8", size=13),
                    ], spacing=2, expand=True),
                    ft.Switch(value=bool(c["activo"]), active_color=CYAN, on_change=cambiar_activo,
                              label="Activo"),
                ]),
                ft.Row([
                    ft.OutlinedButton("Editar", icon=ft.Icons.EDIT,
                                      on_click=lambda e: _form_negocio(page, c)),
                    ft.OutlinedButton("Llave", icon=ft.Icons.KEY,
                                      on_click=lambda e: _ver_llave(page, c)),
                    ft.OutlinedButton("Admins", icon=ft.Icons.PEOPLE,
                                      on_click=lambda e: admins_view(page, c)),
                    ft.OutlinedButton("Pedidos", icon=ft.Icons.TABLE_CHART,
                                      on_click=lambda e: pedidos_view(page, c)),
                ], wrap=True, spacing=8, run_spacing=8),
            ], spacing=10),
        )

    page.add(ft.Container(width=560, padding=16, content=ft.Column([
        _encabezado(page, "👑 Super administrador"),
        ft.Row([
            _boton("➕ Nuevo negocio", lambda e: _form_negocio(page)),
            _boton("👥 Super admins", lambda e: admins_view(page, None), apagado=True),
            _boton("Salir", salir, apagado=True),
        ], wrap=True, spacing=8, run_spacing=8),
        ft.Text(f"{len(negocios)} negocios", color="#94A3B8"),
        *[tarjeta(c) for c in negocios],
    ], spacing=14)))
    page.update()


def _form_negocio(page, c=None):
    nuevo = c is None
    codigo = _campo("Código del lugar (solo números)", "" if nuevo else c["codigo"],
                    numeros=True, disabled=not nuevo)
    nombre = _campo("Nombre del negocio", "" if nuevo else c["nombre"])
    logo = _campo("Logo (dirección de imagen, opcional)", "" if nuevo else c["logo"])
    playlist = _campo("Playlist de YouTube para el aleatorio (enlace o ID)",
                      "" if nuevo else c["playlist"])
    activo = ft.Switch(value=True if nuevo else bool(c["activo"]), label="Activo",
                       active_color=CYAN)
    error = ft.Text("", color="#f87171")

    def guardar(e):
        cod = (codigo.value or "").strip()
        if not cod.isdigit() or len(cod) < 3:
            error.value = "El código debe tener al menos 3 números."
            page.update()
            return
        if not (nombre.value or "").strip():
            error.value = "Escribe el nombre del negocio."
            page.update()
            return
        if nuevo and db.cliente(cod):
            error.value = f"El código {cod} ya existe."
            page.update()
            return
        fila = db.guardar_cliente(cod, nombre.value, logo.value, playlist.value, activo.value)
        ps.olvidar_cliente(cod)
        _cerrar_dialogo(page)
        super_inicio(page)
        if nuevo:
            _ver_llave(page, fila, recien=True)
        else:
            _aviso(page, "Negocio guardado")

    _dialogo(page, "Nuevo negocio" if nuevo else f"Editar {c['nombre']}",
             [codigo, nombre, logo, playlist, activo, error],
             [ft.TextButton("Cancelar", on_click=lambda e: _cerrar_dialogo(page)),
              ft.FilledButton("Guardar", on_click=guardar)])


def _ver_llave(page, c, recien=False):
    c = db.cliente(c["codigo"]) or c
    texto = ft.Text(c["llave"], selectable=True, color="white", size=15, weight=ft.FontWeight.BOLD)

    async def copiar(e):
        try:
            await ft.Clipboard().set(texto.value)
            _aviso(page, "Llave copiada")
        except Exception as ex:
            _aviso(page, f"No se pudo copiar: {ex}", error=True)

    def regenerar(e):
        fila = db.regenerar_llave(c["codigo"])
        texto.value = fila["llave"]
        aviso.value = "Llave nueva creada: la anterior YA NO sirve. Escríbela en el reproductor del bar."
        aviso.color = "#facc15"
        page.update()

    aviso = ft.Text(
        "Negocio creado. Esta es la llave para instalar su reproductor." if recien else
        "Se escribe en el reproductor del bar junto con el código.",
        color="#94A3B8", size=13,
    )
    _dialogo(page, f"🔑 Llave de {c['nombre']}", [
        ft.Text(f"Código del lugar: {c['codigo']}", color="white"),
        ft.Container(padding=12, border_radius=10, bgcolor="#0b1220", content=texto),
        aviso,
        ft.Text("Si un PC se pierde o alguien más tiene la llave, usa Regenerar.",
                color="#64748b", size=12),
    ], [
        ft.TextButton("Regenerar", on_click=regenerar),
        ft.OutlinedButton("Copiar", icon=ft.Icons.CONTENT_COPY, on_click=copiar),
        ft.FilledButton("Listo", on_click=lambda e: _cerrar_dialogo(page)),
    ])


# ---------------------------------------------------------------------------
# Administradores
# ---------------------------------------------------------------------------
def admins_view(page, c):
    """c = negocio, o None para los super administradores."""
    if not _es_super(page):
        return super_login_view(page)
    _preparar(page)
    super_ = c is None
    codigo = "*" if super_ else c["codigo"]
    titulo = "👥 Super administradores" if super_ else f"👥 Admins de {c['nombre']}"
    lista = [a for a in db.admins(codigo) if (a["rol"] == "super") == super_]

    def recargar():
        admins_view(page, c)

    def fila(a):
        def activo(e):
            db.cambiar_admin(a["id"], activo=e.control.value)
            _aviso(page, f"{a['usuario']}: {'activo' if e.control.value else 'desactivado'}")

        def cambiar_clave(e):
            nueva = _campo("Clave nueva", clave=True)

            def ok(ev):
                if len((nueva.value or "").strip()) < 4:
                    return
                db.cambiar_admin(a["id"], clave=nueva.value.strip())
                _cerrar_dialogo(page)
                _aviso(page, "Clave cambiada")

            _dialogo(page, f"Clave de {a['usuario']}", [nueva],
                     [ft.TextButton("Cancelar", on_click=lambda ev: _cerrar_dialogo(page)),
                      ft.FilledButton("Guardar", on_click=ok)])

        def borrar(e):
            def si(ev):
                db.borrar_admin(a["id"])
                _cerrar_dialogo(page)
                recargar()

            _dialogo(page, f"¿Borrar a {a['usuario']}?", [ft.Text("No se puede deshacer.",
                                                                    color="white")],
                     [ft.TextButton("Cancelar", on_click=lambda ev: _cerrar_dialogo(page)),
                      ft.FilledButton("Borrar", on_click=si)])

        return ft.Container(
            width=520, padding=12, border_radius=14, bgcolor=PANEL,
            content=ft.Row([
                ft.Column([ft.Text(a["usuario"], color="white", size=16, weight=ft.FontWeight.BOLD),
                           ft.Text(a["nota"] or a["rol"], color="#94A3B8", size=12)],
                          spacing=2, expand=True),
                ft.Switch(value=bool(a["activo"]), active_color=CYAN, on_change=activo),
                ft.IconButton(icon=ft.Icons.KEY, icon_color="#cbd5e1", tooltip="Cambiar clave",
                              on_click=cambiar_clave),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#f87171", tooltip="Borrar",
                              on_click=borrar),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    usuario = _campo("Usuario", ancho=250)
    clave = _campo("Clave (mínimo 4)", clave=True, ancho=250)
    nota = _campo("Nota (ej. encargado de noche)", ancho=250)
    error = ft.Text("", color="#f87171")

    def agregar(e):
        u, k = (usuario.value or "").strip(), (clave.value or "").strip()
        if not u or len(k) < 4:
            error.value = "Escribe el usuario y una clave de mínimo 4 caracteres."
            page.update()
            return
        if any(a["usuario"].lower() == u.lower() for a in lista):
            error.value = "Ese usuario ya existe aquí."
            page.update()
            return
        db.agregar_admin(codigo, u, k, rol="super" if super_ else "admin", nota=nota.value)
        recargar()
        _aviso(page, f"Administrador {u} creado")

    page.add(ft.Container(width=560, padding=16, content=ft.Column([
        _encabezado(page, titulo, volver=super_inicio),
        ft.Text("Entran al panel de administrador del bar desde la app (🔧 Administrador)."
                if not super_ else "Entran a este panel de super administrador.",
                color="#94A3B8", size=13),
        *([fila(a) for a in lista] or [ft.Text("Todavía no hay ninguno.", color="#94A3B8")]),
        ft.Divider(color="#1e293b"),
        ft.Text("Agregar", color="white", weight=ft.FontWeight.BOLD),
        usuario, clave, nota, error,
        _boton("➕ Agregar", agregar, ancho=200),
    ], spacing=12)))
    page.update()


# ---------------------------------------------------------------------------
# Pedidos (lo que antes se veía en la pestaña de cada bar)
# ---------------------------------------------------------------------------
def pedidos_view(page, c, dias=1):
    if not _es_super(page):
        return super_login_view(page)
    _preparar(page)
    desde = ps.inicio_jornada() - (dias - 1) * 86400 if dias > 0 else 0
    filas = db.tabla(c["codigo"], desde, 1500)
    total = db.contar_pedidos(c["codigo"])

    def filtro(t, d):
        sel = d == dias
        return ft.Container(
            padding=ft.Padding.symmetric(horizontal=14, vertical=6), border_radius=14,
            bgcolor=CYAN if sel else "#1e293b",
            content=ft.Text(t, color=FONDO if sel else "white", size=13),
            on_click=lambda e: pedidos_view(page, c, d),
        )

    async def excel(e):
        if not API_URL:
            _aviso(page, "Falta la variable PLAYBAR_API_URL en Railway (dirección de la API).", True)
            return
        token = await asyncio.to_thread(db.crear_descarga, c["codigo"])
        await ft.UrlLauncher().launch_url(f"{API_URL}/api/v1/excel?t={token}")

    tabla = ft.DataTable(
        columns=[ft.DataColumn(label=ft.Text(t, color="white", weight=ft.FontWeight.BOLD))
                 for t in ("Fecha y hora", "Usuario", "Canción", "Estado", "Estado2")],
        rows=[ft.DataRow(cells=[
            ft.DataCell(content=ft.Text(fecha_local(f["ts"]), size=12, color="#cbd5e1")),
            ft.DataCell(content=ft.Text(f["usuario"], size=12, color="#cbd5e1")),
            ft.DataCell(content=ft.Text(f["titulo"], size=12, color="white", width=320,
                                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)),
            ft.DataCell(content=ft.Text(f["estado"], size=12, color="#94A3B8")),
            ft.DataCell(content=ft.Text(f["estado2"], size=12, color="#94A3B8")),
        ]) for f in filas],
        heading_row_color="#0b1220", column_spacing=16, data_row_min_height=32,
        data_row_max_height=44, horizontal_lines=ft.BorderSide(1, "#1e293b"),
    )
    page.add(ft.Container(padding=16, content=ft.Column([
        _encabezado(page, f"📋 Pedidos de {c['nombre']}", volver=super_inicio),
        ft.Row([filtro("Hoy", 1), filtro("7 días", 7), filtro("30 días", 30), filtro("Todo", 0)],
               wrap=True, spacing=6),
        ft.Row([ft.Text(f"{len(filas)} en este filtro · {total} en total", color="#94A3B8"),
                ft.OutlinedButton("Descargar Excel (todo)", icon=ft.Icons.DOWNLOAD,
                                  on_click=excel)], wrap=True, spacing=12),
        ft.Row([tabla], scroll=ft.ScrollMode.AUTO),
    ], spacing=12)))
    page.update()
