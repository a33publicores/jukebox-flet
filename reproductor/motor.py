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
  * Si llega una canción nueva mientras suena RELLENO, se interrumpe y suena la nueva
    (cuando ya está descargada, sin cortar el relleno antes de tiempo).
  * Si suena una canción pedida, la nueva espera su turno.
  * Comandos del admin (hoja CONTROL): pausar, reanudar, siguiente, anterior.
"""
import asyncio
import os
import random
import time
from collections import deque

from services import cola as C

INTERVALO = 3.0        # segundos entre lecturas de la hoja
LATIDO = 15.0          # segundos entre latidos al panel admin
PRECARGA = 2           # canciones por delante que se descargan
RECIENTES = 15         # relleno: no repetir las últimas N
COMANDO_MAX_EDAD = 120  # ignorar comandos más viejos (p. ej. de antes de reiniciar)
# True: la canción pedida entra apenas se descarga (corta el aleatorio).
# False: espera a que termine la canción aleatoria que está sonando.
INTERRUMPIR_RELLENO = os.getenv("INTERRUMPIR_RELLENO", "1").strip() not in ("0", "false", "no")


class BackendHoja:
    """Acceso real a Google Sheets para un cliente."""

    def __init__(self, cliente):
        self.cliente = str(cliente)
        self.nombre_hoja = None
        self.ultimo = None
        self._limpio = False

    def instantanea(self):
        if self.nombre_hoja is None:
            self.nombre_hoja = C._nombre_hoja(self.cliente)
        snap = C.instantanea(self.cliente, self.nombre_hoja)
        self.ultimo = snap
        if not self._limpio:
            try:
                C.cerrar_atascadas(self.cliente, snap.atascadas, self.nombre_hoja)
                self._limpio = True
            except Exception as ex:
                print("⚠️ No se pudieron cerrar filas viejas:", ex)
        return snap

    def marcar(self, fila, estado2=None, estado=None):
        C.marcar(self.cliente, fila, estado2=estado2, estado=estado, nombre_hoja=self.nombre_hoja)

    def publicar(self, estado, actual, siguiente, ack=None):
        C.publicar_estado(self.cliente, estado, actual, siguiente, ack)

    def registrar(self, item):
        pass  # el historial ya está en la hoja (Estado2 = Reproducido)

    def elegir_relleno(self, excluir):
        """Canción al azar de fechas anteriores, evitando las que sonaron hace poco."""
        snap = self.ultimo or self.instantanea()
        excluir = set(excluir)
        pool = snap.aleatorio
        candidatas = [i for i in pool if i.video_id not in excluir] or pool
        if not candidatas:
            return None
        it = random.choice(candidatas)
        return C.Item(None, it.titulo, it.canal, it.video_id)


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
        self._ultimo_cid = None
        self._ack = None
        self._pub = None
        self._t_pub = 0.0
        self.error = ""

    # ------------------------------------------------------------------ bucle
    async def correr(self):
        while True:
            try:
                await self.tick()
                self.error = ""
            except Exception as ex:  # nunca morir por un fallo de red
                self.error = f"{type(ex).__name__}: {ex}"
                print(f"⚠️ Motor: {self.error}")
                await self._ui_estado()
            await asyncio.sleep(INTERVALO)

    async def tick(self):
        async with self._lock:
            await self._reintentar_marcas()
            snap = await asyncio.to_thread(self.backend.instantanea)
            self.snap = snap
            if await self._comandos(snap):
                # el comando cambió el estado: la lectura quedó vieja, se relee
                snap = await asyncio.to_thread(self.backend.instantanea)
                self.snap = snap
            await self._decidir(snap)
            self._precargar(snap)
            await self._publicar(snap)
            await self._ui_lista(snap)

    # ----------------------------------------------------------- decisiones
    def _filas_pendientes(self):
        return {f for f, _, _ in self._pend}

    async def _decidir(self, snap):
        marcada = snap.actual
        if marcada and marcada.fila in self._filas_pendientes():
            marcada = None
        cola = [i for i in snap.cola if i.fila not in self._filas_pendientes()]

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
        elif self.actual.fila is not None:
            if not marcada or marcada.fila != self.actual.fila:
                await self._terminar("externo")

    async def _tomar(self, item, ya_marcada=False):
        """Descarga `item` (el relleno sigue sonando) y lo pone a sonar."""
        self.ocupado = True
        try:
            await self._ui_estado(f"Preparando: {item.titulo}")
            try:
                ruta = await self._descargar(item.video_id)
            except Exception as ex:
                n = self._fallos.get(item.video_id, 0) + 1
                self._fallos[item.video_id] = n
                print(f"❌ No se pudo descargar {item.video_id} (intento {n}): {ex}")
                if n >= 2:  # un corte de red momentáneo no debe descartar la canción
                    await self._marcar(item.fila, e2=C.E_ERROR, estado=C.E_ERROR)
                return
            if not ya_marcada:
                # las "Pendiente" (versión vieja de la app) quedan como Agregado
                await self._marcar(item.fila, e2=C.E_PLAY,
                                   estado=None if item.estado == "Agregado" else "Agregado")
            if self.actual is not None and self.relleno:
                self.previo = self.actual
            await self._reproducir(item, ruta, relleno=False)
        finally:
            self.ocupado = False

    async def _poner_relleno(self):
        self.ocupado = True
        try:
            for _ in range(3):
                item = await asyncio.to_thread(
                    self.backend.elegir_relleno, list(self.recientes)
                )
                if item is None:
                    await self._ui_estado("Sin canciones en cola ni historial")
                    return
                try:
                    ruta = await self._descargar(item.video_id)
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

    async def _terminar(self, motivo):
        """Cierra la canción actual y pasa a la siguiente."""
        item = self.actual
        if item is not None and item.fila is not None and motivo != "externo":
            await self._marcar(item.fila, e2=C.E_HECHO)
        if item is not None and item.fila is not None and motivo in ("ok", "saltada"):
            try:
                await asyncio.to_thread(self.backend.registrar, item)
            except Exception as ex:
                print(f"⚠️ No se pudo registrar en REPRODUCIDAS: {ex}")
        self.previo = item
        self.actual = None
        self.relleno = False
        self.token += 1  # invalida eventos tardíos del video anterior
        try:
            snap = await asyncio.to_thread(self.backend.instantanea)
            self.snap = snap
            await self._decidir(snap)
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
        if cur is not None and cur.fila is not None:
            await self._marcar(cur.fila, e2=C.E_COLA)  # vuelve al inicio de la cola
        if prev.fila is not None:
            await self._marcar(prev.fila, e2=C.E_PLAY)
        self.previo = None
        self.ocupado = True
        try:
            ruta = await self._descargar(prev.video_id)
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

    async def _reintentar_marcas(self):
        pend, self._pend = self._pend, []
        for fila, e2, est in pend:
            try:
                await asyncio.to_thread(self.backend.marcar, fila, e2, est)
            except Exception:
                self._pend.append((fila, e2, est))

    # ------------------------------------------------------------ descargas
    async def _descargar(self, video_id):
        ruta = self.desc.ruta(video_id)
        if ruta:
            return ruta
        tarea = self._en_curso.get(video_id)
        if tarea is None:
            tarea = self._lanzar_descarga(video_id)
        return await tarea

    def _lanzar_descarga(self, video_id):
        async def _hacer():
            async with self._sem:
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
        for it in snap.cola[:PRECARGA]:
            if not self.desc.ruta(it.video_id) and it.video_id not in self._en_curso:
                self._lanzar_descarga(it.video_id)

    # ----------------------------------------------------------- publicación
    def _estado_txt(self):
        if self.actual is None:
            return "esperando"
        if self.pausado:
            return "pausado"
        return "relleno" if self.relleno else "reproduciendo"

    async def _publicar(self, snap):
        cola = snap.cola
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
        await self.ui.mostrar(
            actual=self.actual,
            cola=snap.cola,
            relleno=self.relleno,
            pausado=self.pausado,
            error=self.error,
        )

    async def _ui_estado(self, texto=""):
        if hasattr(self.ui, "estado"):
            await self.ui.estado(texto or self.error)
