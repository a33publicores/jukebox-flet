"""
Motor del reproductor: decide qué suena, qué sigue y ejecuta los comandos del admin.

No depende de la pantalla ni de Google: recibe un `backend` (la hoja), un
`descargas` (yt-dlp) y una `pantalla` (la UI). Todo corre en UN solo bucle
asyncio, así que no hay condiciones de carrera; lo bloqueante (Sheets, yt-dlp)
se manda a hilos con asyncio.to_thread.

Reglas:
  * Solo cuentan las filas de HOY. Suena la de Estado2 = "En reproduccion"; si no hay,
    la primera "Siguiente"/"En cola".
  * Si no hay cola, suena al azar una canción de fechas anteriores (relleno).
  * El reproductor habla con la API de Railway (BackendApi), nunca con la base directo.
  * Si llega una canción nueva mientras suena RELLENO, NO se corta: queda de siguiente
    (ya descargada) y suena apenas termine la aleatoria.
  * Si suena una canción pedida, la nueva espera su turno.
  * Comandos del admin (hoja CONTROL): pausar, reanudar, siguiente, anterior.
"""
import asyncio
import json
import os
import random
import time
from pathlib import Path
from collections import deque

from services import cola as C

CARPETA_DATOS = Path(os.environ.get("PLAYBAR_HOME", Path.home() / "PlayBarGo"))
INTERVALO = 4.0        # segundos entre lecturas de la hoja (cuota: 60 lecturas/min)
LATIDO = 15.0          # segundos entre latidos al panel admin
PRECARGA = 3           # canciones pedidas por delante que se descargan
RECIENTES = 15         # relleno: no repetir las últimas N
COMANDO_MAX_EDAD = 120  # ignorar comandos más viejos (p. ej. de antes de reiniciar)
# False (por defecto): la canción pedida queda de SIGUIENTE y espera a que termine la
#   canción aleatoria que está sonando (no se corta). Mientras tanto ya se descarga.
# True: la canción pedida entra apenas se descarga (corta el aleatorio).
INTERRUMPIR_RELLENO = os.getenv("INTERRUMPIR_RELLENO", "0").strip().lower() in ("1", "true", "si", "sí")


class BackendApi:
    """Acceso del reproductor a la API de PlayBar GO (con la llave de su negocio)."""

    def __init__(self, api, cliente=""):
        self.api = api                 # services.api_cliente.ApiCliente
        self.cliente = str(cliente)
        self.ultimo = None
        self._config = None
        self._pool = []                # aleatorio: lo pedido en fechas anteriores
        self._t_pool = 0.0
        self._playlist = None          # canciones de la playlist del negocio
        self._t_playlist = 0.0

    def instantanea(self):
        snap = self.api.instantanea()
        self.ultimo = snap
        return snap

    def reordenar(self, filas):
        self.api.reordenar(filas)

    def marcar(self, fila, estado2=None, estado=None):
        self.api.marcar(fila, estado2=estado2, estado=estado)

    def publicar(self, estado, actual, siguiente, ack=None):
        self.api.estado(estado, actual, siguiente, ack)

    def registrar(self, item):
        pass  # el historial ya queda en la base (estado2 = Reproducido)

    def config(self):
        if self._config is None:
            self._config = self.api.config()
        return self._config

    def aleatorio(self):
        """Lo pedido en fechas anteriores (se pide a la API cada 15 min, no a cada rato)."""
        if not self._pool or time.time() - self._t_pool > 900:
            try:
                self._pool, self._t_pool = self.api.aleatorio(), time.time()
                print(f"🎲 Aleatorio: {len(self._pool)} canciones del historial")
            except Exception as ex:
                print("⚠️ No se pudo traer el aleatorio (sigo con el anterior):", ex)
        return self._pool

    def canciones_playlist(self):
        """Playlist de YouTube del negocio (la define el super admin), leída con
        yt-dlp (sin cuota de API). Se guarda en disco y se refresca cada 12 h."""
        if self._playlist is not None and time.time() - self._t_playlist < 12 * 3600:
            return self._playlist
        cache = CARPETA_DATOS / f"playlist_{self.cliente or 'bar'}.json"
        try:
            pl = str(self.config().get("playlist", "")).strip()
            if not pl:
                self._playlist, self._t_playlist = [], time.time()
                return []
            url = pl if pl.startswith("http") else f"https://www.youtube.com/playlist?list={pl}"
            import yt_dlp
            with yt_dlp.YoutubeDL({"extract_flat": "in_playlist", "quiet": True,
                                   "skip_download": True, "ignoreerrors": True}) as ydl:
                info = ydl.extract_info(url, download=False) or {}
            lista = [
                {"id": e["id"], "t": e.get("title") or "", "c": e.get("channel") or e.get("uploader") or ""}
                for e in (info.get("entries") or []) if e and e.get("id")
                and (e.get("title") or "") not in ("[Private video]", "[Deleted video]")
            ]
            if lista:
                CARPETA_DATOS.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(lista, ensure_ascii=False), encoding="utf-8")
            print(f"📃 Playlist del negocio: {len(lista)} canciones")
        except Exception as ex:
            print("⚠️ No se pudo leer la playlist del negocio:", ex)
            try:
                lista = json.loads(cache.read_text(encoding="utf-8"))
            except Exception:
                lista = []
        self._playlist, self._t_playlist = lista, time.time()
        return lista

    def elegir_relleno(self, excluir):
        """Canción al azar: playlist del negocio + lo pedido en fechas anteriores,
        evitando las que sonaron hace poco."""
        excluir = set(excluir)
        pool = list(self.aleatorio())
        ya = {i.video_id for i in pool}
        pool += [C.Item(None, p["t"], p["c"], p["id"]) for p in self.canciones_playlist()
                 if p["id"] not in ya]
        candidatas = [i for i in pool if i.video_id not in excluir] or pool
        if not candidatas:
            return None
        it = random.choice(candidatas)
        return C.Item(None, it.titulo, it.canal, it.video_id)


