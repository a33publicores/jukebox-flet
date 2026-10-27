"""
Pantalla del reproductor PlayBar GO para TV (Android TV, Google TV, Fire TV, TV Box).

Es el mismo reproductor del PC (mismo motor, misma API, mismas reglas de cola y relleno)
con una pantalla pensada para la TV:
  * siempre en pantalla completa: video a la izquierda, logo + playlist a la derecha;
  * se maneja con el CONTROL REMOTO (no hay mouse ni pantalla táctil):
        OK / ▶❚❚ ............ pausar / reanudar
        ▶  (derecha) / ⏭ ..... siguiente canción
        ◀  (izquierda) / ⏮ ... canción anterior
        ▲ ▼ / Menú / Info .... abre el menú (cambiar código, ver registro…)
  * descarga sin ffmpeg (ver descargas_tv.py).
"""
import asyncio
import os
import sys
import threading
import time

import flet as ft
import flet_video as ftv

from tv import config as CFG
from tv import actualizador_tv, descargas_tv, dns_respaldo
from tv.api_cliente import ApiCliente, LlaveInvalida
from tv.fundido import Fundido
from tv.motor import BackendApi, Motor
from tv.version import API_POR_DEFECTO, VERSION

FONDO = "#020617"
PANEL = "#0b1220"
CYAN = "#00D4FF"
VIOLETA = "#B44CFF"
PUESTOS = 3  # lugares fijos en la lista del video: el que suena, el siguiente y uno libre

# Teclas del control remoto (nombres que entrega Flutter). Cada marca de TV manda algo
# distinto: las teclas que no se reconocen quedan anotadas en registro.txt.
T_PAUSA = {"select", "enter", "numpad enter", "media play pause", "media play", "media pause",
           " ", "space", "game button a"}
T_SIGUIENTE = {"arrow right", "media track next", "media fast forward", "channel up"}
T_ANTERIOR = {"arrow left", "media track previous", "media rewind", "channel down"}
T_MENU = {"arrow up", "arrow down", "context menu", "info", "guide", "settings", "m",
          "escape", "go back", "browser back", "game button y"}


def _misma(a, b):
    if not a or not b:
        return False
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def _segundos(d):
    """Convierte lo que manda el video (Duration, dict o milisegundos) a segundos."""
    if d is None:
        return 0.0
    if isinstance(d, (int, float)):
        return float(d) / 1000.0
    if isinstance(d, str):
        try:
            return float(d) / 1000.0
        except ValueError:
            return 0.0
    if isinstance(d, dict):
        g = d.get
    else:
        def g(k, v=0):
            return getattr(d, k, v)
    return ((g("days", 0) or 0) * 86400 + (g("hours", 0) or 0) * 3600
            + (g("minutes", 0) or 0) * 60 + (g("seconds", 0) or 0)
            + (g("milliseconds", 0) or 0) / 1000.0 + (g("microseconds", 0) or 0) / 1e6)


