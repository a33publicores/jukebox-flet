"""
💳 Mi plan — sección de pagos del negocio (panel del administrador del bar).

Muestra la prueba gratis (cuántas canciones van) o el plan activo y su vencimiento, los
planes disponibles y el historial. "Pagar con Wompi" crea la orden y abre el pago seguro de
Wompi (igual que en ALNOVIX); al aprobarse, el plan se activa solo.
"""
import asyncio
import os

import flet as ft

from services import suscripcion as sus
from services.exportar import fecha_local

CYAN = "#00D4FF"
VIOLETA = "#B44CFF"
API_URL = (os.getenv("PLAYBAR_API_URL", "").strip().rstrip("/")
           or "https://playbar-api-production.up.railway.app")
COLOR_ESTADO = {"APROBADO": "#22c55e", "PENDIENTE": "#facc15"}


def _pesos(n):
    return "$" + f"{int(n):,}".replace(",", ".")


def _boton(texto, on_click, ancho=300):
    return ft.Container(
        width=ancho, height=50, border_radius=16,
        gradient=ft.LinearGradient(colors=[CYAN, VIOLETA]),
        content=ft.TextButton(content=ft.Text(texto, color="white", size=16,
                                              weight=ft.FontWeight.BOLD), on_click=on_click),
    )


def plan_view(page, codigo, nombre, logo, bono_txt=""):
    from services import bonos

    page.clean()
    page.bgcolor = "#020617"
    page.scroll = ft.ScrollMode.AUTO
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START

    try:
        e = sus.estado(codigo)
        planes = sus.planes_con_precio(codigo)
        historial = sus.pagos(codigo, 10)
    except Exception as ex:
        page.add(ft.Text(f"No se pudo leer el plan: {ex}", color="#f87171"))
        page.update()
        return
    aviso = ft.Text("", color="#facc15", size=13, text_align=ft.TextAlign.CENTER, width=380)

    # Código de bono de referido: descuenta en UN pago (el servidor vuelve a calcular el precio)
    b, msg_bono = bonos.revisar(bono_txt, codigo) if bonos.normalizar(bono_txt) else (None, "")
    campo_bono = ft.TextField(label="Código de bono (opcional)", value=bonos.normalizar(bono_txt),
                              width=240, color="white", border_color="#334155",
                              focused_border_color=CYAN, hint_text="PBG-XXXXXX",
                              capitalization=ft.TextCapitalization.CHARACTERS)
    nota_bono = ft.Text(msg_bono or (f"Bono aplicado: −{_pesos(b['descuento'])} en este pago"
                                     if b else ""),
                        color="#f87171" if msg_bono else "#4ade80", size=13, width=380)

    def aplicar_bono(ev=None):
        plan_view(page, codigo, nombre, logo, campo_bono.value)

    campo_bono.on_submit = aplicar_bono

    def volver(ev=None):
        from views.admin import admin_view
        admin_view(page, codigo, nombre, logo)

    def pagar(p):
        async def _pagar(ev):
            aviso.value = "Preparando el pago seguro…"
            page.update()
            try:
                o = await asyncio.to_thread(sus.crear_orden, codigo, p["id"],
                                            b["codigo"] if b else "")
            except Exception as ex:
                aviso.value = f"No se pudo crear el pago: {ex}"
                page.update()
                return
            await ft.UrlLauncher().launch_url(f"{API_URL}/pago/ir/{o['referencia']}")
            aviso.value = ("Se abrió la página de Wompi. Cuando termines, vuelve aquí y toca "
                           "«Ya pagué, actualizar».")
            page.update()
        return _pagar

    color = "#22c55e" if e["permitido"] and not e["aviso"] else ("#facc15" if e["permitido"] else "#f87171")
    detalle = [ft.Text(e["titulo"], size=20, color=color, weight=ft.FontWeight.BOLD),
               ft.Text(e["mensaje"], color="#cbd5e1", size=14)]
    if e["estado"] == "prueba" and e["limite"]:
        detalle.append(ft.ProgressBar(value=min(1, e["usadas"] / e["limite"]), color=color,
                                      bgcolor="#1e293b", bar_height=10))

    tarjetas = [ft.Container(
        width=380, padding=16, border_radius=16, bgcolor="#0f172a",
        border=ft.Border.all(1, "#1e293b"),
        content=ft.Column([
            ft.Text(p["nombre"], color="white", size=16, weight=ft.FontWeight.BOLD),
            ft.Text(_pesos(bonos.precio_con_bono(p["precio"], b)[0]), color="white", size=28,
                    weight=ft.FontWeight.BOLD),
            *([ft.Text(f"Antes {_pesos(p['precio'])} · con bono {b['codigo']}",
                       color="#4ade80", size=13)]
              if b and bonos.precio_con_bono(p["precio"], b)[1] else []),
            *([ft.Text(f"🔥 {p['promo_txt']}", color="#facc15", size=13)]
              if p.get("promo_txt") else []),
            ft.Text(f"{p['dias']} días de música sin límite", color="#94A3B8", size=13),
            _boton("💳 Pagar con Wompi", pagar(p), ancho=348),
        ], spacing=6),
    ) for p in planes]

    filas = [ft.Row([
        ft.Text(fecha_local(o["creado"])[:16], color="#94A3B8", size=12, width=120),
        ft.Text(f"{o['plan_nombre']} {_pesos(o['monto'])}", color="white", size=12, expand=True),
        ft.Text(o["estado"], color=COLOR_ESTADO.get(o["estado"], "#f87171"), size=12),
    ]) for o in historial]

    page.add(ft.Container(width=420, padding=16, content=ft.Column(
        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=14, controls=[
            ft.Row([ft.IconButton(icon=ft.Icons.ARROW_BACK, icon_color="white", on_click=volver),
                    ft.Text(f"💳 Mi plan · {nombre}", size=20, color="white",
                            weight=ft.FontWeight.BOLD, expand=True)]),
            ft.Container(width=380, padding=16, border_radius=16, bgcolor="#0b1220",
                         border=ft.Border.all(1, color), content=ft.Column(detalle, spacing=8)),
            ft.Row([campo_bono, ft.OutlinedButton("Aplicar", on_click=aplicar_bono)],
                   width=380, alignment=ft.MainAxisAlignment.CENTER),
            nota_bono,
            *(tarjetas or [ft.Text("No hay planes disponibles por ahora.", color="#94A3B8")]),
            aviso,
            ft.OutlinedButton("Ya pagué, actualizar", icon=ft.Icons.REFRESH,
                              on_click=lambda ev: plan_view(page, codigo, nombre, logo)),
            ft.Text("Pagas con tarjeta, PSE, Nequi o Bancolombia en la página segura de Wompi. "
                    "El plan se activa solo apenas se aprueba.", color="#64748b", size=12,
                    text_align=ft.TextAlign.CENTER, width=380),
            *([ft.Text("HISTORIAL DE PAGOS", color="#94A3B8", size=12, weight=ft.FontWeight.BOLD),
               ft.Column(filas, width=380, spacing=6)] if filas else []),
        ])))
    page.update()
