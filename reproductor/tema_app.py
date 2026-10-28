"""
Tema de temporada en el reproductor (PC y TV; este archivo es igual en los dos).

El super administrador escoge el tema en /super → 🎨 Temas (Navidad, Halloween...). El
reproductor lo pregunta a la API cada 3 minutos y lo aplica al panel de la derecha:
color de fondo, adornos junto al logo, el mensaje y un efecto que cae (nieve, murciélagos...).
Sin tema (o sin internet) queda como siempre.
"""
import asyncio
import json
import random

import flet as ft

CADA_SEG = 180
PARTICULAS = 10
PASO_SEG = 0.5


class TemaApp:
    def __init__(self, fondo_normal):
        self.fondo_normal = fondo_normal
        self.panel = None  # el Container del panel de la derecha (se le cambia el color)
        self.adorno_izq = ft.Text("", size=24)
        self.adorno_der = ft.Text("", size=24)
        self.t_mensaje = ft.Text("", size=13, weight=ft.FontWeight.BOLD, color="white",
                                 text_align=ft.TextAlign.CENTER)
        self.mensaje = ft.Container(visible=False, padding=8, border_radius=12,
                                    margin=ft.Margin.symmetric(horizontal=10, vertical=0),
                                    content=self.t_mensaje)
        # el efecto: va DETRÁS del contenido (no tapa botones) y ocupa todo el panel
        self.capa = ft.Stack([], left=0, top=0, right=0, bottom=0)
        self._firma = None
        self._figuras = []
        self._parts = []

    def logo(self, imagen):
        """La fila del logo con los adornos a los lados."""
        self.img, self.logo_normal = imagen, imagen.src
        return ft.Row([self.adorno_izq, imagen, self.adorno_der],
                      alignment=ft.MainAxisAlignment.CENTER,
                      vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def envolver(self, contenido):
        """El panel con el efecto de fondo (se ve en los espacios libres, nunca tapa nada)."""
        return ft.Stack([self.capa, contenido])

    def aplicar(self, tema):
        firma = json.dumps(tema or None, sort_keys=True)
        if firma == self._firma:
            return
        self._firma = firma
        c = (tema or {}).get("colores") or {}
        if self.panel is not None:
            self.panel.bgcolor = c.get("fondo") or self.fondo_normal
        if getattr(self, "img", None) is not None:
            self.img.src = (tema or {}).get("logo_url") or self.logo_normal
        ad = (tema or {}).get("adornos") or ""
        self.adorno_izq.value = self.adorno_der.value = ad
        msg = (tema or {}).get("mensaje") or ""
        self.t_mensaje.value = msg
        self.t_mensaje.color = c.get("texto") or "white"
        self.mensaje.bgcolor = c.get("panel") or "#0f172a"
        self.mensaje.border = ft.Border.all(1, c.get("acento2") or "#a78bfa")
        self.mensaje.visible = bool(msg)
        self._figuras = list((tema or {}).get("figuras") or [])
        self._parts = []
        for _ in range(PARTICULAS if self._figuras else 0):
            t = ft.Text(random.choice(self._figuras), size=random.randint(14, 26), opacity=0.85,
                        left=random.randint(0, 340), top=random.randint(-600, 0),
                        animate_position=ft.Animation(int(PASO_SEG * 1000), ft.AnimationCurve.LINEAR))
            t.data = random.uniform(25, 60)  # velocidad (pixeles por segundo)
            self._parts.append(t)
        self.capa.controls = self._parts
        print(f"🎨 Tema: {(tema or {}).get('nombre') or 'normal'}")

    async def vigilar(self, api, page):
        """Pregunta el tema cada 3 minutos y mueve el efecto."""
        siguiente = 0.0
        while True:
            ahora = asyncio.get_event_loop().time()
            if ahora >= siguiente:
                siguiente = ahora + CADA_SEG
                try:
                    d = await asyncio.to_thread(api.tema)
                    antes = self._firma
                    self.aplicar(d.get("tema"))
                    if self._firma != antes:
                        page.update()
                except Exception as ex:
                    print(f"ℹ️ Tema: {type(ex).__name__}")  # sin red o API vieja: sigue igual
            if self._parts:
                alto = (page.height or 720) + 40
                for p in self._parts:
                    if p.top > alto:  # salió por abajo: vuelve arriba (sin animar el salto)
                        p.animate_position = None
                        p.top, p.left = -30, random.randint(0, 340)
                    else:
                        if p.animate_position is None:
                            p.animate_position = ft.Animation(int(PASO_SEG * 1000), ft.AnimationCurve.LINEAR)
                        p.top += p.data * PASO_SEG
                try:
                    self.capa.update()
                except Exception:
                    pass
            await asyncio.sleep(PASO_SEG)
