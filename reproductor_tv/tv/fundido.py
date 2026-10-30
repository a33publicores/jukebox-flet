"""
Mezcla entre canciones (reproductor de PC y de TV; este archivo es igual en los dos).

Con mezcla (dos videos): los últimos 8 s de la canción, la SIGUIENTE ya empieza a sonar en
un segundo video escondido detrás; la que termina baja de volumen mientras la otra sube,
así se oyen las dos a la vez, como un DJ. Cuando la primera termina, el video principal
pasa a la siguiente y salta justo a la parte donde iba el escondido (no se nota el cambio),
y el escondido se calla.

Sin mezcla (TV básicos, o si la siguiente no está lista): la que termina baja de volumen y
la siguiente entra suave.
"""
import asyncio
import os
from pathlib import Path

SALIDA_SEG = 8.0   # cuánto dura la mezcla (la que termina baja en estos últimos segundos)
ENTRADA_SEG = 5.0  # sin mezcla: la que empieza sube en 5 s
PASO_SEG = 0.25
RELEVO_ADELANTO_SEG = 0.7  # el principal salta este poco más adelante que el escondido...
RELEVO_ESPERA_SEG = 0.8    # ...y en este tiempo ya está sonando justo donde va el escondido
RELEVO_CRUCE_SEG = 0.2     # luego se cruzan (casi al instante: van en el mismo punto)
RELEVO_TOLERANCIA_SEG = 0.04  # diferencia máxima entre los dos antes de cruzarlos
RELEVO_AJUSTE = 0.25          # al afinar, el principal va 25% más rápido o más lento...
RELEVO_MAX_VELOCIDAD_SEG = 2.5  # ...si la diferencia es menor que esto (si no, otro salto)


def _cubica(v):
    """`v` es cuánto se oye (0-100, en línea recta). El reproductor (mpv) baja el sonido en
    curva: con volumen 50 ya casi no se oye. Por eso se le manda la raíz cúbica."""
    return round(100 * (max(0.0, min(100.0, v)) / 100) ** (1 / 3), 1)


async def _posicion_fresca(leer, espera=1.2):
    """(segundo, hora) de un video justo cuando su posición cambia: el reproductor la avisa a
    saltos, y leerla en cualquier momento puede dar la de hace un rato."""
    reloj = asyncio.get_event_loop()
    antes = float(await leer())
    limite = reloj.time() + espera
    while reloj.time() < limite:
        await asyncio.sleep(0.03)
        valor = float(await leer())
        if valor != antes:
            return valor, reloj.time()
    return antes, reloj.time()


def ganancia_con_nivel(ganancia, nivel):
    """El volumen parejo con el volumen que puso el admin (`nivel`, 0-200; 100 = normal).
    Hasta 100 baja todo. De 100 para arriba las canciones duras se bajan menos: el reproductor
    no puede pasar de su máximo, pero el volumen parejo deja ese margen, y así no se distorsiona."""
    nivel = max(0.0, min(200.0, float(nivel))) / 100
    return min(1.0, ganancia * max(1.0, nivel)) * min(1.0, nivel)


def _mismo(a, b):
    try:
        return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))
    except Exception:
        return False


