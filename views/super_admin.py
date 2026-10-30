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
import re
import time

import flet as ft

from services import db
from services import playbar_service as ps
from services import suscripcion as sus
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
    """Cierra el cuadro de diálogo de arriba. No usa pop_dialog() a secas: si antes salió un
    aviso (SnackBar, p. ej. "Llave copiada"), pop_dialog cerraba el aviso y el cuadro se
    quedaba abierto ("Listo" no cerraba)."""
    try:
        for dlg in reversed(page._dialogs.controls):
            if isinstance(dlg, ft.AlertDialog) and dlg.open:
                dlg.open = False
                dlg.update()
                return
    except Exception:
        pass
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
    """El super administrador entra por el mismo "Iniciar sesión" de todos (/admin)."""
    from views.acceso import acceso_admin_view
    acceso_admin_view(page)


def entrar_como_super(page, usuario):
    _intentos["n"] = 0
    _sesiones_super.add(id(page))
    from services.session_manager import guardar_sesion
    guardar_sesion(page, {"codigo": "*", "telefono": "SUPER", "usuario": usuario}, rol="super")
    super_inicio(page)


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

    async def salir(e):
        _sesiones_super.discard(id(page))
        from services.session_manager import cerrar_sesion
        from views.acceso import ir_a_portada
        cerrar_sesion(page)
        await ir_a_portada()

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
                    ft.Image(src=ps.imagen_logo(c["logo"], c["codigo"]), width=52, height=52,
                             fit=ft.BoxFit.CONTAIN),
                    ft.Column([
                        ft.Text(c["nombre"], size=18, color="white", weight=ft.FontWeight.BOLD),
                        ft.Text(f"Código {c['codigo']}" + (" · playlist ✔" if c["playlist"] else "")
                                + f" · 📺 {int(c.get('televisores') or 1)} TV",
                                color="#94A3B8", size=13),
                        _linea_plan(c),
                        _linea_equipo(c),
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
                    ft.OutlinedButton("Plan", icon=ft.Icons.CREDIT_CARD,
                                      on_click=lambda e: _form_plan_negocio(page, c)),
                    ft.OutlinedButton("Eliminar", icon=ft.Icons.DELETE_FOREVER,
                                      style=ft.ButtonStyle(color="#f87171"),
                                      on_click=lambda e: _eliminar_negocio(page, c)),
                ], wrap=True, spacing=8, run_spacing=8),
            ], spacing=10),
        )

    page.add(ft.Container(width=560, padding=16, content=ft.Column([
        _encabezado(page, "👑 Super administrador"),
        ft.Row([
            _boton("➕ Nuevo negocio", lambda e: _form_negocio(page)),
            _boton("🧪 Prueba 2 días", lambda e: _form_prueba(page)),
            _boton("👥 Super admins", lambda e: admins_view(page, None), apagado=True),
            _boton("💳 Planes", lambda e: planes_view(page), apagado=True),
            _boton("🔥 Promociones", lambda e: promociones_view(page), apagado=True),
            _boton("🎨 Temas", lambda e: temas_view(page), apagado=True),
            _boton("🎵 Canciones", lambda e: canciones_view(page), apagado=True),
            _boton("🎁 Bonos", lambda e: bonos_view(page), apagado=True),
            _boton("🧾 Pagos", lambda e: pagos_view(page), apagado=True),
            _boton("Salir", salir, apagado=True),
        ], wrap=True, spacing=8, run_spacing=8),
        ft.Text(f"{len(negocios)} negocios", color="#94A3B8"),
        *[tarjeta(c) for c in negocios],
    ], spacing=14)))
    page.update()


PLAYLIST_POR_DEFECTO_DE = os.getenv("PLAYLIST_POR_DEFECTO_DE", "8523")  # negocio "modelo"
MAX_LOGO_MB = 2


def _eliminar_negocio(page, c):
    """Borra TODO el negocio de la base. Hay que escribir su código para confirmar."""
    confirmar = _campo(f"Escribe el código del bar ({c['codigo']}) para confirmar", numeros=True)
    error = ft.Text("", color="#f87171")

    def borrar(ev):
        if (confirmar.value or "").strip() != str(c["codigo"]):
            error.value = "El código no coincide. No se borró nada."
            page.update()
            return
        try:
            r = db.eliminar_negocio(c["codigo"])
        except Exception as ex:
            error.value = f"No se pudo eliminar: {ex}"
            page.update()
            return
        _cerrar_dialogo(page)
        super_inicio(page)
        _aviso(page, f"{c['nombre']} ({c['codigo']}) eliminado" if r else "Ese negocio ya no existía")

    _dialogo(page, f"🗑️ Eliminar {c['nombre']}", [
        ft.Text("Se borra para siempre todo lo de este bar: sus administradores, la llave del "
                "reproductor (deja de funcionar en menos de un minuto), las canciones y el "
                "historial, la configuración, el logo, los pagos y las sesiones abiertas. "
                "El enlace /bar/" + str(c["codigo"]) + " dejará de existir.",
                color="#fecaca", size=13),
        ft.Text("Esto NO se puede deshacer.", color="#f87171", weight=ft.FontWeight.BOLD),
        confirmar, error,
    ], [ft.TextButton("Cancelar", on_click=lambda ev: _cerrar_dialogo(page)),
        ft.FilledButton("Eliminar para siempre", on_click=borrar,
                        style=ft.ButtonStyle(bgcolor="#b91c1c", color="white"))])


def _playlist_por_defecto():
    """Los negocios nuevos arrancan con la playlist que ya tenemos (la del negocio modelo),
    para que el aleatorio tenga música desde el primer día."""
    env = os.getenv("PLAYLIST_POR_DEFECTO", "").strip()
    if env:
        return env
    try:
        modelo = db.cliente(PLAYLIST_POR_DEFECTO_DE)
        if modelo and modelo.get("playlist"):
            return modelo["playlist"]
        for x in db.clientes():
            if x.get("playlist"):
                return x["playlist"]
    except Exception:
        pass
    return ""


