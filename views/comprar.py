"""
🛒 Comprar PlayBar GO:  play.alnovix.com/comprar

1. Datos del bar y del administrador + el plan.
2. Se crea el bar con su código (sin servicio todavía) y se paga en Wompi.
3. Cuando Wompi aprueba, el plan queda activo: se muestran el código, el usuario, el
   enlace para los clientes y el botón de WhatsApp para pedir la llave del reproductor.
"""
import asyncio
import threading
import time
import urllib.parse

import flet as ft

from services import bonos, registro
from services import suscripcion as sus
from views.acceso import CYAN, FONDO, VIOLETA, boton_degradado, campo, ir_a_portada
from views.admin import URL_CLIENTES
from views.plan import API_URL

WHATSAPP = "573016130044"
REVISAR_SEG = 4
REVISAR_MAX_MIN = 30
MAX_REGISTROS_POR_VISITA = 3
_registros = {}  # id(page) -> cuántos bares creó esta visita


def _pesos(n):
    return "$" + f"{int(n):,}".replace(",", ".")


def _enlace_whatsapp(bar):
    texto = (f"Hola, compré PlayBar GO. Mi bar es {bar['nombre']}, código {bar['codigo']}. "
             "Quiero la llave del reproductor.")
    return f"https://wa.me/{WHATSAPP}?text={urllib.parse.quote(texto)}"


def _marco(page, *controles):
    page.clean()
    page.bgcolor = FONDO
    page.scroll = ft.ScrollMode.AUTO
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.add(ft.Container(width=440, padding=ft.Padding.symmetric(horizontal=16, vertical=24),
                          content=ft.Column(list(controles), spacing=14,
                                            horizontal_alignment=ft.CrossAxisAlignment.CENTER)))
    page.update()


def _encabezado(titulo, subtitulo):
    return [ft.Image(src="/logo.png", width=150, height=100, fit=ft.BoxFit.CONTAIN),
            ft.Text(titulo, size=26, weight=ft.FontWeight.BOLD, color="white",
                    text_align=ft.TextAlign.CENTER),
            ft.Text(subtitulo, size=14, color="#94A3B8", text_align=ft.TextAlign.CENTER, width=380)]


def _pasos(actual):
    nombres = ["Tus datos", "Pago", "Listo"]
    fichas = []
    for i, n in enumerate(nombres, 1):
        on = i <= actual
        fichas.append(ft.Container(
            padding=ft.Padding.symmetric(horizontal=12, vertical=6), border_radius=20,
            bgcolor=CYAN if i == actual else ("#0e3a4a" if on else "#0b1220"),
            border=ft.Border.all(1, CYAN if on else "#334155"),
            content=ft.Text(f"{i}. {n}", size=12, weight=ft.FontWeight.BOLD,
                            color=FONDO if i == actual else ("white" if on else "#64748b"))))
    return ft.Row(fichas, alignment=ft.MainAxisAlignment.CENTER, spacing=8, wrap=True)


