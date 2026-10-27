"""
Mezcla suave entre canciones (reproductor de PC y de TV; este archivo es igual en los dos).

El reproductor tiene un solo video, así que la mezcla es un fundido: los últimos segundos
de la canción bajan de volumen hasta silencio y la siguiente entra suave hasta el volumen
normal. Si la canción es corta (menos de 40 s) o está en pausa, no se toca el volumen.
"""
import asyncio

SALIDA_SEG = 5.0   # la que termina baja de volumen sus últimos 5 s
ENTRADA_SEG = 3.0  # la que empieza sube en 3 s
PASO_SEG = 0.25


class Fundido:
    def __init__(self, video):
        self.video = video
        self.vol = 100
        self.saliendo = False
        self._tarea = None

    def _poner(self, v):
        v = int(max(0, min(100, round(v))))
        if v == self.vol:
            return
        self.vol = v
        try:
            self.video.volume = v
            self.video.update()
        except Exception:
            pass  # el video todavía no está en pantalla

    def _cancelar(self):
        if self._tarea is not None and not self._tarea.done():
            self._tarea.cancel()
        self._tarea = None

    def _rampa(self, hasta, segundos):
        self._cancelar()
        desde = self.vol

        async def correr():
            n = max(1, int(segundos / PASO_SEG))
            for i in range(1, n + 1):
                self._poner(desde + (hasta - desde) * i / n)
                await asyncio.sleep(PASO_SEG)

        try:
            self._tarea = asyncio.ensure_future(correr())
        except RuntimeError:  # sin bucle asyncio (no debería pasar): volumen directo
            self._poner(hasta)

    def nueva(self):
        """Empezó otra canción: entra suave."""
        self.saliendo = False
        self._cancelar()
        self._poner(25)
        self._rampa(100, ENTRADA_SEG)

    def posicion(self, pos, dur, pausado=False):
        """Cada segundo: al acercarse el final, baja el volumen."""
        if pausado or dur < 40:
            return
        quedan = dur - pos
        if self.saliendo and quedan > SALIDA_SEG + 2:
            self.normal()  # la adelantaron hacia atrás (televisor espejo): vuelve el volumen
        elif not self.saliendo and quedan <= SALIDA_SEG and pos > 10:
            self.saliendo = True
            self._rampa(0, max(1.0, quedan - 0.3))
        elif (not self.saliendo and self.vol < 100 and pos > ENTRADA_SEG + 2
              and (self._tarea is None or self._tarea.done())):
            self._poner(100)  # seguro: el volumen nunca se queda bajo a mitad de canción

    def normal(self):
        """Pausa/reanudar: volumen normal de una."""
        self.saliendo = False
        self._cancelar()
        self._poner(100)
