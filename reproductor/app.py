"""
Pantalla del reproductor PlayBar GO (Flet de escritorio).

Se abre con:  python reproductor.py   (o INICIAR_REPRODUCTOR.bat en Windows)

Muestra el video, "En reproducción", "Sigue" y la playlist. El admin puede
controlarlo desde la app (pausar, avanzar, retroceder) y también desde aquí
con los botones o el teclado:  Espacio = pausa  ·  → = siguiente  ·  ← = anterior
· F = pantalla completa.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import flet as ft
import flet_video as ftv

from reproductor import actualizador, diagnostico
from reproductor.version import VERSION
from reproductor.descargas import Descargador
from reproductor.motor import BackendHoja, Motor

if getattr(sys, "frozen", False):  # instalado como .exe
    RAIZ = Path(sys.executable).resolve().parent          # aquí va credenciales.json
    ASSETS = Path(getattr(sys, "_MEIPASS", RAIZ)) / "assets"
else:
    RAIZ = Path(__file__).resolve().parent.parent
    ASSETS = RAIZ / "assets"
CARPETA = Path(os.environ.get("PLAYBAR_HOME", Path.home() / "PlayBarGo"))
CONFIG = CARPETA / "reproductor_config.json"


def _candidatos_credenciales():
    """Todos los credenciales.json disponibles, en orden: carpeta PlayBarGo del usuario,
    junto al .exe, carpeta actual y carpeta padre del proyecto (sin repetir)."""
    vistos, lista = set(), []
    for d in (CARPETA, RAIZ, Path.cwd(), RAIZ.parent):
        f = (Path(d) / "credenciales.json").resolve()
        if f.is_file() and f not in vistos:
            vistos.add(f)
            lista.append(f)
    return lista


def _usar_credencial(ruta):
    """Apunta playbar_service a ese archivo y olvida la conexión anterior."""
    from services import playbar_service as ps
    os.environ["PLAYBAR_CREDENCIALES"] = str(ruta)
    ps._spreadsheet = None
    ps._google = None


def _es_problema_credencial(problemas):
    return any("credenciales" in m or "hoja de Google" in m for m, _ in problemas)


def _revisar_con_credenciales(cliente):
    """Prueba cada credenciales.json hasta que uno funcione (p. ej. si hay una llave vieja)."""
    candidatos = [] if os.environ.get("GOOGLE_CREDENTIALS_B64") else _candidatos_credenciales()
    problemas = []
    for ruta in candidatos or [None]:
        if ruta:
            _usar_credencial(ruta)
        problemas = diagnostico.revisar(cliente)
        if not _es_problema_credencial(problemas):
            if ruta:
                print("🔑 Usando credenciales:", ruta)
            return problemas
        print("⚠️ No sirvió", ruta, "→", problemas[0][0] if problemas else "")
    if len(candidatos) > 1:
        problemas.append(("Ninguna de las credenciales encontradas funcionó:",
                          " · ".join(str(c) for c in candidatos)))
    return problemas


def _abrir_carpeta(e=None):
    try:
        CARPETA.mkdir(parents=True, exist_ok=True)
        os.startfile(str(CARPETA))  # solo Windows
    except Exception as ex:
        print("No se pudo abrir la carpeta:", ex)

FONDO = "#020617"
PANEL = "#0b1220"
CYAN = "#00D4FF"
VIOLETA = "#B44CFF"


def _leer_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _guardar_config(cfg):
    CARPETA.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _miniatura(video_id):
    return f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"


class Pantalla:
    """Interfaz que usa el Motor (reproducir, pausar, mostrar...)."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.motor = None
        self.token = 0
        self._firma = None

        self.video = ftv.Video(
            expand=True,
            playlist=[],
            autoplay=True,
            controls=None,
            fill_color="#000000",
            on_complete=self._on_complete,
            on_error=self._on_error,
        )
        self.chip = ft.Text("Iniciando…", size=20, weight=ft.FontWeight.BOLD, color="white",
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.lista = ft.ListView(expand=True, spacing=8, padding=12)
        self.btn_pausa = ft.IconButton(
            icon=ft.Icons.PAUSE_CIRCLE, icon_size=44, icon_color=CYAN,
            on_click=self._click_pausa,
        )

    # ------------------------------------------------------------ eventos
    async def _on_complete(self, e):
        if str(e.data).lower() in ("true", "1") and self.motor:
            await self.motor.al_terminar(self.token)

    async def _on_error(self, e):
        if self.motor:
            await self.motor.al_error(self.token, str(e.data))

    async def _click_pausa(self, e):
        if self.motor:
            await self.motor.ejecutar("reanudar" if self.motor.pausado else "pausar")

    # --------------------------------------------- interfaz que usa el Motor
    async def reproducir(self, ruta, item, token):
        self.token = token
        self.video.playlist = [ftv.VideoMedia(resource=ruta)]
        self.video.update()
        try:
            await self.video.play()
        except Exception:
            pass
        self.chip.value = item.titulo
        self.page.update()

    async def pausar(self):
        await self.video.pause()

    async def reanudar(self):
        await self.video.play()

    async def estado(self, texto):
        if texto:
            self.chip.value = texto
            self.page.update()

    async def mostrar(self, actual, cola, relleno, pausado, error):
        firma = (
            actual.video_id if actual else None, relleno, pausado, error,
            tuple((i.fila, i.video_id) for i in cola),
        )
        if firma == self._firma:
            return
        self._firma = firma

        self.btn_pausa.icon = ft.Icons.PLAY_CIRCLE if pausado else ft.Icons.PAUSE_CIRCLE
        self.chip.value = (
            ("⏸ " if pausado else "") + actual.titulo if actual
            else (error or "Esperando canciones…")
        )

        filas = []
        if error:
            filas.append(ft.Container(
                padding=10, border_radius=10, bgcolor="#7f1d1d",
                content=ft.Text(f"Sin conexión con la hoja — sigo con lo que hay\n{error[:90]}",
                                size=12, color="white"),
            ))
        if actual:
            filas.append(self._tarjeta(
                actual, "RELLENO · del historial" if relleno else "EN REPRODUCCIÓN",
                resaltada=True,
            ))
        if cola:
            filas.append(ft.Text(f"SIGUE ({len(cola)})", size=12, color="#94A3B8",
                                 weight=ft.FontWeight.BOLD))
            for it in cola[:20]:
                filas.append(self._tarjeta(it, "", quitar=True))
            if len(cola) > 20:
                filas.append(ft.Text(f"… y {len(cola) - 20} más", color="#94A3B8", size=12))
        elif actual:
            filas.append(ft.Text("No hay más canciones en cola", size=12, color="#94A3B8"))
        self.lista.controls = filas
        self.page.update()

    # ------------------------------------------------------------- piezas
    def _tarjeta(self, item, etiqueta, resaltada=False, quitar=False):
        info = [
            ft.Text(item.titulo, size=14, weight=ft.FontWeight.BOLD, color="white",
                    max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(item.canal, size=11, color="#94A3B8", max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS),
        ]
        if etiqueta:
            info.insert(0, ft.Text(etiqueta, size=11, weight=ft.FontWeight.BOLD,
                                   color=CYAN if "REPRO" in etiqueta else VIOLETA))
        fila = [
            ft.Image(src=_miniatura(item.video_id), width=96, height=54,
                     fit=ft.BoxFit.COVER, border_radius=8),
            ft.Column(info, spacing=2, expand=True),
        ]
        if quitar:
            async def _quitar(e, fila_hoja=item.fila):
                if self.motor:
                    await asyncio.to_thread(self.motor.backend.marcar, fila_hoja, "Eliminado")

            fila.append(ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color="#94A3B8",
                                      icon_size=20, on_click=_quitar, tooltip="Quitar de la cola"))
        return ft.Container(
            padding=8, border_radius=12,
            bgcolor="#12203a" if resaltada else PANEL,
            border=ft.Border.all(1, CYAN) if resaltada else None,
            content=ft.Row(fila, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

    def construir(self):
        async def _ant(e):
            await self.motor.ejecutar("anterior")

        async def _sig(e):
            await self.motor.ejecutar("siguiente")

        async def _full(e):
            self.page.window.full_screen = not self.page.window.full_screen
            self.page.update()

        controles = ft.Row(
            [
                ft.IconButton(icon=ft.Icons.SKIP_PREVIOUS, icon_size=36, icon_color="white",
                              on_click=_ant, tooltip="Anterior"),
                self.btn_pausa,
                ft.IconButton(icon=ft.Icons.SKIP_NEXT, icon_size=36, icon_color="white",
                              on_click=_sig, tooltip="Siguiente"),
                ft.IconButton(icon=ft.Icons.FULLSCREEN, icon_size=28, icon_color="#94A3B8",
                              on_click=_full, tooltip="Pantalla completa (F)"),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
        )
        izquierda = ft.Stack(
            expand=True,
            controls=[
                ft.Container(content=self.video, expand=True, bgcolor="#000000"),
                ft.Container(
                    left=0, right=0, top=0, padding=ft.Padding.symmetric(horizontal=16, vertical=10),
                    bgcolor="#000000B3",
                    content=ft.Row(
                        [ft.Image(src="/logo.png", height=40, fit=ft.BoxFit.CONTAIN),
                         ft.Container(content=self.chip, expand=True)],
                        spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ),
            ],
        )
        derecha = ft.Container(
            width=390, bgcolor=FONDO,
            border=ft.Border.only(left=ft.BorderSide(1, "#1e293b")),
            content=ft.Column(
                spacing=0,
                controls=[
                    ft.Container(
                        padding=16,
                        content=ft.Row([
                            ft.Image(src="/logo.png", height=48, fit=ft.BoxFit.CONTAIN),
                        ], alignment=ft.MainAxisAlignment.CENTER),
                    ),
                    self.lista,
                    ft.Container(padding=8, content=controles, bgcolor=PANEL),
                ],
            ),
        )
        return ft.Row([izquierda, derecha], expand=True, spacing=0)


async def _pantalla_config(page: ft.Page, mensaje=""):
    """Primera vez: pide el código del cliente (el mismo que usan los clientes en la app)."""
    page.controls.clear()
    campo = ft.TextField(label="Código del lugar (ej. 8523)", width=320, autofocus=True,
                         border_color=CYAN, color="white")
    texto = ft.Text(mensaje, color="#fca5a5")
    hecho = asyncio.Event()

    async def guardar(e):
        if campo.value.strip():
            _guardar_config({"cliente": campo.value.strip()})
            hecho.set()

    campo.on_submit = guardar
    page.add(ft.Column(
        [ft.Image(src="/logo.png", width=260), ft.Text("Configurar reproductor", size=24,
                                                      color="white", weight=ft.FontWeight.BOLD),
         campo, ft.FilledButton("Guardar y empezar", on_click=guardar), texto],
        horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER,
        expand=True,
    ))
    page.update()
    await hecho.wait()


async def main(page: ft.Page):
    page.title = f"PlayBar GO — Reproductor v{VERSION}"
    page.bgcolor = FONDO
    page.padding = 0
    page.spacing = 0
    page.theme_mode = ft.ThemeMode.DARK

    cfg = _leer_config()
    while not cfg.get("cliente"):
        await _pantalla_config(page)
        cfg = _leer_config()

    page.controls.clear()
    page.add(ft.Container(expand=True, alignment=ft.Alignment.CENTER,
                          content=ft.Image(src="/logo.png", width=300)))
    page.update()

    # Verificaciones previas (internet, ffmpeg, credenciales, código del lugar).
    problemas = await asyncio.to_thread(_revisar_con_credenciales, cfg["cliente"])
    if problemas:
        page.controls.clear()
        page.add(ft.Container(expand=True, alignment=ft.Alignment.CENTER, padding=30,
                              content=ft.Column([
                                  ft.Text("No se pudo iniciar el reproductor", size=24,
                                          color="white", weight=ft.FontWeight.BOLD),
                                  *[ft.Column([ft.Text("• " + m, color="#fca5a5", selectable=True),
                                               ft.Text("  " + sol, color="#94A3B8")], spacing=2)
                                    for m, sol in problemas],
                                  ft.Row([
                                      ft.OutlinedButton("Abrir carpeta", on_click=_abrir_carpeta),
                                      ft.OutlinedButton("Cambiar código del lugar",
                                                        on_click=lambda e: _cambiar_codigo(page)),
                                      ft.FilledButton("Reintentar", on_click=lambda e: _reiniciar(page)),
                                  ], alignment=ft.MainAxisAlignment.CENTER),
                                  ft.Text(f"Versión {VERSION}", color="#64748b", size=11),
                              ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=12)))
        page.update()
        return

    pantalla = Pantalla(page)
    descargas = Descargador(
        CARPETA / "cache",
        cookies=os.environ.get("YTDLP_COOKIES", str(CARPETA / "cookies.txt")),
        max_gb=float(cfg.get("cache_gb", 5)),
    )
    motor = Motor(BackendHoja(cfg["cliente"]), descargas, pantalla)
    pantalla.motor = motor

    page.controls.clear()
    page.add(pantalla.construir())
    page.update()

    async def teclas(e: ft.KeyboardEvent):
        k = e.key.lower()
        if k == " ":
            await motor.ejecutar("reanudar" if motor.pausado else "pausar")
        elif k == "arrow right":
            await motor.ejecutar("siguiente")
        elif k == "arrow left":
            await motor.ejecutar("anterior")
        elif k == "c" and e.ctrl and e.shift:  # Ctrl+Shift+C: cambiar código del lugar
            _cambiar_codigo(page)
        elif k == "f":
            page.window.full_screen = not page.window.full_screen
            page.update()

    page.on_keyboard_event = teclas

    async def revisar_actualizacion():
        info = await asyncio.to_thread(actualizador.hay_actualizacion)
        if info:
            _ventana_actualizacion(page, info)

    page.run_task(revisar_actualizacion)
    print(f"🎬 Reproductor PlayBar GO para el cliente {cfg['cliente']}")
    await motor.correr()


def _cambiar_codigo(page):
    """Borra el código guardado y reinicia: vuelve a pedir el código del lugar."""
    try:
        CONFIG.unlink()
    except Exception:
        pass
    _reiniciar(page)


def _reiniciar(page):
    """Vuelve a abrir el programa (sirve después de corregir el problema)."""
    try:
        os.execv(sys.executable, [sys.executable] + ([] if getattr(sys, "frozen", False) else sys.argv))
    except Exception:
        page.window.close()


def _ventana_actualizacion(page, info):
    obligatoria = bool(info.get("obligatoria"))

    def descargar(e):
        page.launch_url(info["url"])

    def luego(e):
        dlg.open = False
        page.update()

    acciones = [ft.FilledButton("Descargar", on_click=descargar)]
    if not obligatoria:
        acciones.insert(0, ft.TextButton("Más tarde", on_click=luego))
    dlg = ft.AlertDialog(
        modal=True, bgcolor="#111827",
        title=ft.Text("🔄 Hay una actualización", color="#22d3ee"),
        content=ft.Column([
            ft.Text(f"Nueva versión {info.get('version', '')} (tienes la {VERSION}).", color="white"),
            ft.Text(str(info.get("notas", "")), color="#94A3B8"),
            ft.Text("Descárgala, ciérrame e instala la nueva versión.", color="#94A3B8", size=12),
        ], tight=True, width=380),
        actions=acciones,
    )
    page.overlay.append(dlg)
    dlg.open = True
    page.update()


def ejecutar():
    os.chdir(RAIZ)  # para encontrar credenciales.json junto al programa
    CARPETA.mkdir(parents=True, exist_ok=True)
    ft.run(main, assets_dir=str(ASSETS))