# ---------------------------------------------------------------------------
# Paso 1: datos
# ---------------------------------------------------------------------------
def comprar_view(page, plan_id=None):
    try:
        planes = [p for p in sus.planes() if not (p.get("solo_para") or "").strip()]
    except Exception as ex:
        print("⚠️ comprar: planes:", ex)
        planes = []

    nombre = campo("Nombre del bar", capitalization=ft.TextCapitalization.WORDS)
    ciudad = campo("Ciudad", capitalization=ft.TextCapitalization.WORDS)
    celular = campo("Celular (WhatsApp)", keyboard_type=ft.KeyboardType.PHONE,
                    input_filter=ft.NumbersOnlyInputFilter(), max_length=12,
                    counter=ft.Container(width=0, height=0), hint_text="3001234567")
    usuario = campo("Usuario para entrar al panel", autocorrect=False, enable_suggestions=False,
                    capitalization=ft.TextCapitalization.NONE)
    clave = campo("Contraseña", password=True, can_reveal_password=True)
    clave2 = campo("Repite la contraseña", password=True, can_reveal_password=True)
    bono = campo("Código de bono (opcional)", capitalization=ft.TextCapitalization.CHARACTERS,
                 autocorrect=False, enable_suggestions=False, hint_text="PBG-XXXXXX")
    error = ft.Text("", color="#f87171", size=13, width=320, text_align=ft.TextAlign.CENTER)

    elegido = str(plan_id) if plan_id and any(str(p["id"]) == str(plan_id) for p in planes) \
        else (str(planes[0]["id"]) if planes else "")
    grupo = ft.RadioGroup(value=elegido, content=ft.Column([
        ft.Container(
            width=320, padding=12, border_radius=14, bgcolor="#0b1220",
            border=ft.Border.all(1, "#334155"),
            content=ft.Radio(value=str(p["id"]), fill_color=CYAN,
                             label=f"{p['nombre']} · {_pesos(p['precio'])} · {p['dias']} días",
                             label_style=ft.TextStyle(color="white", size=15)))
        for p in planes], spacing=8))

    def continuar(e=None):
        if not planes:
            error.value = "No hay planes disponibles. Escríbenos por WhatsApp."
            page.update()
            return
        msg = registro.validar(nombre.value, ciudad.value, celular.value, usuario.value,
                               clave.value, clave2.value)
        if not msg and not grupo.value:
            msg = "Elige un plan."
        if not msg and _registros.get(id(page), 0) >= MAX_REGISTROS_POR_VISITA:
            msg = "Ya creaste varios bares. Si necesitas otro, escríbenos por WhatsApp."
        if not msg and bonos.normalizar(bono.value):
            _, msg = bonos.revisar(bono.value)
        if msg:
            error.value = msg
            page.update()
            return
        error.value = "Creando tu bar…"
        page.update()
        try:
            bar = registro.crear_bar(nombre.value, ciudad.value, celular.value,
                                     usuario.value, clave.value)
            _registros[id(page)] = _registros.get(id(page), 0) + 1
        except Exception as ex:
            print("❌ registro web:", ex)
            error.value = "No se pudo crear el bar. Intenta de nuevo en un momento."
            page.update()
            return
        pago_view(page, bar, usuario.value.strip(), int(grupo.value), bono.value)

    clave2.on_submit = continuar
    bono.on_submit = continuar

    _marco(page,
           *_encabezado("Compra PlayBar GO", "Crea tu cuenta de administrador y paga tu plan. "
                        "Al aprobarse el pago, tu bar queda activo."),
           _pasos(1),
           ft.Container(height=4),
           ft.Text("TU BAR", color="#94A3B8", size=12, weight=ft.FontWeight.BOLD, width=320),
           nombre, ciudad, celular,
           ft.Text("TU USUARIO DE ADMINISTRADOR", color="#94A3B8", size=12,
                   weight=ft.FontWeight.BOLD, width=320),
           usuario, clave, clave2,
           ft.Text("TU PLAN", color="#94A3B8", size=12, weight=ft.FontWeight.BOLD, width=320),
           grupo if planes else ft.Text("No hay planes disponibles por ahora.", color="#94A3B8"),
           bono,
           ft.Text(f"Con un código de bono de referido pagas {_pesos(bonos.DESCUENTO)} menos "
                   "en este primer pago.", color="#64748b", size=12, width=320),
           error,
           boton_degradado("Continuar al pago", continuar),
           ft.Text("El código de tu bar lo genera el sistema. La llave del reproductor te la "
                   "damos por WhatsApp después del pago.", color="#64748b", size=12, width=320,
                   text_align=ft.TextAlign.CENTER),
           ft.TextButton("← Volver al inicio", on_click=ir_a_portada,
                         style=ft.ButtonStyle(color="#94A3B8")))