def _form_negocio(page, c=None):
    nuevo = c is None
    codigo = _campo("Código del lugar (solo números)", "" if nuevo else c["codigo"],
                    numeros=True, disabled=not nuevo)
    nombre = _campo("Nombre del negocio", "" if nuevo else c["nombre"])
    playlist = _campo("Playlist de YouTube para el aleatorio (enlace o ID)",
                      _playlist_por_defecto() if nuevo else c["playlist"])
    activo = ft.Switch(value=True if nuevo else bool(c["activo"]), label="Activo",
                       active_color=CYAN)
    televisores = _campo("Televisores (equipos con el reproductor a la vez)",
                         "1" if nuevo else str(c.get("televisores") or 1), numeros=True)
    error = ft.Text("", color="#f87171")

    # Logo: se adjunta un PNG/JPG desde el computador o el celular (se guarda en la base)
    logo_nuevo = {"bytes": None, "tipo": "", "quitar": False}
    vista = ft.Image(src=ps.imagen_logo("" if nuevo else c["logo"], None if nuevo else c["codigo"]),
                     width=120, height=90, fit=ft.BoxFit.CONTAIN)
    nota_logo = ft.Text("Sin logo: se muestra el de PlayBar GO." if nuevo or not c["logo"] else "",
                        color="#64748b", size=12)

    async def adjuntar(e):
        try:
            archivos = await ft.FilePicker().pick_files(
                dialog_title="Logo del negocio", file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["png", "jpg", "jpeg", "webp"], with_data=True)
        except Exception as ex:
            error.value = f"No se pudo abrir el selector: {ex}"
            page.update()
            return
        if not archivos:
            return
        f = archivos[0]
        datos = f.bytes or b""
        if not datos:
            error.value = "No se pudo leer la imagen. Intenta de nuevo."
        elif len(datos) > MAX_LOGO_MB * 1024 * 1024:
            error.value = f"La imagen pesa {len(datos) / 1048576:.1f} MB. Máximo {MAX_LOGO_MB} MB."
        else:
            ext = (f.name or "").rsplit(".", 1)[-1].lower()
            logo_nuevo.update(bytes=datos, quitar=False,
                              tipo="image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext or 'png'}")
            vista.src = datos
            nota_logo.value = f"✔ {f.name} listo (se guarda al tocar Guardar)"
            error.value = ""
        page.update()

    def quitar(e):
        logo_nuevo.update(bytes=None, quitar=True)
        vista.src = ps.LOGO_PLAYBAR
        nota_logo.value = "Se quitará el logo: se mostrará el de PlayBar GO."
        page.update()

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
        tv_txt = (televisores.value or "").strip() or "1"
        if not tv_txt.isdigit() or not 1 <= int(tv_txt) <= db.MAX_TELEVISORES:
            error.value = f"Televisores: escribe un número de 1 a {db.MAX_TELEVISORES}."
            page.update()
            return
        logo_actual = "" if nuevo else c["logo"]
        fila = db.guardar_cliente(cod, nombre.value, logo_actual, playlist.value, activo.value)
        db.poner_televisores(cod, int(tv_txt))
        try:
            if logo_nuevo["bytes"]:
                db.guardar_logo(cod, logo_nuevo["bytes"], logo_nuevo["tipo"])
            elif logo_nuevo["quitar"]:
                db.quitar_logo(cod)
        except Exception as ex:
            _aviso(page, f"El negocio se guardó, pero el logo no: {ex}", error=True)
        ps.olvidar_cliente(cod)
        _cerrar_dialogo(page)
        super_inicio(page)
        if nuevo:
            _ver_llave(page, db.cliente(cod) or fila, recien=True)
        else:
            _aviso(page, "Negocio guardado")

    _dialogo(page, "Nuevo negocio" if nuevo else f"Editar {c['nombre']}", [
        codigo, nombre,
        ft.Text("Logo del negocio", color="white", size=14, weight=ft.FontWeight.BOLD),
        ft.Row([
            ft.Container(content=vista, bgcolor="#0b1220", border_radius=10, padding=6),
            ft.Column([
                ft.OutlinedButton("📎 Adjuntar imagen", on_click=adjuntar),
                ft.TextButton("Quitar logo", on_click=quitar),
            ], spacing=4),
        ], spacing=12),
        nota_logo,
        playlist,
        ft.Text("Los negocios nuevos traen la playlist que ya tenemos, para que suene algo "
                "desde el primer día. Puedes cambiarla.", color="#64748b", size=12),
        televisores,
        ft.Text("Con 3, el bar puede tener el reproductor abierto en 3 televisores; al abrirlo "
                "en un 4.º le sale \"Usar aquí\".", color="#64748b", size=12),
        activo, error,
    ], [ft.TextButton("Cancelar", on_click=lambda e: _cerrar_dialogo(page)),
        ft.FilledButton("Guardar", on_click=guardar)])


def _form_prueba(page):
    """Negocio de PRUEBA: el super admin le pone nombre, usuario y contraseña; tiene música
    sin límite por unos días (2 por defecto) y después se corta solo."""
    from services import registro
    codigo = _campo("Código del lugar", registro.nuevo_codigo(), numeros=True)
    nombre = _campo("Nombre del negocio")
    usuario = _campo("Usuario del administrador (para entrar al panel)")
    clave = _campo("Contraseña (mínimo 6)", clave=True)
    dias = _campo("Días de prueba", "2", numeros=True)
    error = ft.Text("", color="#f87171")

    def crear(e):
        cod = (codigo.value or "").strip()
        usu = (usuario.value or "").strip()
        d = (dias.value or "").strip() or "2"
        if not cod.isdigit() or len(cod) < 3:
            error.value = "El código debe tener al menos 3 números."
        elif db.cliente(cod):
            error.value = f"El código {cod} ya existe. Usa otro."
        elif len((nombre.value or "").strip()) < 3:
            error.value = "Escribe el nombre del negocio."
        elif not re.fullmatch(r"[A-Za-z0-9._-]{3,30}", usu):
            error.value = "Usuario: de 3 a 30 letras o números, sin espacios."
        elif len(clave.value or "") < 6:
            error.value = "La contraseña debe tener al menos 6 caracteres."
        elif not d.isdigit() or not 1 <= int(d) <= 30:
            error.value = "Días de prueba: de 1 a 30."
        else:
            error.value = ""
        if error.value:
            page.update()
            return
        try:
            db.guardar_cliente(cod, nombre.value, "", _playlist_por_defecto(), True)
            db.agregar_admin(cod, usu, clave.value, rol="admin", nota=f"Prueba {d} días")
            sus.crear_prueba_dias(cod, int(d))
        except Exception as ex:
            error.value = f"No se pudo crear: {ex}"
            page.update()
            return
        ps.olvidar_cliente(cod)
        _cerrar_dialogo(page)
        super_inicio(page)
        _ver_llave(page, db.cliente(cod), recien=True)
        _aviso(page, f"Prueba creada: {cod} · usuario {usu} · {d} días")

    _dialogo(page, "🧪 Negocio de prueba", [
        ft.Text("Música sin límite por los días que pongas. Al terminar se corta sola y "
                "el bar ve \"Tu prueba terminó\" con la opción de comprar su plan.",
                color="#94A3B8", size=13),
        codigo, nombre, usuario, clave, dias, error,
    ], [ft.TextButton("Cancelar", on_click=lambda e: _cerrar_dialogo(page)),
        ft.FilledButton("Crear prueba", on_click=crear)])