def _mmss(s):
    s = max(0, int(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _miniatura(video_id):
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


class Pantalla:
    """Interfaz que usa el Motor (reproducir, pausar, mostrar...)."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.motor = None
        self.token = 0
        self._firma = None
        self.menu_abierto = False

        self.video = ftv.Video(
            expand=True,
            playlist=[],
            autoplay=True,
            controls=None,
            fill_color="#000000",
            playlist_mode=ftv.PlaylistMode.LOOP,
            # Es una rockola: si el TV pasa a otra app o al protector de pantalla, sigue sonando.
            pause_upon_entering_background_mode=False,
            resume_upon_entering_foreground_mode=False,
            on_complete=self._on_complete,
            on_track_change=self._on_pista,
            on_error=self._on_error,
            on_position_change=self._on_posicion,
            on_duration_change=self._on_duracion,
        )
        # Puestos fijos (igual que en el PC): la lista del video se arma una vez y después
        # solo se salta entre puestos, así la siguiente canción entra sin pausa.
        self.puestos = [CFG.CARPETA / "en_cola" / f"puesto{i}.mp4" for i in range(PUESTOS)]
        self.fuente = [None] * PUESTOS
        self.anticipada = [False] * PUESTOS
        self.cur = 0
        self._lista_armada = False
        self._salto = None
        self._entro_sola = None
        self._lock_puestos = asyncio.Lock()
        self.fundido = Fundido(self.video)  # mezcla suave entre canciones
        self.dur = 0.0
        self.pos = 0.0
        self._ult_seg = -1
        self._terminado_token = -1
        self._t_inicio = self._t_real = time.time()

        self.barra = ft.ProgressBar(value=0, expand=True, color=CYAN, bgcolor="#334155",
                                    bar_height=4)
        self.t_pos = ft.Text("0:00", size=12, color="white", weight=ft.FontWeight.BOLD)
        self.t_dur = ft.Text("0:00", size=12, color="#94A3B8")
        self.t_pausa = ft.Container(
            visible=False, alignment=ft.Alignment.CENTER, left=0, right=0, top=0, bottom=0,
            content=ft.Container(
                padding=ft.Padding.symmetric(horizontal=22, vertical=12), border_radius=16,
                bgcolor="#000000B3",
                content=ft.Text("⏸ En pausa · OK para seguir", size=18, color="white",
                                weight=ft.FontWeight.BOLD)),
        )
        self.encabezado = ft.Column(spacing=8, controls=[
            ft.Text("Descargando la primera canción…", size=13, color="#94A3B8")])
        self.lista = ft.ListView(expand=True, spacing=8,
                                 padding=ft.Padding.only(left=10, right=10, bottom=10))
        self._url_pago = ""
        self.t_plan_titulo = ft.Text("", size=26, color="white", weight=ft.FontWeight.BOLD,
                                     text_align=ft.TextAlign.CENTER)
        self.t_plan_msg = ft.Text("", size=15, color="#cbd5e1", text_align=ft.TextAlign.CENTER,
                                  width=520)
        self.t_plan_url = ft.Text("", size=14, color=CYAN, text_align=ft.TextAlign.CENTER,
                                  width=520, selectable=True)
        # Un solo reproductor por bar: si se abre en otro equipo, este se detiene.
        self.t_otro = ft.Text("", size=15, color="#cbd5e1", text_align=ft.TextAlign.CENTER,
                              width=520)
        self.capa_otro = ft.Container(
            visible=False, left=0, right=0, top=0, bottom=0, bgcolor="#020617F2",
            alignment=ft.Alignment.CENTER,
            content=ft.Column([
                ft.Image(src="/logo.png", height=80, fit=ft.BoxFit.CONTAIN),
                ft.Text("PlayBar GO se está usando en otro equipo", size=24, color="white",
                        weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
                self.t_otro,
                ft.Container(
                    width=300, height=52, border_radius=16, bgcolor=CYAN,
                    border=ft.Border.all(3, "white"), alignment=ft.Alignment.CENTER,
                    content=ft.Text("▶ Usar aquí (OK)", color=FONDO, size=18,
                                    weight=ft.FontWeight.BOLD),
                ),
                ft.Text("Presiona OK en el control para que la música pase a este TV.",
                        color="#64748b", size=12),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, tight=True),
        )
        self.capa_plan = ft.Container(
            visible=False, left=0, right=0, top=0, bottom=0, bgcolor="#020617EE",
            alignment=ft.Alignment.CENTER,
            content=ft.Column([
                ft.Image(src="/logo.png", height=80, fit=ft.BoxFit.CONTAIN),
                self.t_plan_titulo, self.t_plan_msg,
                ft.Text("Para pagar, abre este enlace en tu celular:", color="#94A3B8", size=13),
                self.t_plan_url,
                ft.Text("Apenas se apruebe el pago, la música vuelve sola.", color="#64748b",
                        size=12),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12, tight=True),
        )
        self.t_aviso_act = ft.Text("", color="white", size=12)
        self.aviso_act = ft.Container(
            visible=False, padding=8, margin=ft.Margin.symmetric(horizontal=10, vertical=0),
            border_radius=10, bgcolor="#0e7490", content=self.t_aviso_act,
        )
        self.t_aviso_plan = ft.Text("", color="white", size=12)
        self.aviso_plan = ft.Container(
            visible=False, padding=8, margin=ft.Margin.symmetric(horizontal=10, vertical=0),
            border_radius=10, bgcolor="#713f12", content=self.t_aviso_plan,
        )

    # ------------------------------------------------------------ eventos
    async def _on_complete(self, e):
        # Igual que en el PC: el fin llega como cambio de puesto (_on_pista).
        pass

    async def _on_pista(self, e):
        try:
            idx = int(str(e.data).strip())
        except Exception:
            return
        if self._salto is not None and idx == self._salto:
            self._salto = None
            self.cur = idx
            return
        if idx == self.cur or not self._lista_armada:
            return
        self.cur = idx
        if self.anticipada[idx] and self.fuente[idx]:
            self._entro_sola = (idx, self.fuente[idx])
        else:
            self._entro_sola = None
            try:
                await self.video.pause()
            except Exception:
                pass
        self.anticipada[idx] = False
        self._reiniciar_tiempo()
        await self._terminar_una_vez()

    async def _terminar_una_vez(self):
        if self.motor and self._terminado_token != self.token:
            self._terminado_token = self.token
            await self.motor.al_terminar(self.token)

    async def vigilar_final(self):
        """Respaldo: si el video quedó quieto en el final 3 s, pasa a la siguiente."""
        quieto = 0
        ultimo = -1.0
        while True:
            await asyncio.sleep(1)
            try:
                if (not self.motor or self.motor.pausado or self.dur <= 0
                        or time.time() - self._t_real < 8):
                    quieto, ultimo = 0, self.pos
                    continue
                cerca_del_final = self.dur - 1.0 <= self.pos <= self.dur + 2
                quieto = quieto + 1 if abs(self.pos - ultimo) < 0.2 else 0
                ultimo = self.pos
                if cerca_del_final and quieto >= 3:
                    quieto = 0
                    token = self.token
                    try:
                        pos = _segundos(await self.video.get_current_position())
                        dur = _segundos(await self.video.get_duration())
                    except Exception:
                        continue
                    if token == self.token and dur > 0 and pos >= dur - 1.5:
                        print(f"⏭️ Fin detectado por el vigilante ({pos:.0f}/{dur:.0f} s)")
                        await self._terminar_una_vez()
            except asyncio.CancelledError:
                raise
            except Exception as ex:
                print("⚠️ vigilante:", ex)

    async def _on_duracion(self, e):
        dur = _segundos(e.data)
        if dur <= 0:
            return
        self.dur = dur
        self.t_dur.value = _mmss(self.dur)
        try:
            self.t_dur.update()
        except Exception:
            pass

    async def _on_posicion(self, e):
        pos = _segundos(e.data)
        if pos > (time.time() - self._t_inicio) + 4:  # aviso tardío de la canción anterior
            return
        self.pos = pos
        if int(pos) == self._ult_seg:
            return
        self._ult_seg = int(pos)
        self.fundido.posicion(pos, self.dur, bool(self.motor and self.motor.pausado))
        if self.dur <= 0:
            try:
                self.dur = _segundos(await self.video.get_duration())
                self.t_dur.value = _mmss(self.dur)
            except Exception:
                pass
        self.t_pos.value = _mmss(pos)
        self.barra.value = min(1.0, pos / self.dur) if self.dur > 0 else 0
        try:
            self.t_pos.update()
            self.t_dur.update()
            self.barra.update()
        except Exception:
            pass

    def _reiniciar_tiempo(self):
        self.fundido.nueva()  # la canción nueva entra suave
        self.dur, self.pos, self._ult_seg = 0.0, 0.0, -1
        self._t_inicio = self._t_real = time.time()
        self.t_pos.value, self.t_dur.value, self.barra.value = "0:00", "0:00", 0

    async def _on_error(self, e):
        print(f"❌ Error del video: {e.data}")
        token = self.token
        await asyncio.sleep(2)
        if token != self.token or self.pos >= 1.0 or (self.motor and self.motor.pausado):
            print("ℹ️ aviso de error ignorado: la canción actual suena bien")
            return
        if self.motor:
            await self.motor.al_error(token, str(e.data))

    def aviso_actualizacion(self, texto):
        self.t_aviso_act.value = texto
        self.aviso_act.visible = bool(texto)
        try:
            self.page.update()
        except Exception:
            pass

    # ------------------------------------------- un solo reproductor por bar
    async def mostrar_otro_equipo(self, equipo):
        """El bar quedó sonando en otro equipo: este se detiene y ofrece "Usar aquí"."""
        try:
            self.t_otro.value = f"Ahora está sonando en «{equipo}»."
            self.capa_otro.visible = True
            self.page.update()
        except Exception:
            pass

    async def ocultar_otro_equipo(self):
        try:
            self.capa_otro.visible = False
            self.page.update()
        except Exception:
            pass

    def _usar_aqui(self, e=None):
        if getattr(self, "motor", None) is not None:
            self.page.run_task(self.motor.usar_aqui)

    # ------------------------------------------- prueba gratis / plan del bar
    async def mostrar_plan(self, info, sonando=False):
        info = info or {}
        self._url_pago = info.get("url_pago") or self._url_pago
        permitido = info.get("permitido", True)
        titulo, msg = info.get("titulo", ""), info.get("mensaje", "")
        try:
            if not permitido and not sonando:
                self.t_plan_titulo.value = "🔒 " + (titulo or "Plan no activo")
                self.t_plan_msg.value = msg
                self.t_plan_url.value = self._url_pago or "Pídelo al administrador de PlayBar GO."
                self.capa_plan.visible = True
                self.aviso_plan.visible = False
            else:
                self.capa_plan.visible = False
                if not permitido:
                    self.t_aviso_plan.value = f"🔒 {titulo}: esta es la última canción."
                    self.aviso_plan.bgcolor = "#7f1d1d"
                    self.aviso_plan.visible = True
                elif info.get("aviso"):
                    self.t_aviso_plan.value = f"⏳ {titulo}: {msg}"
                    self.aviso_plan.bgcolor = "#713f12"
                    self.aviso_plan.visible = True
                else:
                    self.aviso_plan.visible = False
            self.page.update()
        except Exception as ex:
            print("⚠️ aviso del plan:", ex)

    # --------------------------------------------- interfaz que usa el Motor
    async def reproducir(self, ruta, item, token):
        self.token = token
        if self.motor is not None and hasattr(self.motor.desc, "marcar_uso"):
            self.motor.desc.marcar_uso(ruta)  # la que suena es la última en borrarse
        entro = self._entro_sola
        self._entro_sola = None
        if entro and entro[0] == self.cur and _misma(entro[1], ruta):
            pass
        elif not self._lista_armada:
            await self._armar_lista(ruta)
        else:
            async with self._lock_puestos:
                destino = None
                for cand in ((self.cur + 1) % PUESTOS, (self.cur + 2) % PUESTOS):
                    try:
                        await asyncio.to_thread(self._poner_en_puesto, cand, ruta)
                        destino = cand
                        break
                    except Exception as ex:
                        print(f"⚠️ Puesto {cand} ocupado: {ex}")
                if destino is None:
                    raise RuntimeError("No hay puesto libre para la canción")
                self.anticipada[destino] = False
                self._salto = destino
                self._reiniciar_tiempo()
                try:
                    await self.video.jump_to(destino)
                except Exception as ex:
                    print(f"⚠️ No se pudo saltar al puesto {destino}: {ex}")
                self.cur = destino
        try:
            await self.video.play()
        except Exception:
            pass
        self.t_pausa.visible = False
        self.page.update()

    async def preparar_siguiente(self, ruta):
        if not self._lista_armada:
            return
        async with self._lock_puestos:
            sig = (self.cur + 1) % PUESTOS
            if ruta is None:
                self.anticipada[sig] = False
                return
            if self.anticipada[sig] and _misma(self.fuente[sig], ruta):
                return
            try:
                await asyncio.to_thread(self._poner_en_puesto, sig, ruta)
                self.anticipada[sig] = True
            except Exception as ex:
                self.anticipada[sig] = False
                print(f"⚠️ No se pudo dejar lista la siguiente: {ex}")

    async def _armar_lista(self, ruta):
        for i in range(PUESTOS):
            await asyncio.to_thread(self._poner_en_puesto, i, ruta)
        self.anticipada = [False] * PUESTOS
        self.cur = 0
        self._reiniciar_tiempo()
        self.video.playlist = [ftv.VideoMedia(resource=str(p)) for p in self.puestos]
        self.video.update()
        self._lista_armada = True

    def _poner_en_puesto(self, i, ruta):
        """Enlace al archivo guardado (instantáneo); si Android no deja, se copia."""
        destino = self.puestos[i]
        if _misma(self.fuente[i], ruta) and destino.exists():
            return
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_name(destino.stem + ".tmp")
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        try:
            os.link(ruta, tmp)
        except Exception:
            import shutil
            shutil.copyfile(ruta, tmp)
        os.replace(tmp, destino)
        self.fuente[i] = str(ruta)

    async def pausar(self):
        await self.video.pause()
        self.t_pausa.visible = True
        self.page.update()

    async def reanudar(self):
        self.fundido.normal()
        await self.video.play()
        self.t_pausa.visible = False
        self.page.update()

    async def ir_a(self, segundos):
        """Televisor espejo: salta a la parte donde va el principal."""
        seg = max(0.0, float(segundos or 0))
        if self.dur > 0:
            seg = min(seg, max(0.0, self.dur - 1))
        try:
            await self.video.seek(ft.Duration(milliseconds=int(seg * 1000)))
            self.pos = seg
            self._t_inicio = time.time() - seg
            self._ult_seg = -1
        except Exception as ex:
            print("⚠️ No se pudo adelantar al punto del principal:", ex)

    async def estado(self, texto):
        if texto and self.motor and self.motor.actual is None:
            self.encabezado.controls = [ft.Text(texto, size=13, color="#94A3B8")]
            self.page.update()

    async def mostrar(self, actual, cola, relleno, pausado, error):
        firma = (
            actual.video_id if actual else None, relleno, pausado, error,
            tuple((i.fila, i.video_id) for i in cola),
        )
        if firma == self._firma:
            return
        self._firma = firma

        filas = []
        if error:
            filas.append(ft.Container(
                padding=8, border_radius=10, bgcolor="#7f1d1d",
                content=ft.Text(error if error.startswith("💾") else
                                f"⚠️ {error[:120]}\nLa música sigue sonando; los pedidos nuevos "
                                "llegan solos cuando vuelva la conexión.",
                                size=11, color="white"),
            ))
        if actual:
            filas.append(self._tarjeta(
                actual, "RELLENO · del historial" if relleno else "EN REPRODUCCIÓN",
                resaltada=True))
        else:
            filas.append(ft.Text("Esperando canciones…", size=13, color="#94A3B8"))
        if cola:
            filas.append(ft.Text(f"SIGUE ({len(cola)})", size=11, color="#94A3B8",
                                 weight=ft.FontWeight.BOLD))
        elif actual:
            filas.append(ft.Text("No hay más canciones en cola", size=11, color="#94A3B8"))
        self.encabezado.controls = filas
        self.lista.controls = [self._tarjeta(it, "") for it in cola[:30]]
        self.t_pausa.visible = bool(pausado and actual)
        self.page.update()

    # ------------------------------------------------------------- piezas
    def _tarjeta(self, item, etiqueta, resaltada=False):
        info = [
            ft.Text(item.titulo, size=13, weight=ft.FontWeight.BOLD, color="white",
                    max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(item.canal, size=10, color="#94A3B8", max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS),
        ]
        if etiqueta:
            info.insert(0, ft.Text(etiqueta, size=10, weight=ft.FontWeight.BOLD,
                                   color=CYAN if "REPRO" in etiqueta else VIOLETA))
        return ft.Container(
            padding=6, border_radius=10,
            bgcolor="#12203a" if resaltada else PANEL,
            border=ft.Border.all(1, CYAN) if resaltada else None,
            content=ft.Row([
                ft.Image(src=_miniatura(item.video_id), width=80, height=45,
                         fit=ft.BoxFit.COVER, border_radius=6),
                ft.Column(info, spacing=1, expand=True),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def construir(self):
        tiempo = ft.Container(
            left=0, right=0, bottom=0,
            padding=ft.Padding.symmetric(horizontal=14, vertical=8), bgcolor="#000000B3",
            content=ft.Row([self.t_pos, self.barra, self.t_dur], spacing=10,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )
        video = ft.Stack(
            expand=7,
            controls=[
                ft.Container(content=self.video, expand=True, bgcolor="#000000",
                             left=0, right=0, top=0, bottom=0),
                tiempo, self.t_pausa, self.capa_plan, self.capa_otro,
            ],
        )
        # El logo de PlayBar GO SIEMPRE visible encima de la playlist.
        logo = ft.Container(
            padding=ft.Padding.only(top=12, bottom=8),
            content=ft.Row([ft.Image(src="/logo.png", height=56, fit=ft.BoxFit.CONTAIN)],
                           alignment=ft.MainAxisAlignment.CENTER),
        )
        ayuda = ft.Container(
            padding=ft.Padding.symmetric(horizontal=10, vertical=6), bgcolor=PANEL,
            content=ft.Text("OK pausa · ◀ ▶ anterior/siguiente · ▲ menú", size=10,
                            color="#64748b", text_align=ft.TextAlign.CENTER),
        )
        derecha = ft.Container(
            expand=3, bgcolor=FONDO,
            border=ft.Border.only(left=ft.BorderSide(1, "#1e293b")),
            content=ft.Column(spacing=6, controls=[
                logo, self.aviso_act, self.aviso_plan,
                ft.Container(content=self.encabezado, padding=ft.Padding.symmetric(horizontal=10)),
                self.lista, ayuda,
            ]),
        )
        return ft.Row([video, derecha], expand=True, spacing=0)


# =============================================================================
# Pantallas de arranque
# =============================================================================
def _limpiar(page):
    page.controls.clear()
    page.overlay.clear()


# Teclado propio de la pantalla de configuración. No usa el teclado del sistema: en
# muchos TV ese teclado sale pero no responde al control remoto (o ni sale). Este se
# maneja con las flechas y OK; los números del control y un teclado USB/PC escriben directo.
TECLADO = [list("1234567890"), list("ABCDEFGHJK"), list("LMNPQRSTUV"),
           list("WXYZ-") + ["⌫"], ["Código", "Llave", "Guardar y empezar"]]
T_ARRIBA, T_ABAJO = {"arrow up"}, {"arrow down"}
T_IZQ, T_DER = {"arrow left"}, {"arrow right"}
T_OK = {"select", "enter", "numpad enter", "game button a", "dpad center", "space", " "}
T_BORRAR = {"backspace", "delete", "del"}


async def _pantalla_config(page: ft.Page, mensaje=""):
    """Primera vez: código del lugar + llave del bar (las da el super administrador)."""
    _limpiar(page)
    previo = CFG.leer_config()
    url = previo.get("api") or API_POR_DEFECTO
    valores = {"Código": str(previo.get("cliente", "")), "Llave": str(previo.get("llave", ""))}
    est = {"campo": "Código" if not valores["Código"] else "Llave", "fila": 0, "col": 0,
           "ocupado": False}
    texto = ft.Text(mensaje, color="#fca5a5", text_align=ft.TextAlign.CENTER)
    hecho = asyncio.Event()
    cajas = {}       # nombre -> (caja, texto del valor)
    teclas_ui = []   # filas de cajas de las teclas (para resaltar la seleccionada)

    def armar():
        """Datos a la izquierda y teclado a la derecha, escalados al tamaño de la pantalla:
        cabe completo en un TV grande, uno pequeño o un TV Box HD (desde 640×360 puntos).
        Se vuelve a armar si cambia el tamaño (ventana en el PC)."""
        ancho_p, alto_p = float(page.width or 960), float(page.height or 540)
        k = max(0.5, min(1.15, (ancho_p - 24) / 800, (alto_p - 24) / 400))

        def z(n):
            return round(n * k)

        texto.width, texto.size = z(320), max(9, z(12))
        cajas.clear()
        for nombre, ejemplo in (("Código", "ej. 8523"), ("Llave", "ej. K7M4-X9P2")):
            valor = ft.Text("", size=z(20), color="white", weight=ft.FontWeight.BOLD)
            etiqueta = "Código del lugar" if nombre == "Código" else "Llave del bar"
            cajas[nombre] = (ft.Container(
                width=z(320), padding=ft.Padding.symmetric(horizontal=z(12), vertical=z(6)),
                border_radius=z(12), bgcolor=PANEL,
                content=ft.Column([ft.Text(f"{etiqueta} ({ejemplo})", size=max(8, z(13)),
                                           color="#94A3B8"), valor], spacing=2)), valor)
        teclas_ui.clear()
        filas_ui = []
        for f, fila in enumerate(TECLADO):
            fila_ui = []
            for c, t in enumerate(fila):
                ancho = 36 if f < 4 else (90 if t != "Guardar y empezar" else 180)
                fila_ui.append(ft.Container(
                    width=z(ancho if t != "⌫" else 78), height=z(36), border_radius=z(8),
                    alignment=ft.Alignment.CENTER,
                    content=ft.Text(t, size=max(8, z(16 if f < 4 else 13)),
                                    weight=ft.FontWeight.BOLD)))
            teclas_ui.append(fila_ui)
            # GestureDetector (no on_click): así las teclas no toman el foco de Flutter y el
            # OK del control no las activa dos veces; el mouse y lo táctil siguen sirviendo.
            filas_ui.append(ft.Row(
                [ft.GestureDetector(content=caja, on_tap=lambda e, f=f, c=c: pulsar(f, c))
                 for c, caja in enumerate(fila_ui)],
                spacing=z(5), alignment=ft.MainAxisAlignment.CENTER))
        izquierda = ft.Column(
            [ft.Image(src="/logo.png", width=z(90)),
             ft.Text("Configurar reproductor de TV", size=z(17), color="white",
                     weight=ft.FontWeight.BOLD),
             ft.Text("Usa las flechas y OK del control. El código y la llave te los da el "
                     "administrador de PlayBar GO.", color="#94A3B8", size=max(8, z(11)),
                     width=z(320), text_align=ft.TextAlign.CENTER),
             *[ft.GestureDetector(content=cajas[n][0], on_tap=lambda e, n=n: elegir_campo(n))
               for n in ("Código", "Llave")],
             texto],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=z(8), tight=True)
        derecha = ft.Column(filas_ui, spacing=z(5), tight=True,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER)
        page.controls.clear()
        # Anchos fijos por columna: si no, cada columna ocupa todo el ancho y quedan apiladas.
        page.add(ft.Container(expand=True, alignment=ft.Alignment.CENTER, padding=8, content=ft.Row(
            [ft.Container(width=z(330), content=izquierda),
             ft.Container(width=z(420), content=derecha)],
            spacing=z(20), alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)))
        pintar()

    def pintar():
        for nombre, (caja, valor) in cajas.items():
            activo = est["campo"] == nombre
            caja.border = ft.Border.all(3 if activo else 1, CYAN if activo else "#334155")
            valor.value = valores[nombre] + ("▌" if activo else "") or " "
        for f, fila in enumerate(teclas_ui):
            for c, caja in enumerate(fila):
                sel = (f, c) == (est["fila"], est["col"])
                es_guardar = TECLADO[f][c] == "Guardar y empezar"
                caja.bgcolor = CYAN if sel else (VIOLETA if es_guardar else "#1e293b")
                caja.border = ft.Border.all(3, "white") if sel else None
                caja.content.color = FONDO if sel else "white"
        page.update()

    def elegir_campo(nombre):
        est["campo"] = nombre
        pintar()

    def escribir(letra):
        campo = est["campo"]
        if campo == "Código":
            if letra.isdigit() and len(valores[campo]) < 8:
                valores[campo] += letra
        elif len(valores[campo]) < 40:
            valores[campo] += letra
        texto.value = ""
        pintar()

    def borrar():
        valores[est["campo"]] = valores[est["campo"]][:-1]
        pintar()

    def pulsar(f, c):
        est["fila"], est["col"] = f, c
        t = TECLADO[f][c]
        if t == "⌫":
            borrar()
        elif t in ("Código", "Llave"):
            elegir_campo(t)
        elif t == "Guardar y empezar":
            page.run_task(guardar)
        else:
            escribir(t)

    async def guardar():
        if est["ocupado"]:
            return
        cod, ll = valores["Código"].strip(), valores["Llave"].strip()
        if not (cod and ll):
            texto.value = "Escribe el código del lugar y la llave del bar."
            texto.color = "#fca5a5"
            est["campo"] = "Código" if not cod else "Llave"
            pintar()
            return
        est["ocupado"] = True
        texto.value = "Comprobando la llave…"
        texto.color = "#94A3B8"
        page.update()
        try:
            datos = await asyncio.to_thread(ApiCliente(url, ll).config)
        except Exception as ex:
            print(f"⚠️ Configurar: {type(ex).__name__}: {ex}")
            texto.value = ("No funcionó: " + str(ex) if isinstance(ex, LlaveInvalida)
                           else dns_respaldo.explicar_error(ex))
            texto.color = "#fca5a5"
            est["ocupado"] = False
            page.update()
            return
        if str(datos.get("codigo")) != cod:
            texto.value = (f"Esa llave es del lugar {datos.get('codigo')} "
                           f"({datos.get('nombre')}), no del {cod}.")
            texto.color = "#fca5a5"
            est["ocupado"] = False
            page.update()
            return
        CFG.guardar_config({**previo, "cliente": cod, "llave": ll, "api": url})
        hecho.set()

    def mover(df, dc):
        f = max(0, min(len(TECLADO) - 1, est["fila"] + df))
        if df:  # al cambiar de fila, quedar en la tecla más cercana
            c = round(est["col"] * (len(TECLADO[f]) - 1) / max(1, len(TECLADO[est["fila"]]) - 1))
        else:
            c = est["col"] + dc
        est["fila"], est["col"] = f, max(0, min(len(TECLADO[f]) - 1, c))
        pintar()

    async def teclas(e: ft.KeyboardEvent):
        k = (e.key or "").lower()
        if k in T_ARRIBA:
            mover(-1, 0)
        elif k in T_ABAJO:
            mover(1, 0)
        elif k in T_IZQ:
            mover(0, -1)
        elif k in T_DER:
            mover(0, 1)
        elif k in T_OK:
            pulsar(est["fila"], est["col"])
        elif k in T_BORRAR:
            borrar()
        elif k == "tab":
            elegir_campo("Llave" if est["campo"] == "Código" else "Código")
        elif len(k) == 1 and (k.isalnum() or k == "-"):
            escribir(k.upper())  # números del control remoto, teclado USB o del PC
        elif k.startswith("numpad ") and k[-1:].isdigit():
            escribir(k[-1])
        else:
            print(f"ℹ️ tecla sin uso en la configuración: {e.key!r}")

    page.on_keyboard_event = teclas

    def al_cambiar_tamano(e=None):
        try:
            armar()
        except Exception as ex:
            print(f"ℹ️ No se pudo reacomodar la configuración: {ex}")

    page.on_resize = al_cambiar_tamano
    armar()
    try:
        await hecho.wait()
    finally:
        page.on_keyboard_event = None
        page.on_resize = None


def _revisar(api, cliente):
    """Internet, servidor y llave. Devuelve [(mensaje, solución)]; vacía si todo bien."""
    import socket
    for host in (("8.8.8.8", 53), ("1.1.1.1", 53)):
        try:
            socket.create_connection(host, timeout=4).close()
            break
        except OSError:
            continue
    else:
        return [("No hay conexión a internet.", "Conecta el TV a internet (Wi-Fi o cable).")]
    try:
        api.salud()
    except Exception as ex:
        return [(f"No responde el servidor de PlayBar GO ({api.url}): {ex}",
                 "Revisa la dirección del servidor o espera un momento.")]
    try:
        datos = api.config()
    except LlaveInvalida:
        return [("La llave del bar no es válida (o el negocio está inactivo).",
                 "Pide la llave actual al super administrador.")]
    except Exception as ex:
        return [(f"No se pudo leer la configuración del bar: {ex}", "Intenta de nuevo.")]
    if str(datos.get("codigo")) != str(cliente):
        return [(f"La llave es del lugar {datos.get('codigo')}, no del {cliente}.",
                 "Usa 'Cambiar código o llave'.")]
    return []


async def _pantalla_problemas(page, problemas):
    """Muestra qué falló y espera a que toquen Reintentar o Cambiar código."""
    _limpiar(page)
    eleccion = asyncio.Queue()
    page.add(ft.Container(expand=True, alignment=ft.Alignment.CENTER, padding=30,
                          content=ft.Column([
                              ft.Text("No se pudo iniciar el reproductor", size=22,
                                      color="white", weight=ft.FontWeight.BOLD),
                              *[ft.Column([ft.Text("• " + m, color="#fca5a5"),
                                           ft.Text("  " + sol, color="#94A3B8")], spacing=2)
                                for m, sol in problemas],
                              ft.Row([
                                  ft.FilledButton("Reintentar", autofocus=True,
                                                  on_click=lambda e: eleccion.put_nowait("r")),
                                  ft.OutlinedButton("Cambiar código o llave",
                                                    on_click=lambda e: eleccion.put_nowait("c")),
                              ], alignment=ft.MainAxisAlignment.CENTER),
                              ft.Text(f"Versión TV {VERSION}", color="#64748b", size=11),
                          ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12)))
    page.update()
    if await eleccion.get() == "c":
        _olvidar_llave()


def _olvidar_llave():
    cfg = CFG.leer_config()
    cfg.pop("llave", None)
    try:
        CFG.guardar_config(cfg)
    except Exception:
        pass


# =============================================================================
# Menú (se abre con ▲ ▼ o la tecla Menú del control)
# =============================================================================
def _abrir_menu(page, pantalla, motor, reiniciar):
    if pantalla.menu_abierto:
        return
    pantalla.menu_abierto = True

    def cerrar(e=None):
        dlg.open = False
        pantalla.menu_abierto = False
        page.update()

    async def accion(cmd):
        cerrar()
        await motor.ejecutar(cmd)

    def cambiar(e):
        cerrar()
        _olvidar_llave()
        reiniciar.set()

    def ver_registro(e):
        cerrar()
        _ver_registro(page, pantalla)

    pausado = motor.pausado
    botones = [
        ft.FilledButton("▶ Reanudar" if pausado else "⏸ Pausar", autofocus=True, width=300,
                        on_click=lambda e: page.run_task(accion, "reanudar" if pausado else "pausar")),
        ft.OutlinedButton("⏭ Siguiente canción", width=300,
                          on_click=lambda e: page.run_task(accion, "siguiente")),
        ft.OutlinedButton("⏮ Canción anterior", width=300,
                          on_click=lambda e: page.run_task(accion, "anterior")),
        ft.OutlinedButton("🔑 Cambiar código o llave", width=300, on_click=cambiar),
        ft.OutlinedButton("📄 Ver registro (para soporte)", width=300, on_click=ver_registro),
        ft.TextButton("Cerrar menú", width=300, on_click=cerrar),
    ]
    cfg = CFG.leer_config()
    dlg = ft.AlertDialog(
        modal=False, bgcolor="#0f172a",
        title=ft.Text("PlayBar GO TV", color="white", weight=ft.FontWeight.BOLD),
        content=ft.Column([*botones,
                           ft.Text(f"Lugar {cfg.get('cliente', '')} · versión TV {VERSION}",
                                   size=11, color="#64748b")],
                          tight=True, spacing=8,
                          horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        on_dismiss=lambda e: setattr(pantalla, "menu_abierto", False),
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


def _ver_registro(page, pantalla):
    """Últimas líneas de registro.txt: sirve para saber qué pasa en el TV sin un PC."""
    try:
        lineas = (CFG.CARPETA / "registro.txt").read_text("utf-8", errors="ignore").splitlines()[-60:]
    except Exception as ex:
        lineas = [f"No se pudo leer el registro: {ex}"]
    pantalla.menu_abierto = True

    def cerrar(e=None):
        dlg.open = False
        pantalla.menu_abierto = False
        page.update()

    dlg = ft.AlertDialog(
        modal=False, bgcolor="#0f172a",
        title=ft.Text("Registro", color="white"),
        content=ft.Container(width=820, height=420, content=ft.Column(
            [ft.Text("\n".join(lineas), size=11, color="#cbd5e1", font_family="monospace")],
            scroll=ft.ScrollMode.ALWAYS)),
        actions=[ft.FilledButton("Cerrar", autofocus=True, on_click=cerrar)],
        on_dismiss=lambda e: setattr(pantalla, "menu_abierto", False),
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


# =============================================================================
# Arranque
# =============================================================================
async def _una_sesion(page: ft.Page):
    """Configura, revisa y hace sonar. Vuelve cuando hay que empezar de nuevo
    (cambiaron el código o la llave, o tocaron Reintentar)."""
    cfg = CFG.leer_config()
    if not (cfg.get("cliente") and cfg.get("llave")) and await actualizador_tv.revisar_ya():
        return "actualizar"  # código nuevo antes de configurar (p. ej. un arreglo de esta pantalla)
    while not (cfg.get("cliente") and cfg.get("llave") and cfg.get("api")):
        await _pantalla_config(page)
        cfg = CFG.leer_config()
    api = ApiCliente(cfg["api"], cfg["llave"])

    _limpiar(page)
    page.add(ft.Container(expand=True, alignment=ft.Alignment.CENTER,
                          content=ft.Image(src="/logo.png", width=280)))
    page.update()

    problemas = await asyncio.to_thread(_revisar, api, cfg["cliente"])
    if problemas:
        await _pantalla_problemas(page, problemas)
        return

    pantalla = Pantalla(page)
    # TV básicos (menos de 2 GB de RAM): videos en 480p, más livianos de reproducir.
    from tv import equipo
    calidad = descargas_tv.LIVIANA if equipo.es_basico() else 720
    descargas = descargas_tv.Descargador(CFG.CACHE, cookies=str(CFG.CARPETA / "cookies.txt"),
                                         altura_max=calidad)
    from tv.nube_cliente import Nube
    descargas.nube = Nube(api.nube)  # canciones en la nube (si la API la tiene activa)
    motor = Motor(BackendApi(api, cfg["cliente"]), descargas, pantalla)
    motor.info = equipo.info(page, calidad)
    print(f"📺 Equipo: {motor.info}")
    pantalla.motor = motor
    reiniciar = asyncio.Event()

    _limpiar(page)
    page.add(pantalla.construir())
    page.update()

    async def teclas(e: ft.KeyboardEvent):
        k = (e.key or "").lower()
        if pantalla.menu_abierto:
            return  # con el menú abierto las flechas y OK mueven el menú
        if motor.inactivo:  # suena en otro equipo: OK = "Usar aquí"
            if k in T_PAUSA:
                await motor.usar_aqui()
            return
        if k in T_PAUSA:
            await motor.ejecutar("reanudar" if motor.pausado else "pausar")
        elif k in T_SIGUIENTE:
            await motor.ejecutar("siguiente")
        elif k in T_ANTERIOR:
            await motor.ejecutar("anterior")
        elif k in T_MENU:
            _abrir_menu(page, pantalla, motor, reiniciar)
        else:
            print(f"ℹ️ tecla sin uso: {e.key!r}")

    page.on_keyboard_event = teclas
    print(f"🎬 Reproductor TV PlayBar GO para el lugar {cfg['cliente']}")

    resultado = {"valor": None}

    def aplicar_actualizacion():
        resultado["valor"] = "actualizar"
        reiniciar.set()

    async def confirmar():
        await asyncio.sleep(90)  # 90 s sonando sin caerse: este código queda como bueno
        await asyncio.to_thread(actualizador_tv.confirmar_que_funciona)

    tareas = [asyncio.ensure_future(motor.correr()),
              asyncio.ensure_future(pantalla.vigilar_final()),
              asyncio.ensure_future(confirmar()),
              asyncio.ensure_future(actualizador_tv.vigilar(
                  motor, pantalla.aviso_actualizacion, aplicar_actualizacion))]
    try:
        await reiniciar.wait()
        return resultado["valor"]
    finally:
        for t in tareas:
            t.cancel()
        page.on_keyboard_event = None
        try:
            await pantalla.video.stop()
        except Exception:
            try:
                await pantalla.video.pause()
            except Exception:
                pass


async def main(page: ft.Page):
    page.title = f"PlayBar GO TV v{VERSION}"
    page.bgcolor = FONDO
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.DARK
    while True:
        try:
            if await _una_sesion(page) == "actualizar":
                return "actualizar"  # arranque.py recarga el código nuevo
        except Exception as ex:
            import traceback
            traceback.print_exc()
            await _pantalla_problemas(page, [(f"Error inesperado: {ex}",
                                              "Toca Reintentar. Si se repite, envía el registro.")])


# =============================================================================
# Registro en archivo (en el TV no hay consola)
# =============================================================================
class _Registro:
    def __init__(self, ruta, original=None):
        self.f = open(ruta, "a", encoding="utf-8", buffering=1)
        self.original = original
        self._nueva = True

    def write(self, texto):
        if self.original is not None:
            try:
                self.original.write(texto)
            except Exception:
                pass
        try:
            for parte in texto.splitlines(True):
                if self._nueva:
                    self.f.write(time.strftime("%Y-%m-%d %H:%M:%S  "))
                self.f.write(parte)
                self._nueva = parte.endswith("\n")
        except Exception:
            pass
        return len(texto)

    def flush(self):
        try:
            self.f.flush()
        except Exception:
            pass


def preparar():
    """Antes de abrir la ventana: carpeta, registro y yt-dlp al día."""
    CFG.CARPETA.mkdir(parents=True, exist_ok=True)
    ruta = CFG.CARPETA / "registro.txt"
    try:
        if ruta.exists() and ruta.stat().st_size > 2 * 1024 * 1024:
            os.replace(ruta, CFG.CARPETA / "registro_anterior.txt")
        sys.stdout = _Registro(ruta, sys.stdout)
        sys.stderr = _Registro(ruta, sys.stderr)
    except Exception:
        pass
    print(f"===== PlayBar GO TV v{VERSION} · {sys.platform} · datos en {CFG.CARPETA} =====")
    dns_respaldo.activar()  # si el DNS del TV falla, se usa el de Cloudflare/Google
    descargas_tv.activar_ytdlp_actualizado(CFG.CARPETA)
    threading.Thread(target=descargas_tv.actualizar_ytdlp, args=(CFG.CARPETA,), daemon=True).start()