# ---------------------------------------------------------------------------
# Paso 2: pago
# ---------------------------------------------------------------------------
def pago_view(page, bar, usuario, plan_id, bono_txt=""):
    codigo = bar["codigo"]
    p = sus.plan(plan_id)
    aviso = ft.Text("", color="#facc15", size=13, width=340, text_align=ft.TextAlign.CENTER)
    estado = {"ref": None, "vivo": True, "desde": time.time(), "bono": ""}
    linea_bono = ft.Row([], visible=False)
    total = ft.Text("", color="white", size=20, weight=ft.FontWeight.BOLD)

    def pintar_precio(b=None):
        """Precio a pagar (lo mismo que calcula el servidor al crear la orden)."""
        precio = int(p["precio"]) if p else 0
        monto, descuento = bonos.precio_con_bono(precio, b)
        estado["bono"] = b["codigo"] if b and descuento else ""
        linea_bono.visible = bool(estado["bono"])
        linea_bono.controls = [
            ft.Text(f"Bono {estado['bono']}", color="#4ade80", size=14, expand=True),
            ft.Text(f"−{_pesos(descuento)}", color="#4ade80", size=15)] if estado["bono"] else []
        total.value = _pesos(monto)

    b_inicial, _ = bonos.revisar(bono_txt, codigo) if bonos.normalizar(bono_txt) else (None, "")
    pintar_precio(b_inicial)

    def revisar():
        """Revisa la orden cada pocos segundos hasta que Wompi la apruebe o la rechace."""
        while estado["vivo"] and time.time() - estado["desde"] < REVISAR_MAX_MIN * 60:
            time.sleep(REVISAR_SEG)
            ref = estado["ref"]
            if not ref:
                continue
            try:
                o = sus.orden(ref)
            except Exception as ex:
                print("⚠️ comprar: revisar orden:", ex)
                continue
            if o and o["estado"] == "APROBADO":
                estado["vivo"] = False
                listo_view(page, bar, usuario)
                return
            if o and o["estado"] in ("RECHAZADO", "ERROR", "ANULADO"):
                estado["ref"] = None
                aviso.value = "El pago no se aprobó y no se hizo ningún cobro. Puedes intentarlo otra vez."
                try:
                    page.update()
                except Exception:
                    return

    async def pagar(e):
        aviso.value = "Preparando el pago seguro…"
        page.update()
        try:
            o = await asyncio.to_thread(sus.crear_orden, codigo, plan_id, estado["bono"])
        except Exception as ex:
            if estado["bono"]:  # el bono se ocupó mientras tanto: se puede pagar sin él
                pintar_precio(None)
                aviso.value = f"{ex} Si tocas «Pagar» otra vez, pagas el precio sin bono."
            else:
                aviso.value = f"No se pudo crear el pago: {ex}"
            page.update()
            return
        estado["ref"] = o["referencia"]
        await ft.UrlLauncher().launch_url(f"{API_URL}/pago/ir/{o['referencia']}")
        aviso.value = ("Se abrió el pago de Wompi en otra pestaña. Cuando se apruebe, esta página "
                       "se actualiza sola.")
        page.update()

    def ya_pague(e):
        c = sus.estado(codigo)
        if c["permitido"]:
            estado["vivo"] = False
            listo_view(page, bar, usuario)
        else:
            aviso.value = "Todavía no vemos el pago aprobado. PSE o Nequi pueden tardar unos minutos."
            page.update()

    tarjeta = ft.Container(
        width=360, padding=18, border_radius=18, bgcolor="#0b1220",
        border=ft.Border.all(1, VIOLETA),
        content=ft.Column([
            ft.Text("Tu bar quedó creado", color="#94A3B8", size=13),
            ft.Text(bar["nombre"], color="white", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([ft.Text("Código del bar", color="#94A3B8", size=14, expand=True),
                    ft.Text(codigo, color=CYAN, size=26, weight=ft.FontWeight.BOLD,
                            selectable=True)]),
            ft.Row([ft.Text("Usuario", color="#94A3B8", size=14, expand=True),
                    ft.Text(usuario, color="white", size=16, selectable=True)]),
            ft.Divider(color="#1e293b"),
            ft.Row([ft.Text(p["nombre"] if p else "Plan", color="white", size=15, expand=True),
                    ft.Text(_pesos(p["precio"]) if p else "", color="#94A3B8", size=15)]),
            linea_bono,
            ft.Row([ft.Text("Total a pagar", color="white", size=15, expand=True), total]),
        ], spacing=8))

    _marco(page,
           *_encabezado("Paga tu plan", "Guarda el código de tu bar: lo necesitas para entrar al "
                        "panel. El servicio se activa apenas Wompi apruebe el pago."),
           _pasos(2),
           tarjeta,
           boton_degradado("💳 Pagar con Wompi", pagar, ancho=360),
           aviso,
           ft.OutlinedButton("Ya pagué, revisar", icon=ft.Icons.REFRESH, on_click=ya_pague),
           ft.Text("Tarjeta, PSE, Nequi o Bancolombia en la página segura de Wompi.",
                   color="#64748b", size=12, text_align=ft.TextAlign.CENTER, width=340),
           ft.Text("Si cierras esta página sin pagar, entra a play.alnovix.com/admin con tu código "
                   "y paga desde «Mi plan».", color="#64748b", size=12,
                   text_align=ft.TextAlign.CENTER, width=340))
    threading.Thread(target=revisar, daemon=True).start()


# ---------------------------------------------------------------------------
# Paso 3: listo
# ---------------------------------------------------------------------------
def listo_view(page, bar, usuario):
    codigo = bar["codigo"]

    async def whatsapp(e):
        await ft.UrlLauncher().launch_url(_enlace_whatsapp(bar))

    def entrar(e):
        from views.acceso import acceso_admin_view
        acceso_admin_view(page, codigo)

    _marco(page,
           *_encabezado("¡Tu bar ya tiene PlayBar GO!", "El pago se aprobó y tu plan está activo."),
           _pasos(3),
           ft.Container(
               width=360, padding=18, border_radius=18, bgcolor="#0b1220",
               border=ft.Border.all(1, CYAN),
               content=ft.Column([
                   ft.Row([ft.Text("Código del bar", color="#94A3B8", expand=True),
                           ft.Text(codigo, color=CYAN, size=28, weight=ft.FontWeight.BOLD,
                                   selectable=True)]),
                   ft.Row([ft.Text("Usuario", color="#94A3B8", expand=True),
                           ft.Text(usuario, color="white", size=16, selectable=True)]),
                   ft.Text("Enlace para tus clientes (ponlo en el QR de las mesas):",
                           color="#94A3B8", size=13),
                   ft.Text(f"{URL_CLIENTES}{codigo}", color="white", size=15, selectable=True),
               ], spacing=10)),
           ft.Container(
               width=360, padding=18, border_radius=18, bgcolor="#052e16",
               border=ft.Border.all(1, "#16a34a"),
               content=ft.Column([
                   ft.Text("Último paso: el reproductor", color="white", size=17,
                           weight=ft.FontWeight.BOLD),
                   ft.Text("Escríbenos por WhatsApp y te asignamos la llave para el computador "
                           "o el televisor de tu bar.", color="#bbf7d0", size=14),
                   ft.Container(
                       height=50, border_radius=14, bgcolor="#16a34a",
                       content=ft.TextButton(
                           content=ft.Text("Pedir la llave por WhatsApp · 301 613 0044",
                                           color="white", weight=ft.FontWeight.BOLD),
                           on_click=whatsapp)),
               ], spacing=10)),
           boton_degradado("Entrar a mi panel", entrar, ancho=360))