def _ver_llave(page, c, recien=False):
    c = db.cliente(c["codigo"]) or c
    texto = ft.Text(db.formato_llave(c["llave"]), selectable=True, color="white", size=30,
                    weight=ft.FontWeight.BOLD, font_family="monospace")

    async def copiar(e):
        try:
            await ft.Clipboard().set(texto.value)
            _aviso(page, "Llave copiada")
        except Exception as ex:
            _aviso(page, f"No se pudo copiar: {ex}", error=True)

    def regenerar(e):
        fila = db.regenerar_llave(c["codigo"])
        texto.value = db.formato_llave(fila["llave"])
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
        ft.Text("No importan mayúsculas ni el guion. Si la llave todavía es larga (pbg_...), "
                "usa Regenerar para tener una corta (la larga deja de servir).",
                color="#64748b", size=12),
        ft.Text("Si un PC o TV se pierde o alguien más tiene la llave, usa Regenerar.",
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


# ---------------------------------------------------------------------------
# Suscripción: prueba gratis, planes y pagos
# ---------------------------------------------------------------------------
NOMBRES_ESTADO = {"prueba": "Prueba gratis", "activo": "Plan activo", "vencido": "Vencido / suspendido",
                  "cortesia": "Cortesía (sin cobro)"}


def _pesos(n):
    return "$" + f"{int(n):,}".replace(",", ".")


def _linea_plan(c):
    try:
        e = sus.estado(c["codigo"], c)
    except Exception:
        return ft.Text("")
    color = "#22c55e" if e["permitido"] and not e["aviso"] else ("#facc15" if e["permitido"] else "#f87171")
    txt = e["titulo"]
    if e["estado"] == "prueba":
        txt += f" · {e['usadas']}/{e['limite']} canciones"
    elif e.get("prueba_dias") and e["permitido"]:
        txt += f" · hasta {sus.fecha_txt(e['vence'])} ({e['mensaje'].split('(quedan ')[-1].split(')')[0]})"
    elif e["estado"] in ("activo", "vencido") and e["vence"]:
        txt += f" · vence {sus.fecha_txt(e['vence'])}"
    return ft.Text(txt, color=color, size=13)


def _linea_equipo(c):
    """En qué equipo suena el bar (lo manda el reproductor al abrir): modelo, sistema, RAM..."""
    import json
    import time as _t
    try:
        ctl = db.control(c["codigo"]) or {}
        info = json.loads(ctl.get("equipo_info") or "{}")
    except Exception:
        return ft.Text("")
    if not info:
        return ft.Text("📺 Reproductor: todavía no se ha conectado con la versión nueva",
                       color="#64748b", size=12)
    visto = float(ctl.get("instancia_visto") or 0)
    hace = _t.time() - visto
    cuando = ("en línea" if hace < 90 else
              f"visto hace {int(hace // 60)} min" if hace < 3600 else
              f"visto hace {int(hace // 3600)} h" if hace < 86400 else "visto hace días")
    ram = float(info.get("ram_gb") or 0)
    partes = [("📺 " if info.get("tipo") == "tv" else "💻 ") + str(info.get("modelo") or "Equipo"),
              info.get("sistema", ""),
              f"{ram:g} GB RAM" if ram else "",
              f"{info['libre_gb']:g} GB libres" if info.get("libre_gb") is not None else "",
              info.get("pantalla", ""), info.get("calidad", ""),
              f"app {info['app']}" if info.get("app") else "", cuando]
    texto = " · ".join(p for p in partes if p)
    try:
        espejos = db.reproductores_activos(c["codigo"])
    except Exception:
        espejos = []
    if espejos:
        texto += f" · +{len(espejos)} TV espejo: " + ", ".join(e["equipo"] or "TV" for e in espejos)
    basico = 0 < ram < 2
    if basico:
        texto += " · ⚠️ equipo básico"
    return ft.Text(texto, color="#facc15" if basico else "#94A3B8", size=12, selectable=True)


def _form_plan_negocio(page, c):
    c = db.cliente(c["codigo"]) or c
    e = sus.estado(c["codigo"], c)
    estado = ft.Dropdown(label="Estado", width=340, value=c.get("plan_estado") or "prueba",
                         options=[ft.DropdownOption(key=k, text=v) for k, v in NOMBRES_ESTADO.items()])
    limite = _campo("Canciones de la prueba gratis", c.get("prueba_limite", 30), numeros=True)
    dias = _campo("Días a activar (si eliges Plan activo)", "30", numeros=True)
    reiniciar = ft.Checkbox(label="Reiniciar el conteo de la prueba (vuelve a 0)", value=False)
    error = ft.Text("", color="#f87171")

    def guardar(ev):
        try:
            sus.poner_estado(
                c["codigo"], estado.value,
                dias=int(dias.value or 0) if estado.value == "activo" else None,
                limite=int(limite.value or 0), reiniciar_prueba=bool(reiniciar.value))
        except Exception as ex:
            error.value = str(ex)
            page.update()
            return
        _cerrar_dialogo(page)
        super_inicio(page)
        _aviso(page, f"Plan de {c['nombre']} actualizado")

    _dialogo(page, f"💳 Plan de {c['nombre']}", [
        ft.Text(f"{e['titulo']}: {e['mensaje']}", color="white", size=13),
        estado, limite, dias, reiniciar,
        ft.Text("Plan activo + días: suma esos días desde hoy (o desde el vencimiento si aún "
                "está vigente). Vencido corta la música hasta que paguen.", color="#64748b", size=12),
        error,
    ], [ft.TextButton("Cancelar", on_click=lambda ev: _cerrar_dialogo(page)),
        ft.FilledButton("Guardar", on_click=guardar)])


def planes_view(page):
    if not _es_super(page):
        return super_login_view(page)
    _preparar(page)

    def editar(p=None):
        nombre = _campo("Nombre del plan", p["nombre"] if p else "")
        precio = _campo("Precio en pesos (ej. 60000)", p["precio"] if p else "", numeros=True)
        dias_ = _campo("Días que dura", p["dias"] if p else 30, numeros=True)
        solo = _campo("Solo para estos códigos (vacío = todos)", p["solo_para"] if p else "")
        orden = _campo("Orden en la lista", p["orden"] if p else 1, numeros=True)
        activo = ft.Switch(label="Activo (se puede comprar)", value=bool(p["activo"]) if p else True,
                           active_color=CYAN)
        error = ft.Text("", color="#f87171")

        def guardar(ev):
            try:
                if int(precio.value or 0) < 1500:
                    raise ValueError("Wompi no acepta pagos menores a $1.500")
                sus.guardar_plan(p["id"] if p else None, nombre.value, int(precio.value),
                                 int(dias_.value or 30), activo.value, solo.value,
                                 int(orden.value or 0))
                _portada_al_dia()
            except Exception as ex:
                error.value = str(ex)
                page.update()
                return
            _cerrar_dialogo(page)
            planes_view(page)

        _dialogo(page, "Editar plan" if p else "Nuevo plan",
                 [nombre, precio, dias_, solo, orden, activo, error],
                 [ft.TextButton("Cancelar", on_click=lambda ev: _cerrar_dialogo(page)),
                  ft.FilledButton("Guardar", on_click=guardar)])

    tarjetas = [ft.Container(
        width=520, padding=14, border_radius=16, bgcolor=PANEL, border=ft.Border.all(1, "#1e293b"),
        content=ft.Row([
            ft.Column([
                ft.Text(f"{p['nombre']} · {_pesos(p['precio'])} · {p['dias']} días", color="white",
                        size=16, weight=ft.FontWeight.BOLD),
                ft.Text(("Activo" if p["activo"] else "Inactivo") + " · " +
                        (f"solo para {p['solo_para']}" if p["solo_para"] else "para todos"),
                        color="#94A3B8", size=13),
                *([ft.Text(f"🔥 Promoción: {p['promo_pagos']} pago(s) a {_pesos(p['promo_precio'])}",
                           color="#facc15", size=13)] if sus.promo_vigente(p) else []),
            ], expand=True, spacing=2),
            ft.OutlinedButton("Editar", icon=ft.Icons.EDIT, on_click=lambda ev, p=p: editar(p)),
        ]),
    ) for p in sus.planes(todos=True)]
    page.add(ft.Container(width=560, padding=16, content=ft.Column([
        _encabezado(page, "💳 Planes", volver=super_inicio),
        _boton("➕ Nuevo plan", lambda ev: editar(None)),
        *tarjetas,
    ], spacing=14)))
    page.update()


def _portada_al_dia():
    try:
        import servidor_web
        servidor_web.limpiar_cache_portada()
    except Exception as ex:
        print("⚠️ portada: no se pudo refrescar:", ex)  # igual se refresca sola en 1 minuto


def promociones_view(page):
    """🔥 Promociones: lo que se guarda aquí sale de una en la página y al comprar."""
    if not _es_super(page):
        return super_login_view(page)
    _preparar(page)

    def editar(p):
        activa = ft.Switch(active_color=CYAN, value=bool(p.get("promo_activa")))
        texto = _campo("De qué se trata (ej. Promo de diciembre)", p.get("promo_texto") or "")
        valor = _campo("Valor de la promoción en pesos (ej. 29900)", p.get("promo_precio") or "",
                       numeros=True)
        meses = _campo("Cuántos meses a ese valor (ej. 3)", p.get("promo_pagos") or "", numeros=True)
        hasta = _campo("Válida hasta, opcional (ej. 2026-12-31)", p.get("promo_hasta") or "")
        error = ft.Text("", color="#f87171")

        def guardar(ev):
            try:
                v, m = int(valor.value or 0), int(meses.value or 0)
                fin = (hasta.value or "").strip()
                if fin:
                    time.strptime(fin, "%Y-%m-%d")
                if len(texto.value or "") > 200:
                    raise ValueError("El texto es muy largo (máximo 200 letras)")
                if activa.value:
                    if v < 1500:
                        raise ValueError("Wompi no acepta pagos menores a $1.500")
                    if v >= int(p["precio"]):
                        raise ValueError(f"Debe ser más barata que el precio normal ({_pesos(p['precio'])})")
                    if m < 1:
                        raise ValueError("Pon cuántos meses dura la promoción")
                sus.guardar_promo(p["id"], activa.value, texto.value, v, m, fin)
                _portada_al_dia()
            except ValueError as ex:
                error.value = ("La fecha va así: 2026-12-31" if "does not match" in str(ex) or
                               "out of range" in str(ex) else str(ex))
                page.update()
                return
            _cerrar_dialogo(page)
            _aviso(page, "Promoción guardada: ya está en la página." if activa.value
                   else "Promoción apagada: ya no sale en la página.")
            promociones_view(page)

        _dialogo(page, f"🔥 Promoción · {p['nombre']}",
                 [ft.Row([activa, ft.Text("Promoción activa (se ve en la página)", color="white", size=14)]),
                  texto, valor, meses, hasta,
                  ft.Text(f"Después de esos meses, el bar paga el precio normal "
                          f"({_pesos(p['precio'])}). Es para los primeros pagos de cada bar: quien "
                          "ya hizo esa cantidad de pagos de este plan no la recibe.",
                          color="#64748b", size=12),
                  error],
                 [ft.TextButton("Cancelar", on_click=lambda ev: _cerrar_dialogo(page)),
                  ft.FilledButton("Guardar", on_click=guardar)])

    def tarjeta(p):
        if sus.promo_vigente(p):
            estado, color = (f"🔥 Activa: {p['promo_pagos']} mes(es) a {_pesos(p['promo_precio'])}" +
                             (f" · hasta {p['promo_hasta']}" if p.get("promo_hasta") else ""), "#facc15")
        elif p.get("promo_activa"):
            estado, color = "Vencida o incompleta: no sale en la página", "#f87171"
        else:
            estado, color = "Sin promoción", "#94A3B8"
        return ft.Container(
            width=520, padding=14, border_radius=16, bgcolor=PANEL, border=ft.Border.all(1, "#1e293b"),
            content=ft.Row([
                ft.Column([
                    ft.Text(f"{p['nombre']} · {_pesos(p['precio'])}", color="white", size=16,
                            weight=ft.FontWeight.BOLD),
                    ft.Text(estado, color=color, size=13),
                    *([ft.Text(p["promo_texto"], color="#cbd5e1", size=13)]
                      if p.get("promo_activa") and p.get("promo_texto") else []),
                ], expand=True, spacing=2),
                ft.OutlinedButton("Editar", icon=ft.Icons.EDIT, on_click=lambda ev, p=p: editar(p)),
            ]),
        )

    page.add(ft.Container(width=560, padding=16, content=ft.Column([
        _encabezado(page, "🔥 Promociones", volver=super_inicio),
        ft.Text("Escoge el plan y pon el texto, el valor y los meses. Sale de una en la página y al "
                "comprar. Para retirarla, apaga «Promoción activa».", color="#94A3B8", size=13),
        *[tarjeta(p) for p in sus.planes(todos=True)],
    ], spacing=14)))
    page.update()


def _vista_tema(t, ancho=480, logo_bytes=None):
    """Cómo se ve el tema en el reproductor (colores, logo, adornos y mensaje)."""
    from services import temas
    c = t["colores"]
    return ft.Container(
        width=ancho, padding=12, border_radius=14, bgcolor=c["fondo"],
        border=ft.Border.all(2, c["acento"]),
        content=ft.Column([
            ft.Row([ft.Text(t.get("adornos") or "", size=22),
                    ft.Image(src=logo_bytes or temas.ruta_logo(t) or "/logo.png", height=44,
                             fit=ft.BoxFit.CONTAIN),
                    ft.Text(t.get("adornos") or "", size=22)],
                   alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(padding=8, border_radius=10, bgcolor=c["panel"],
                         border=ft.Border.all(1, c["acento2"]),
                         content=ft.Text(t.get("mensaje") or "(sin mensaje)", color=c["texto"], size=13,
                                         text_align=ft.TextAlign.CENTER)),
            ft.Row([ft.Container(width=26, height=14, border_radius=4, bgcolor=c[k],
                                 border=ft.Border.all(1, "#ffffff33"), tooltip=k)
                    for k in ("fondo", "panel", "acento", "acento2", "texto")], spacing=6,
                   alignment=ft.MainAxisAlignment.CENTER),
        ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
    )


def temas_view(page):
    """🎨 Temas por temporada: plantillas que cambian el visual de los reproductores."""
    if not _es_super(page):
        return super_login_view(page)
    from services import temas
    _preparar(page)
    lista = temas.lista()
    modo = temas.modo()

    def cambiar_modo(e):
        temas.poner_modo(e.control.value)
        _aviso(page, "Listo: los reproductores lo cambian en máximo 3 minutos.")
        temas_view(page)

    selector = ft.Dropdown(
        label="Tema que se ve en todos los bares", width=480, value=modo, color="white",
        border_color=CYAN, on_select=cambiar_modo,
        options=[ft.dropdown.Option("normal", "Normal (sin tema)"),
                 ft.dropdown.Option("auto", "📅 Automático por fechas")]
        + [ft.dropdown.Option(x["clave"], f"Siempre: {x['nombre']}") for x in lista],
    )
    ahora = temas.actual()
    estado = ft.Text("Ahora se ve: " + (ahora["nombre"] if ahora else "el normal (sin tema)"),
                     color="#22d3ee", size=14, weight=ft.FontWeight.BOLD)

    def editar(t=None, copia=False):
        base = dict(t) if t else temas.limpiar({"nombre": "Nuevo tema", "colores": temas.NORMAL})
        if copia:
            base.update(clave="", nombre=f"{base['nombre']} (copia)")
        colores = dict(base["colores"])
        nombre = _campo("Nombre (ej. 💕 Amor y amistad)", base["nombre"])
        mensaje = _campo("Mensaje que se ve en la pantalla", base["mensaje"])
        adornos = _campo("Adornos junto al logo (emojis, ej. 🎄🎁⭐)", base["adornos"])
        efecto = ft.Dropdown(label="Efecto animado", width=340, value=base["efecto"], color="white",
                             border_color=CYAN,
                             options=[ft.dropdown.Option(k, v) for k, v in temas.EFECTOS.items()])
        desde = _campo("Se activa sola desde (MM-DD)", base["desde"], ancho=165)
        hasta = _campo("hasta (MM-DD)", base["hasta"], ancho=165)
        orden = _campo("Orden", base.get("orden") or 0, numeros=True, ancho=100)
        error = ft.Text("", color="#f87171")

        # --- logo: el de siempre, uno de assets o uno adjuntado desde el computador/celular
        logo = {"valor": base.get("logo") or "", "bytes": None, "tipo": ""}
        logos_assets = [f for f in temas.logos_disponibles() if f != "logo.png"]
        logo_sel = ft.Dropdown(
            label="Logo", width=340, color="white", border_color=CYAN,
            value=logo["valor"] if logo["valor"] in logos_assets or not logo["valor"] else "subido",
            options=[ft.dropdown.Option("", "El de siempre (PlayBar GO)")]
            + [ft.dropdown.Option(f, f) for f in logos_assets]
            + ([ft.dropdown.Option("subido", "El que adjunté")] if logo["valor"].startswith("subido:") else []))
        nota_logo = ft.Text("", color="#64748b", size=12)

        def elegir_logo(e):
            if e.control.value != "subido":
                logo.update(valor=e.control.value or "", bytes=None)
                nota_logo.value = ""
                ver()

        logo_sel.on_select = elegir_logo

        async def adjuntar(e):
            try:
                archivos = await ft.FilePicker().pick_files(
                    dialog_title="Logo del tema", file_type=ft.FilePickerFileType.CUSTOM,
                    allowed_extensions=["png", "jpg", "jpeg", "webp"], with_data=True)
            except Exception as ex:
                error.value = f"No se pudo abrir el selector: {ex}"
                page.update()
                return
            if not archivos:
                return
            f = archivos[0]
            datos_ = f.bytes or b""
            if not datos_:
                error.value = "No se pudo leer la imagen. Intenta de nuevo."
            elif len(datos_) > MAX_LOGO_MB * 1024 * 1024:
                error.value = f"La imagen pesa {len(datos_) / 1048576:.1f} MB. Máximo {MAX_LOGO_MB} MB."
            else:
                ext = (f.name or "").rsplit(".", 1)[-1].lower()
                logo.update(bytes=datos_, tipo="image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext or 'png'}")
                nota_logo.value = f"✔ {f.name} listo (se guarda al tocar Guardar). Mejor PNG sin fondo."
                error.value = ""
                ver()
                return
            page.update()

        # --- colores: se escogen tocando la paleta
        nombres_color = (("fondo", "Fondo"), ("panel", "Paneles"), ("acento", "Principal"),
                         ("acento2", "Secundario"), ("texto", "Texto"))
        activo = {"k": "fondo"}
        chips = {}

        def pintar_chips():
            for k, chip in chips.items():
                chip.content.controls[0].bgcolor = colores[k]
                chip.border = ft.Border.all(3 if k == activo["k"] else 1,
                                            CYAN if k == activo["k"] else "#334155")
            titulo_paleta.value = f"Toca un color para «{dict(nombres_color)[activo['k']]}»:"
            hex_campo.value = colores[activo["k"]]

        def escoger_rol(k):
            activo["k"] = k
            pintar_chips()
            page.update()

        for k, etq in nombres_color:
            chips[k] = ft.Container(
                padding=6, border_radius=10, on_click=lambda e, k=k: escoger_rol(k),
                content=ft.Column([
                    ft.Container(width=46, height=26, border_radius=6, border=ft.Border.all(1, "#ffffff55")),
                    ft.Text(etq, size=11, color="#cbd5e1"),
                ], spacing=3, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True))

        def poner_color(hex_):
            colores[activo["k"]] = hex_
            pintar_chips()
            ver()

        paleta = ft.Row([
            ft.Container(width=30, height=30, border_radius=8, bgcolor=h, tooltip=h,
                         border=ft.Border.all(1, "#ffffff44"), on_click=lambda e, h=h: poner_color(h))
            for h in temas.PALETA], wrap=True, spacing=6, run_spacing=6, width=340)
        titulo_paleta = ft.Text("", color="#94A3B8", size=12)

        def hex_cambiado(e):
            v = (e.control.value or "").strip()
            if re.match(r"^#[0-9a-fA-F]{6}$", v):
                poner_color(v.lower())

        hex_campo = _campo("u otro color (#RRGGBB)", "", ancho=160)
        hex_campo.on_blur = hex_cambiado
        hex_campo.on_submit = hex_cambiado
        pintar_chips()

        vista = ft.Container(content=_vista_tema(base, ancho=340))

        def datos():
            return {"clave": base.get("clave") or "", "nombre": nombre.value, "mensaje": mensaje.value,
                    "adornos": adornos.value, "efecto": efecto.value, "desde": desde.value,
                    "hasta": hasta.value, "orden": orden.value, "logo": logo["valor"],
                    "colores": dict(colores)}

        def ver(ev=None):
            vista.content = _vista_tema(temas.limpiar(datos()), ancho=340, logo_bytes=logo["bytes"])
            page.update()

        for f in [mensaje, adornos]:
            f.on_blur = ver
        efecto.on_select = ver

        def guardar(ev):
            d = datos()
            fecha = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
            if (d["desde"] or d["hasta"]) and not (fecha.match((d["desde"] or "").strip())
                                                  and fecha.match((d["hasta"] or "").strip())):
                error.value = "Fechas con el formato MM-DD (ej. 12-01), o deja las dos vacías."
                page.update()
                return
            try:
                guardado = temas.guardar(d)
                if logo["bytes"]:  # el logo adjuntado se guarda con la clave del tema
                    d["clave"] = guardado["clave"]
                    d["logo"] = temas.guardar_logo(guardado["clave"], logo["bytes"], logo["tipo"])
                    temas.guardar(d)
            except Exception as ex:
                error.value = f"No se pudo guardar: {ex}"
                page.update()
                return
            _cerrar_dialogo(page)
            _aviso(page, "Tema guardado")
            temas_view(page)

        _dialogo(page, "Editar tema" if t and not copia else "Nuevo tema", [
            vista, nombre, mensaje, adornos, efecto,
            logo_sel,
            ft.Row([ft.OutlinedButton("📎 Adjuntar logo", on_click=adjuntar)], wrap=True),
            nota_logo,
            ft.Text("Colores: toca qué quieres cambiar y luego un color de la paleta.",
                    color="#94A3B8", size=12),
            ft.Row(list(chips.values()), wrap=True, spacing=4, run_spacing=4),
            titulo_paleta, paleta, hex_campo,
            ft.Row([desde, hasta], wrap=True, spacing=8),
            ft.Text("Con «Automático por fechas», este tema se ve solo entre esas fechas.",
                    color="#64748b", size=12),
            orden, error,
        ], [ft.TextButton("Cancelar", on_click=lambda ev: _cerrar_dialogo(page)),
            ft.FilledButton("Guardar", on_click=guardar)])

    def eliminar(t):
        def si(ev):
            temas.borrar(t["clave"])
            _cerrar_dialogo(page)
            temas_view(page)
        _dialogo(page, f"¿Eliminar {t['nombre']}?", [ft.Text("La plantilla se borra.", color="white")],
                 [ft.TextButton("Cancelar", on_click=lambda ev: _cerrar_dialogo(page)),
                  ft.FilledButton("Eliminar", on_click=si)])

    def activar(t):
        temas.poner_modo(t["clave"])
        _aviso(page, f"{t['nombre']} activado en todos los bares (en máximo 3 minutos).")
        temas_view(page)

    def tarjeta(t):
        fechas = f"📅 {t['desde']} a {t['hasta']}" if t["desde"] and t["hasta"] else "📅 sin fechas"
        return ft.Container(
            width=520, padding=14, border_radius=16, bgcolor=PANEL, border=ft.Border.all(1, "#1e293b"),
            content=ft.Column([
                ft.Text(t["nombre"], size=17, color="white", weight=ft.FontWeight.BOLD),
                ft.Text(f"{fechas} · {temas.EFECTOS.get(t['efecto'], '')}", color="#94A3B8", size=13),
                _vista_tema(t),
                ft.Row([
                    ft.OutlinedButton("Activar ya", icon=ft.Icons.PLAY_ARROW,
                                      on_click=lambda e, t=t: activar(t)),
                    ft.OutlinedButton("Editar", icon=ft.Icons.EDIT, on_click=lambda e, t=t: editar(t)),
                    ft.OutlinedButton("Duplicar", icon=ft.Icons.COPY,
                                      on_click=lambda e, t=t: editar(t, copia=True)),
                    ft.OutlinedButton("Eliminar", icon=ft.Icons.DELETE, style=ft.ButtonStyle(color="#f87171"),
                                      on_click=lambda e, t=t: eliminar(t)),
                ], wrap=True, spacing=8, run_spacing=8),
            ], spacing=8),
        )

    page.add(ft.Container(width=560, padding=16, content=ft.Column([
        _encabezado(page, "🎨 Temas por temporada", volver=super_inicio),
        ft.Text("Cambian el visual de los reproductores (TV, PC y navegador) y de la página de los "
                "clientes: colores, mensaje, adornos y un efecto animado.", color="#94A3B8", size=13),
        selector, estado,
        _boton("➕ Nuevo tema", lambda e: editar(None)),
        *[tarjeta(t) for t in lista],
    ], spacing=14)))
    page.update()


def canciones_view(page, buscar="", ver_eliminadas=False):
    """🎵 Las canciones que están en la nube (Cloudflare), con el nombre claro (allá solo se ve
    el código del video)."""
    if not _es_super(page):
        return super_login_view(page)
    from services import volumen
    _preparar(page)
    try:
        filas = db.canciones_nube(buscar)
        total, megas = db.contar_canciones_nube()
    except Exception as ex:
        page.add(ft.Text(f"No se pudo leer: {ex}", color="#f87171"))
        page.update()
        return
    campo = _campo("Buscar por canción o artista", buscar, ancho=360)
    campo.on_submit = lambda e: canciones_view(page, campo.value or "")
    eliminadas = db.canciones_eliminadas()

    def eliminar(f):
        def si(ev):
            db.eliminar_cancion(f["video_id"], f["titulo"], f["canal"])
            _cerrar_dialogo(page)
            _aviso(page, "Canción eliminada: ya no suena de relleno. Se borra de la nube en un momento.")
            canciones_view(page, buscar)
        _dialogo(page, "🗑️ ¿Eliminar esta canción?", [
            ft.Text(f["titulo"] or f["video_id"], color="white", weight=ft.FontWeight.BOLD),
            ft.Text("Deja de sonar como relleno en todos los bares (y sale de los géneros) y se "
                    "borra de la nube. Los clientes sí la pueden pedir: si alguien la pide, vuelve. "
                    "También la puedes restaurar en «Canciones eliminadas».", color="#cbd5e1", size=13),
        ], [ft.TextButton("Cancelar", on_click=lambda ev: _cerrar_dialogo(page)),
            ft.FilledButton("Eliminar", on_click=si, style=ft.ButtonStyle(bgcolor="#b91c1c"))])

    def restaurar(f):
        db.restaurar_cancion(f["video_id"])
        _aviso(page, "Canción restaurada: vuelve al relleno cuando la pidan (se baja de nuevo).")
        canciones_view(page, buscar, ver_eliminadas=True)

    def fila(f):
        fac = volumen.factor(f["lufs"])
        detalles = [f"{f['canal']}" if f["canal"] else "",
                    f"{f['bytes'] / 1048576:.0f} MB" if f["bytes"] else "",
                    f"pedida {f['veces']} {'vez' if f['veces'] == 1 else 'veces'}" if f["veces"] else "",
                    "🎄 Diciembre" if f["genero"] == "diciembre" else "",
                    "🔊 sin medir" if f["lufs"] is None else
                    f"🔊 se baja al {int(fac * 100)}%" if fac < 0.99 else "🔊 volumen normal"]
        return ft.Container(
            width=520, padding=8, border_radius=12, bgcolor=PANEL,
            content=ft.Row([
                ft.Image(src=f"https://i.ytimg.com/vi/{f['video_id']}/mqdefault.jpg", width=96, height=54,
                         fit=ft.BoxFit.COVER, border_radius=6),
                ft.Column([
                    ft.Text(f["titulo"] or f["video_id"], color="white", size=13, weight=ft.FontWeight.BOLD,
                            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(" · ".join(d for d in detalles if d), color="#94A3B8", size=11, max_lines=2),
                ], spacing=2, expand=True),
                ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, icon_color="#22d3ee", tooltip="Ver en YouTube",
                              url=f"https://youtu.be/{f['video_id']}"),
                ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#f87171", tooltip="Eliminar (no sirve)",
                              on_click=lambda e, f=f: eliminar(f)),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def fila_eliminada(f):
        return ft.Container(
            width=520, padding=8, border_radius=12, bgcolor="#1f0f12", border=ft.Border.all(1, "#7f1d1d"),
            content=ft.Row([
                ft.Column([
                    ft.Text(f["titulo"] or f["video_id"], color="white", size=13, max_lines=2,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text((f"{f['canal']} · " if f["canal"] else "") +
                            ("borrada de la nube" if f["borrada_nube"] else "se está borrando de la nube"),
                            color="#94A3B8", size=11),
                ], spacing=2, expand=True),
                ft.OutlinedButton("Restaurar", icon=ft.Icons.RESTORE, on_click=lambda e, f=f: restaurar(f)),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    page.add(ft.Container(width=560, padding=16, content=ft.Column([
        _encabezado(page, "🎵 Canciones en la nube", volver=super_inicio),
        ft.Text(f"{total} canciones guardadas en la nube" + (f" ({megas / 1024:.1f} GB)" if megas else "") +
                ". Las ven todos los bares sin bajarlas de YouTube. En Cloudflare solo aparece el "
                "código del video; aquí está el nombre. Si eliminas una, sale del relleno y de los "
                "géneros, pero los clientes la pueden volver a pedir.",
                color="#94A3B8", size=13),
        ft.Row([campo, _boton("Buscar", lambda e: canciones_view(page, campo.value or ""))],
               wrap=True, spacing=8),
        ft.TextButton(f"🗑️ Canciones eliminadas ({len(eliminadas)})" + (" ▲" if ver_eliminadas else " ▼"),
                      on_click=lambda e: canciones_view(page, buscar, not ver_eliminadas)),
        *([fila_eliminada(f) for f in eliminadas] if ver_eliminadas else []),
        ft.Text(f"{len(filas)} resultado(s)" + (f" para «{buscar}»" if buscar else " · las más recientes"),
                color="#64748b", size=12),
        *[fila(f) for f in filas],
    ], spacing=10)))
    page.update()


def bonos_view(page):
    """🎁 Bonos de referido: cada código descuenta bonos.DESCUENTO en un solo pago."""
    from services import bonos

    if not _es_super(page):
        return super_login_view(page)
    _preparar(page)
    nota = _campo("Referido por (opcional): nombre o nota", ancho=340)

    def generar(e):
        b = bonos.crear(nota.value)

        async def copiar(ev):
            await ft.Clipboard().set(b["codigo"])
            _aviso(page, "Código copiado")

        _dialogo(page, "🎁 Bono creado", [
            ft.Text(b["codigo"], selectable=True, color="white", size=30, weight=ft.FontWeight.BOLD),
            ft.Text(f"Descuenta {_pesos(b['descuento'])} en un solo pago (compra o renovación)."
                    + (f"\nReferido por: {b['nota']}" if b["nota"] else ""), color="#cbd5e1", size=13),
        ], [ft.TextButton("Copiar", on_click=copiar),
            ft.FilledButton("Listo", on_click=lambda ev: (_cerrar_dialogo(page), bonos_view(page)))])

    def cambiar(b, activo):
        bonos.poner_activo(b["codigo"], activo)
        bonos_view(page)

    color = {"sin usar": "#22c55e", "reservado": "#facc15", "usado": "#94A3B8",
             "desactivado": "#f87171"}
    filas = []
    for b in bonos.lista():
        est = bonos.estado_txt(b)
        detalle = est.capitalize()
        if est == "usado":
            detalle += f" · bar {b['usado_bar']} · {fecha_local(b['usado_en'])[:16]}"
        elif est == "reservado":
            detalle += " · pago en curso"
        acciones = []
        if est in ("sin usar", "reservado"):
            acciones.append(ft.TextButton("Desactivar", on_click=lambda e, b=b: cambiar(b, False)))
        elif est == "desactivado":
            acciones.append(ft.TextButton("Activar", on_click=lambda e, b=b: cambiar(b, True)))
        filas.append(ft.Container(
            width=520, padding=12, border_radius=14, bgcolor=PANEL, border=ft.Border.all(1, "#1e293b"),
            content=ft.Row([
                ft.Column([
                    ft.Text(b["codigo"], color="white", size=16, weight=ft.FontWeight.BOLD,
                            selectable=True),
                    ft.Text(f"−{_pesos(b['descuento'])}" + (f" · {b['nota']}" if b["nota"] else "")
                            + f" · creado {fecha_local(b['creado'])[:10]}", color="#94A3B8", size=12),
                    ft.Text(detalle, color=color.get(est, "white"), size=13),
                ], expand=True, spacing=2),
                *acciones,
            ])))
    page.add(ft.Container(width=560, padding=16, content=ft.Column([
        _encabezado(page, "🎁 Bonos de referido", volver=super_inicio),
        ft.Text(f"Cada código sirve una sola vez y descuenta {_pesos(bonos.DESCUENTO)} de un pago "
                "(la compra en la web o una renovación en «Mi plan»).", color="#94A3B8", size=13),
        nota,
        _boton("➕ Generar bono", generar),
        *(filas or [ft.Text("Todavía no hay bonos.", color="#94A3B8")]),
    ], spacing=12)))
    page.update()


def pagos_view(page):
    if not _es_super(page):
        return super_login_view(page)
    _preparar(page)
    filas = sus.pagos(None, 300)
    color = {"APROBADO": "#22c55e", "PENDIENTE": "#facc15"}
    tabla = ft.DataTable(
        columns=[ft.DataColumn(label=ft.Text(t, color="white", weight=ft.FontWeight.BOLD))
                 for t in ("Fecha", "Negocio", "Plan", "Valor", "Estado", "Referencia")],
        rows=[ft.DataRow(cells=[
            ft.DataCell(content=ft.Text(fecha_local(o["creado"])[:16], size=12, color="#cbd5e1")),
            ft.DataCell(content=ft.Text(o["codigo"], size=12, color="#cbd5e1")),
            ft.DataCell(content=ft.Text(o["plan_nombre"] + (f" · bono {o['bono']}" if o.get("bono") else ""),
                                        size=12, color="white")),
            ft.DataCell(content=ft.Text(_pesos(o["monto"]), size=12, color="white")),
            ft.DataCell(content=ft.Text(o["estado"], size=12, color=color.get(o["estado"], "#f87171"))),
            ft.DataCell(content=ft.Text(o["referencia"], size=11, color="#64748b", selectable=True)),
        ]) for o in filas],
        heading_row_color="#0b1220", column_spacing=14, data_row_min_height=32,
        horizontal_lines=ft.BorderSide(1, "#1e293b"),
    )
    aprobados = sum(int(o["monto"]) for o in filas if o["estado"] == "APROBADO")
    page.add(ft.Container(padding=16, content=ft.Column([
        _encabezado(page, "🧾 Pagos", volver=super_inicio),
        ft.Text(f"{len(filas)} pagos · aprobados {_pesos(aprobados)}", color="#94A3B8"),
        ft.Row([tabla], scroll=ft.ScrollMode.AUTO),
    ], spacing=12)))
    page.update()