AVISAR_SIN_RED_SEG = 45


def _explicar(ex):
    texto = f"{type(ex).__name__}: {ex}"
    if "Timeout" in texto or "timed out" in texto:
        return "El servidor no responde (internet lento o caído)."
    if "Connection" in texto or "Max retries" in texto or "NameResolution" in texto:
        return "Sin internet o sin conexión con el servidor."
    return texto[:120]


class Motor:
    def __init__(self, backend, descargas, pantalla, ahora=time.time):
        self.backend = backend
        self.desc = descargas
        self.ui = pantalla
        self.ahora = ahora

        self.actual = None       # Item que suena
        self.relleno = False
        self.pausado = False
        self.previo = None       # para "anterior"
        self.token = 0           # identifica la reproducción vigente
        self.ocupado = False     # preparando una canción
        self.recientes = deque(maxlen=RECIENTES)
        self.snap = None

        self._en_curso = {}      # video_id -> Task de descarga
        self._sem = asyncio.Semaphore(2)
        self._lock = asyncio.Lock()  # una sola operación de estado a la vez
        self._fallos = {}        # video_id -> descargas fallidas
        self._pend = []          # marcas que no se pudieron escribir [(fila, estado2, estado)]
        self._hechas = set()     # filas que ya sonaron en esta sesión (aunque la hoja no lo sepa)
        self._relleno_sig = None  # próxima canción aleatoria, elegida y descargada por adelantado
        self._marcas = set()      # escrituras a la API en segundo plano
        self._preparando_relleno = False
        self._ultimo_cid = None
        self._ack = None
        self._pub = None
        self._t_pub = 0.0
        self.error = ""

    # ------------------------------------------------------------------ bucle
    async def correr(self):
        desde = None  # cuándo empezó a fallar la conexión
        while True:
            try:
                await self.tick()
                if desde is not None:
                    print(f"✅ Conexión recuperada ({int(self.ahora() - desde)} s sin servidor)")
                desde = None
                if self.error:
                    self.error = ""
                    if self.snap is not None:
                        await self._ui_lista(self.snap)
            except Exception as ex:  # nunca morir por un fallo de red
                print(f"⚠️ Motor: {type(ex).__name__}: {ex}")
                desde = desde if desde is not None else self.ahora()
                # Un corte de segundos (internet, el servidor reiniciándose) no se muestra:
                # la música sigue igual. Solo se avisa si dura más de AVISAR_SIN_RED_SEG.
                if self.ahora() - desde >= AVISAR_SIN_RED_SEG and not self.error:
                    self.error = _explicar(ex)
                    await self._ui_estado()
                    if self.snap is not None:
                        await self._ui_lista(self.snap)
            await asyncio.sleep(INTERVALO)

    async def tick(self):
        # Lo que va por internet se hace SIN el candado: si el servidor tarda, el cambio
        # de canción (al_terminar) no queda esperando y la música nunca se detiene.
        await self._reintentar_marcas()
        try:
            snap = await asyncio.to_thread(self.backend.instantanea)
        except Exception:
            # Sin servidor (internet...): si no suena nada, seguir con la última
            # lectura para no quedarse en silencio. Los cambios se escriben después.
            async with self._lock:
                if self.actual is None and not self.ocupado and self.snap is not None:
                    await self._decidir(self.snap)
            if self.snap is not None:
                await self._ui_lista(self.snap)
            raise
        async with self._lock:
            self.snap = snap
            if await self._comandos(snap):
                # el comando cambió el estado: la lectura quedó vieja, se relee
                try:
                    snap = await asyncio.to_thread(self.backend.instantanea)
                    self.snap = snap
                except Exception:
                    pass
            await self._decidir(snap)
            self._precargar(snap)
            await self._anticipar(snap)
        await self._publicar(snap)
        await self._ui_lista(snap)

    # ----------------------------------------------------------- decisiones
    def _filas_pendientes(self):
        return {f for f, _, _ in self._pend}

    async def _decidir(self, snap):
        omitir = self._filas_pendientes() | self._hechas
        marcada = snap.actual
        if marcada and marcada.fila in omitir:
            marcada = None
        cola = [i for i in snap.cola if i.fila not in omitir
                and not (self.actual is not None and i.fila == self.actual.fila)]

        if self.actual is None:
            if marcada:
                await self._tomar(marcada, ya_marcada=True)
            elif cola:
                await self._tomar(cola[0])
            else:
                await self._poner_relleno()
        elif self.relleno:
            if cola and INTERRUMPIR_RELLENO:
                await self._tomar(cola[0])
        elif self.actual.fila is not None and self.actual.fila not in self._filas_pendientes():
            # Solo se corta si en la hoja ESA fila fue quitada a propósito (admin la
            # eliminó). Que otra fila diga "En reproduccion" es un dato viejo: se corrige.
            fila_hoja = next((i for i in snap.items if i.fila == self.actual.fila), None)
            if fila_hoja is not None and fila_hoja.estado2 in (C.E_ELIM, C.E_ERROR):
                await self._terminar("externo")
            elif marcada and marcada.fila != self.actual.fila:
                await self._corregir_marcada(marcada)

    async def _corregir_marcada(self, marcada):
        """Otra fila quedó como "En reproduccion" en la hoja (escritura atrasada)."""
        if marcada.fila in self._filas_pendientes():
            return
        estado = C.E_HECHO if marcada.fila in self._hechas else C.E_SIGUE
        print(f"🩹 Corrigiendo fila {marcada.fila}: {estado}")
        await self._marcar(marcada.fila, e2=estado)
        if self.actual and self.actual.fila is not None:
            await self._marcar(self.actual.fila, e2=C.E_PLAY)

    async def _tomar(self, item, ya_marcada=False):
        """Descarga `item` (el relleno sigue sonando) y lo pone a sonar."""
        self.ocupado = True
        try:
            await self._ui_estado(f"Preparando: {item.titulo}")
            try:
                ruta = await self._descargar(item.video_id, item)
            except Exception as ex:
                n = self._fallos.get(item.video_id, 0) + 1
                self._fallos[item.video_id] = n
                print(f"❌ No se pudo descargar {item.video_id} (intento {n}): {ex}")
                if n >= 2:  # un corte de red momentáneo no debe descartar la canción
                    await self._marcar(item.fila, e2=C.E_ERROR, estado=C.E_ERROR)
                return
            if self.actual is not None and self.relleno:
                self.previo = self.actual
            await self._reproducir(item, ruta, relleno=False)  # primero suena…
            if not ya_marcada:  # …y la marca viaja a la API en segundo plano
                self._marcar_luego(item.fila, e2=C.E_PLAY,
                                   estado=None if item.estado == "Agregado" else "Agregado")
        finally:
            self.ocupado = False

    async def _elegir_relleno(self):
        return await asyncio.to_thread(self.backend.elegir_relleno, list(self.recientes))

    async def _preparar_relleno(self):
        """Mientras suena una canción, deja elegida y descargada la próxima aleatoria."""
        try:
            if self._relleno_sig is None or self._relleno_sig.video_id in self.recientes:
                self._relleno_sig = await self._elegir_relleno()
            if self._relleno_sig is not None:
                await self._descargar(self._relleno_sig.video_id, self._relleno_sig)
        except Exception as ex:
            print(f"⚠️ No se pudo preparar el próximo aleatorio: {ex}")
            self._relleno_sig = None

    async def _poner_relleno(self):
        self.ocupado = True
        try:
            # 1) la que ya quedó lista mientras sonaba la anterior: entra al instante
            sig, self._relleno_sig = self._relleno_sig, None
            if sig is not None and self.desc.ruta(sig.video_id):
                await self._reproducir(sig, self.desc.ruta(sig.video_id), relleno=True)
                return
            for _ in range(3):
                item = await self._elegir_relleno()
                if item is None:
                    await self._ui_estado("Sin canciones en cola ni historial")
                    return
                try:
                    ruta = await self._descargar(item.video_id, item)
                except Exception as ex:
                    print(f"❌ Relleno {item.video_id}: {ex}")
                    self.recientes.append(item.video_id)
                    continue
                await self._reproducir(item, ruta, relleno=True)
                return
        finally:
            self.ocupado = False

    async def _reproducir(self, item, ruta, relleno):
        self.actual = item
        self.relleno = relleno
        self.pausado = False
        self.token += 1
        self.recientes.append(item.video_id)
        await self.ui.reproducir(ruta, item, self.token)
        print(f"▶️ {'(relleno) ' if relleno else ''}{item.titulo}")
        await self._anticipar()

    async def _terminar(self, motivo):
        """Cierra la canción actual y pasa a la siguiente."""
        item = self.actual
        if item is not None and item.fila is not None and motivo != "externo":
            self._hechas.add(item.fila)
            self._marcar_luego(item.fila, e2=C.E_HECHO)  # no se espera a la API
        self.previo = item
        self.actual = None
        self.relleno = False
        self.token += 1  # invalida eventos tardíos del video anterior
        # La siguiente se decide con la última lectura (tiene máx. 4 s): sin esperar a la red.
        try:
            if self.snap is not None:
                await self._decidir(self.snap)
            else:
                self.snap = await asyncio.to_thread(self.backend.instantanea)
                await self._decidir(self.snap)
        except Exception as ex:
            print(f"⚠️ Siguiente canción se decidirá en el próximo ciclo: {ex}")

    async def al_terminar(self, token):
        """La UI avisa que el video llegó al final."""
        async with self._lock:
            if token == self.token and self.actual is not None:
                await self._terminar("ok")

    async def al_error(self, token, mensaje):
        """El reproductor no pudo abrir el archivo."""
        async with self._lock:
            if token != self.token or self.actual is None:
                return
            print(f"❌ Error de reproducción: {mensaje}")
            it = self.actual
            if it.fila is not None:
                await self._marcar(it.fila, e2=C.E_ERROR, estado=C.E_ERROR)
            self.previo = None
            self.actual = None
            self.relleno = False
            self.token += 1

    # ------------------------------------------------------------- comandos
    async def _comandos(self, snap):
        """Ejecuta el comando pendiente del admin. True si cambió el estado."""
        c = snap.control
        cid = c.get("comando_id", "")
        if not cid or cid == c.get("ack") or cid == self._ultimo_cid:
            return False
        self._ultimo_cid = cid
        try:
            edad = self.ahora() - int(cid.split("-")[0])
        except ValueError:
            edad = 0
        cmd = c.get("comando", "")
        cambio = False
        if edad <= COMANDO_MAX_EDAD:
            print(f"🎛️ Comando admin: {cmd}")
            cambio = await self._ejecutar(cmd)
        self._ack = cid
        return cambio

    async def reordenar(self, filas):
        """Nuevo orden de la cola elegido en la pantalla (arrastrando)."""
        async with self._lock:
            try:
                await asyncio.to_thread(self.backend.reordenar, filas)
                self.snap = await asyncio.to_thread(self.backend.instantanea)
                await self._ui_lista(self.snap)
            except Exception as ex:
                print("⚠️ No se pudo guardar el nuevo orden:", ex)

    async def ejecutar(self, cmd):
        """Botones locales de la pantalla (toman el candado si cambian la cola)."""
        if cmd in ("pausar", "reanudar"):
            await self._ejecutar(cmd)
        else:
            async with self._lock:
                await self._ejecutar(cmd)
        if self.snap is not None:
            await self._ui_lista(self.snap)

    async def _ejecutar(self, cmd):
        """Lógica de cada comando. Devuelve True si cambió qué suena."""
        if cmd == "pausar" and self.actual:
            await self.ui.pausar()
            self.pausado = True
        elif cmd == "reanudar" and self.actual:
            await self.ui.reanudar()
            self.pausado = False
        elif cmd == "siguiente":
            if self.actual is not None:
                await self._terminar("saltada")
            elif self.snap is not None:
                await self._decidir(self.snap)
            return True
        elif cmd == "anterior":
            await self._anterior()
            return True
        return False

    async def _anterior(self):
        prev, cur = self.previo, self.actual
        if prev is None:
            return
        if prev.fila is not None:
            self._hechas.discard(prev.fila)
        if cur is not None and cur.fila is not None:
            await self._marcar(cur.fila, e2=C.E_COLA)  # vuelve al inicio de la cola
        if prev.fila is not None:
            await self._marcar(prev.fila, e2=C.E_PLAY)
        self.previo = None
        self.ocupado = True
        try:
            ruta = await self._descargar(prev.video_id, prev)
            await self._reproducir(prev, ruta, relleno=prev.fila is None)
        except Exception as ex:
            print(f"❌ No se pudo volver a la anterior: {ex}")
        finally:
            self.ocupado = False

    # ------------------------------------------------------- hoja / marcas
    async def _marcar(self, fila, e2=None, estado=None):
        if fila is None:
            return
        try:
            await asyncio.to_thread(self.backend.marcar, fila, e2, estado)
        except Exception as ex:
            print(f"⚠️ No se pudo escribir en la hoja (se reintenta): {ex}")
            self._pend.append((fila, e2, estado))

    def _marcar_luego(self, fila, e2=None, estado=None):
        """Escribe en la API sin frenar la música (si falla, se reintenta en el próximo ciclo)."""
        if fila is None:
            return
        self._pend.append((fila, e2, estado))  # cuenta como pendiente mientras viaja

        async def _ir():
            try:
                await asyncio.to_thread(self.backend.marcar, fila, e2, estado)
                try:
                    self._pend.remove((fila, e2, estado))
                except ValueError:
                    pass
            except Exception as ex:
                print(f"⚠️ No se pudo escribir (se reintenta): {ex}")

        t = asyncio.ensure_future(_ir())
        self._marcas.add(t)
        t.add_done_callback(self._marcas.discard)

    async def _reintentar_marcas(self):
        # las pendientes siguen anotadas mientras se reintenta (así _decidir las respeta)
        for marca in list(self._pend):
            try:
                await asyncio.to_thread(self.backend.marcar, *marca)
            except Exception:
                break  # sigue sin servidor: se reintenta en el próximo ciclo
            try:
                self._pend.remove(marca)
            except ValueError:
                pass

    # ------------------------------------------------------------ descargas
    async def _descargar(self, video_id, item=None):
        ruta = self.desc.ruta(video_id)
        if ruta:
            return ruta
        tarea = self._en_curso.get(video_id)
        if tarea is None:
            tarea = self._lanzar_descarga(video_id, item)
        return await tarea

    def _lanzar_descarga(self, video_id, item=None):
        titulo = getattr(item, "titulo", None)
        canal = getattr(item, "canal", None)

        async def _hacer():
            async with self._sem:
                if titulo:  # con el nombre puede buscar otro video si este no sirve
                    return await asyncio.to_thread(self.desc.obtener, video_id, titulo, canal)
                return await asyncio.to_thread(self.desc.obtener, video_id)

        tarea = asyncio.ensure_future(_hacer())
        self._en_curso[video_id] = tarea

        def _fin(t):
            self._en_curso.pop(video_id, None)
            if not t.cancelled():
                t.exception()  # evita "exception was never retrieved"

        tarea.add_done_callback(_fin)
        return tarea

    def _precargar(self, snap):
        omitir = self._hechas | ({self.actual.fila} if self.actual and self.actual.fila else set())
        pendientes = [i for i in snap.cola if i.fila not in omitir][:PRECARGA]
        for it in pendientes:
            if not self.desc.ruta(it.video_id) and it.video_id not in self._en_curso:
                self._lanzar_descarga(it.video_id, it)
        # si no hay pedidos esperando, deja lista la próxima aleatoria
        if not pendientes and self.actual is not None and not self._preparando_relleno:
            self._preparando_relleno = True

            async def _prep():
                try:
                    await self._preparar_relleno()
                finally:
                    self._preparando_relleno = False

            t = asyncio.ensure_future(_prep())
            self._marcas.add(t)
            t.add_done_callback(self._marcas.discard)

    def _proxima(self, snap):
        """La canción que sonará cuando termine la actual (misma regla que _decidir)."""
        if snap is None:
            return None
        omitir = self._filas_pendientes() | self._hechas
        if self.actual is not None and self.actual.fila is not None:
            omitir = omitir | {self.actual.fila}
        marcada = snap.actual
        if marcada is not None and marcada.fila not in omitir:
            return marcada
        cola = [i for i in snap.cola if i.fila not in omitir]
        if cola:
            return cola[0]
        return self._relleno_sig

    async def _anticipar(self, snap=None):
        """Deja la próxima canción (si ya está descargada) lista en el reproductor, para
        que entre sola al terminar la actual: sin pausa y aunque la ventana esté minimizada."""
        if not hasattr(self.ui, "preparar_siguiente") or self.actual is None:
            return
        it = self._proxima(snap if snap is not None else self.snap)
        ruta = self.desc.ruta(it.video_id) if it is not None else None
        try:
            await self.ui.preparar_siguiente(ruta)
        except Exception as ex:
            print(f"⚠️ No se pudo dejar lista la siguiente: {ex}")

    # ----------------------------------------------------------- publicación
    def _estado_txt(self):
        if self.actual is None:
            return "esperando"
        if self.pausado:
            return "pausado"
        return "relleno" if self.relleno else "reproduciendo"

    async def _publicar(self, snap):
        omitir = self._hechas | ({self.actual.fila} if self.actual and self.actual.fila else set())
        cola = [i for i in snap.cola if i.fila not in omitir]
        actual = self.actual.titulo if self.actual else ""
        sig = cola[0].titulo if cola else ""
        clave = (self._estado_txt(), actual, sig, self._ack)
        ahora = self.ahora()
        if clave == self._pub and ahora - self._t_pub < LATIDO:
            return
        await asyncio.to_thread(
            self.backend.publicar, clave[0], actual, sig, self._ack
        )
        self._pub, self._t_pub = clave, ahora

    async def _ui_lista(self, snap):
        omitir = self._hechas | ({self.actual.fila} if self.actual and self.actual.fila else set())
        await self.ui.mostrar(
            actual=self.actual,
            cola=[i for i in snap.cola if i.fila not in omitir],
            relleno=self.relleno,
            pausado=self.pausado,
            error=self.error,
        )

    async def _ui_estado(self, texto=""):
        if hasattr(self.ui, "estado"):
            await self.ui.estado(texto or self.error)