class Fundido:
    def __init__(self, video, mezcla=None, siguiente=None, saltar=None, pos_mezcla=None,
                 volumen_de=None, pos_principal=None, informar=None):
        """`mezcla`: segundo video (escondido) para que suenen las dos a la vez. `siguiente()`:
        ruta del archivo de la canción que sigue (o None si no está lista). `saltar(seg)`:
        lleva el video principal a ese segundo. `pos_mezcla()`: en qué segundo va el escondido."""
        self.video = video
        self.mezcla = mezcla
        self.siguiente = siguiente
        self.saltar = saltar
        self.pos_mezcla = pos_mezcla
        self.pos_principal = pos_principal  # async: en qué segundo va el principal
        self.informar = informar  # informar(texto): aviso a los registros del servidor
        # Volumen parejo: `volumen_de(video_id)` (async) -> cuánto bajar esa canción (1 = igual)
        self.volumen_de = volumen_de
        self.ganancia = 1.0
        self.ganancia_mezcla = 1.0
        self.nivel = 100  # volumen del bar que pone el admin
        self.vol = 100
        self.vol_mezcla = 0
        self.saliendo = False
        self.mezclando = None  # ruta que suena en el video escondido
        self.mezcla_sonando = False  # el escondido está sonando (mezcla o relevo en curso)
        self._vuelta = 0  # cambia con cada canción: una mezcla que llega tarde ya no arranca
        self._tarea = None

    # ------------------------------------------------------------ volumen
    def _poner(self, v):
        v = int(max(0, min(100, round(v))))
        if v == self.vol:
            return
        self.vol = v
        self._aplicar()

    def _aplicar(self):
        try:
            self.video.volume = _cubica(self.vol * ganancia_con_nivel(self.ganancia, self.nivel))
            self.video.update()
        except Exception:
            pass  # el video todavía no está en pantalla

    def _poner_mezcla(self, v):
        v = int(max(0, min(100, round(v))))
        if v == self.vol_mezcla or self.mezcla is None:
            return
        self.vol_mezcla = v
        self._aplicar_mezcla()

    def _aplicar_mezcla(self):
        try:
            self.mezcla.volume = _cubica(self.vol_mezcla * ganancia_con_nivel(self.ganancia_mezcla, self.nivel))
            self.mezcla.update()
        except Exception:
            pass

    def _cancelar(self):
        if self._tarea is not None and not self._tarea.done():
            self._tarea.cancel()
        self._tarea = None

    def _rampa(self, hasta, segundos, hasta_mezcla=None):
        """Lleva el volumen del principal (y, si se pide, el del escondido) en `segundos`."""
        self._cancelar()
        desde, desde_m = self.vol, max(0, self.vol_mezcla)

        async def correr():
            n = max(1, int(segundos / PASO_SEG))
            for i in range(1, n + 1):
                self._poner(desde + (hasta - desde) * i / n)
                if hasta_mezcla is not None:
                    self._poner_mezcla(desde_m + (hasta_mezcla - desde_m) * i / n)
                await asyncio.sleep(PASO_SEG)

        try:
            self._tarea = asyncio.ensure_future(correr())
        except RuntimeError:  # sin bucle asyncio (no debería pasar): volumen directo
            self._poner(hasta)

    # ------------------------------------------------------------ mezcla
    def poner_ganancia(self, g):
        """Volumen parejo de la canción que suena (lo pide la app al empezar cada canción)."""
        g = max(0.2, min(1.0, float(g or 1.0)))
        if abs(g - self.ganancia) > 0.01:
            self.ganancia = g
            self._aplicar()

    def poner_nivel(self, nivel):
        """El admin movió el volumen del bar: se aplica de una, también si está mezclando."""
        if nivel != self.nivel:
            self.nivel = nivel
            self._aplicar()
            if self.mezcla is not None and self.vol_mezcla > 0:
                self._aplicar_mezcla()

    async def _empezar_mezcla(self, ruta, segundos):
        import flet_video as ftv
        vuelta = self._vuelta
        try:
            self.ganancia_mezcla = 1.0
            if self.volumen_de is not None:  # la siguiente también suena con su volumen parejo
                try:
                    self.ganancia_mezcla = max(0.2, min(1.0, float(await self.volumen_de(Path(ruta).stem))))
                except Exception:
                    pass
            if vuelta != self._vuelta:
                return  # mientras tanto la cambiaron: no se mezcla nada
            self.mezclando = str(ruta)
            self.vol_mezcla = -1
            self._poner_mezcla(0)
            self.mezcla.playlist = [ftv.VideoMedia(resource=str(ruta))]
            self.mezcla.update()
            await asyncio.sleep(0.3)
            if vuelta != self._vuelta:  # la cambiaron justo ahora: el escondido no arranca
                self.mezclando = None
                return
            self.mezcla_sonando = True
            await self.mezcla.play()
            print(f"🎚️ Mezcla: la siguiente ya suena por debajo ({segundos:.0f} s)")
            self._rampa(0, segundos, hasta_mezcla=100)
        except Exception as ex:
            print(f"⚠️ Mezcla: no se pudo arrancar la siguiente ({ex}); se hace solo fundido")
            self.mezclando = None
            self._rampa(0, segundos)

    async def _relevo(self):
        """Terminó la primera y el principal ya tiene la siguiente. El escondido SIGUE sonando
        mientras el principal (callado) salta a donde va el escondido y arranca; después se
        cruzan en medio segundo (uno sube, el otro baja). Así no se oye el salto como una pausa."""
        try:
            # (la rampa anterior ya la canceló nueva(); aquí NO se llama _cancelar(): esta
            # misma tarea es self._tarea y se cancelaría a sí misma)
            self.mezclando = None  # el relevo ya está en curso (no se repite)
            self.vol = -1
            self._poner(0)  # el principal empieza callado: lo que se oye es el escondido
            dif, intentos = None, 0
            seg = float(await self.pos_mezcla()) if self.pos_mezcla else 0.0
            if seg > 0.5 and self.saltar is not None:
                # Se apunta un poco adelante (lo que tarda en saltar y volver a sonar) y,
                # mientras el principal sigue callado, se mide y se corrige hasta que los
                # dos van en el mismo punto (si no, al cruzarlos se oiría como un salto).
                # Volver a saltar no sirve para afinar (en el TV cada salto cae donde puede):
                # la diferencia se cierra cambiando un rato la velocidad del principal, que
                # está callado, así que no se nota.
                await self.saltar(seg + RELEVO_ADELANTO_SEG)
                await asyncio.sleep(RELEVO_ESPERA_SEG)
                for k in range(5):
                    intentos += 1
                    if self.pos_principal is None:
                        break
                    dif = await self._diferencia()
                    if abs(dif) <= RELEVO_TOLERANCIA_SEG or k == 4:
                        break
                    if abs(dif) > RELEVO_MAX_VELOCIDAD_SEG:  # muy lejos: otro salto y se mide de nuevo
                        pz, tz = await _posicion_fresca(self.pos_mezcla)
                        await self.saltar(pz + (asyncio.get_event_loop().time() - tz) + RELEVO_ADELANTO_SEG)
                        await asyncio.sleep(RELEVO_ESPERA_SEG)
                        continue
                    # adelantado: más lento; atrasado: más rápido (se cierra RELEVO_AJUSTE s por segundo)
                    self._velocidad(1 - RELEVO_AJUSTE if dif > 0 else 1 + RELEVO_AJUSTE)
                    await asyncio.sleep(abs(dif) / RELEVO_AJUSTE)
                    self._velocidad(1.0)
                    await asyncio.sleep(0.3)
            else:
                await asyncio.sleep(RELEVO_ESPERA_SEG)
            self.ganancia = self.ganancia_mezcla
            n = max(1, int(RELEVO_CRUCE_SEG / 0.1))
            for i in range(1, n + 1):
                self._poner(100 * i / n)
                self._poner_mezcla(100 * (1 - i / n))
                await asyncio.sleep(0.1)
            print(f"🎚️ Mezcla: entra completa (desde el segundo {seg:.1f})")
            if self.informar is not None and seg > 0.5:
                try:  # para revisar en los registros cómo quedan los cambios en cada equipo
                    self.informar(f"mezcla: relevo con diferencia {dif if dif is None else round(dif, 3)} s "
                                  f"en {intentos} intento(s)")
                except Exception:
                    pass
        except Exception as ex:
            print(f"⚠️ Mezcla: relevo ({ex})")
            self._poner(100)
        finally:
            self._velocidad(1.0)  # (también si la cambiaron a mitad del relevo)
        await self.parar_mezcla()

    async def _diferencia(self):
        """Cuánto va adelantado el principal respecto al escondido (segundos; negativo: atrasado).
        El TV avisa la posición a saltos: se toma justo cuando cambia (así es la de ese
        instante) y se lleva a "ahora" con el reloj, para los dos videos."""
        pp, tp = await _posicion_fresca(self.pos_principal)
        pz, tz = await _posicion_fresca(self.pos_mezcla)
        ahora = asyncio.get_event_loop().time()
        return (pp + (ahora - tp)) - (pz + (ahora - tz))

    def _velocidad(self, v):
        try:
            if getattr(self.video, "playback_rate", 1.0) != v:
                self.video.playback_rate = v
                self.video.update()
        except Exception:
            pass

    async def parar_mezcla(self):
        self.mezclando = None
        self.mezcla_sonando = False
        if self.mezcla is None:
            return
        try:
            self._poner_mezcla(0)
            await self.mezcla.pause()
        except Exception:
            pass

    def _parar_mezcla_luego(self):
        if self.mezclando or self.mezcla_sonando:
            try:
                asyncio.ensure_future(self.parar_mezcla())
            except RuntimeError:
                pass

    # ------------------------------------------------------------ eventos del reproductor
    def nueva(self, ruta=None):
        """Empezó otra canción en el principal (`ruta`: su archivo)."""
        self.saliendo = False
        self._vuelta += 1
        if self.mezclando and ruta and _mismo(ruta, self.mezclando):
            try:
                self._cancelar()
                self._tarea = asyncio.ensure_future(self._relevo())
                return
            except RuntimeError:
                pass
        # Otra canción (la pasaron a mano, o la siguiente no era la que se mezclaba): se corta
        # todo lo de antes, incluido un relevo a medias, para que no siga sonando por debajo.
        self._cancelar()
        self._parar_mezcla_luego()
        self._poner(5)
        self._rampa(100, ENTRADA_SEG)

    def posicion(self, pos, dur, pausado=False):
        """Cada segundo: al acercarse el final, arranca la mezcla (o el fundido)."""
        if pausado or dur < 40:
            return
        quedan = dur - pos
        if self.saliendo and quedan > SALIDA_SEG + 2:
            self.normal()  # la adelantaron hacia atrás (televisor espejo): vuelve el volumen
        elif not self.saliendo and quedan <= SALIDA_SEG and pos > 10:
            self.saliendo = True
            segundos = max(1.0, quedan - 0.3)
            ruta = self.siguiente() if (self.mezcla is not None and self.siguiente) else None
            if ruta:
                try:
                    asyncio.ensure_future(self._empezar_mezcla(ruta, segundos))
                    return
                except RuntimeError:
                    pass
            print(f"🎚️ Mezcla: baja el volumen (quedan {quedan:.1f} s de {dur:.0f} s)")
            self._rampa(0, segundos)
        elif (not self.saliendo and self.vol < 100 and pos > ENTRADA_SEG + 2
              and (self._tarea is None or self._tarea.done())):
            self._poner(100)  # seguro: el volumen nunca se queda bajo a mitad de canción

    def normal(self):
        """Pausa/reanudar o la adelantaron: volumen normal de una y sin mezcla."""
        self.saliendo = False
        self._vuelta += 1
        self._cancelar()
        self._parar_mezcla_luego()
        self._poner(100)
