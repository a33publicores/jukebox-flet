"""
Conexión web que se retoma sola, sin recargar la página (app web de PlayBar GO en Railway).

En el celular la conexión con el servidor se cae seguido (datos móviles que cambian de IP,
pantalla bloqueada). La reconexión propia de Flet 1.0 deja la pantalla "pegada" (el
navegador deja de aplicar los cambios), y por eso antes la página se recargaba sola cada
pocos minutos.

Aquí la conexión se retoma por debajo y Flet ni se entera:
  - la página (web_boot.py) le pone a su conexión un identificador (pbgo_t). Si se cae,
    abre otra con el mismo identificador (pbgo_r=1) y dice cuántos mensajes alcanzó a
    recibir (pbgo_n);
  - el servidor engancha esa conexión nueva a la MISMA sesión, le dice cuántos mensajes
    le llegaron de la página ("pbgo:N") y le repite los que se perdieron en el corte; la
    página hace lo mismo con los suyos;
  - mientras tanto la sesión sigue viva (hasta GRACIA_SEG) y lo que haya que mandarle a la
    página espera en la cola.
Si la sesión ya no existe (servidor reiniciado, o más tiempo fuera que GRACIA_SEG), el
servidor cierra con el código 4000 y la página se recarga una vez.
"""
import asyncio
import collections

GRACIA_SEG = 60 * 60       # cuánto espera la sesión a que la página vuelva
GUARDAR_ENVIADOS = 600     # mensajes recientes que se guardan para repetirlos
MAX_EN_COLA = 3000         # si se acumula más que esto sin página, se suelta la sesión
CIERRE_RECARGAR = 4000     # la página se recarga
CIERRE_CAMBIO = 4100       # conexión vieja reemplazada por una nueva
CIERRES_FINALES = (1000, 1001)  # la página se cerró o se fue a otra dirección

_por_token = {}


def _ws(app):
    return getattr(app, "_FletApp__websocket", None)


def _preparar(app, token):
    app._pbgo_token = token
    app._pbgo_enviados = collections.deque(maxlen=GUARDAR_ENVIADOS)  # (n, bytes)
    app._pbgo_n_env = 0
    app._pbgo_n_rec = 0
    app._pbgo_fin = False
    app._pbgo_cambio = asyncio.Event()
    app._pbgo_candado = asyncio.Lock()
    app._pbgo_soltar = {}  # websocket reemplazo -> Event (su conexión ya no se usa)


def _avisar_cambio(app):
    app._pbgo_cambio.set()
    app._pbgo_cambio = asyncio.Event()


def _soltar(app, ws):
    evento = app._pbgo_soltar.pop(ws, None) if hasattr(app, "_pbgo_soltar") else None
    if evento is not None:
        evento.set()


def _terminar(app):
    if not getattr(app, "_pbgo_fin", True):
        app._pbgo_fin = True
        _soltar(app, _ws(app))
        _avisar_cambio(app)


async def _esperar_reemplazo(app, ws_vieja):
    """True si llegó una conexión nueva para esta sesión; False si hay que soltarla."""
    if not hasattr(app, "_pbgo_token"):
        return False
    lazo = asyncio.get_running_loop()
    hasta = lazo.time() + GRACIA_SEG
    while True:
        if app._pbgo_fin:
            return False
        actual = _ws(app)
        if actual is not None and actual is not ws_vieja:
            return True
        cola = getattr(app, "_FletApp__send_queue", None)
        if cola is not None and cola.qsize() > MAX_EN_COLA:
            return False
        falta = hasta - lazo.time()
        if falta <= 0:
            return False
        try:
            await asyncio.wait_for(app._pbgo_cambio.wait(), timeout=min(falta, 30))
        except asyncio.TimeoutError:
            pass


async def _reemplazar(app, ws, n_cliente):
    """Engancha la conexión nueva `ws` a la sesión de `app` y le repite lo perdido."""
    await ws.accept()
    soltar = asyncio.Event()
    async with app._pbgo_candado:
        primero = app._pbgo_enviados[0][0] if app._pbgo_enviados else app._pbgo_n_env + 1
        if app._pbgo_fin or n_cliente < primero - 1 or n_cliente > app._pbgo_n_env:
            await ws.close(code=CIERRE_RECARGAR)
            _terminar(app)  # no se puede poner al día: la página se recarga
            return
        vieja = _ws(app)
        app._FletApp__websocket = ws
        app._pbgo_soltar[ws] = soltar
        _soltar(app, vieja)
        n_servidor = app._pbgo_n_rec
        try:
            await ws.send_text(f"pbgo:{n_servidor}")
            for n, datos in list(app._pbgo_enviados):
                if n > n_cliente:
                    await ws.send_bytes(datos)
        except Exception:
            pass  # se volvió a caer: los bucles lo notan y esperan otra conexión
        _avisar_cambio(app)
    if vieja is not None:
        try:
            await vieja.close(code=CIERRE_CAMBIO)
        except Exception:
            pass
    await soltar.wait()  # la conexión sigue abierta mientras la sesión la use


def instalar(_app):
    FletApp = _app.FletApp
    if getattr(FletApp.handle, "_pbgo_reanudar", False):
        return
    handle_original = FletApp.handle
    msgpack = _app.msgpack
    decodificar = _app.decode_ext_from_msgpack
    WebSocketDisconnect = _app.WebSocketDisconnect

    async def handle(self, websocket):
        q = websocket.query_params
        token = (q.get("pbgo_t") or "")[:64]
        if token and q.get("pbgo_r") == "1":
            app = _por_token.get(token)
            try:
                n_cliente = int(q.get("pbgo_n") or 0)
            except ValueError:
                n_cliente = -1
            if app is None:
                await websocket.accept()
                await websocket.close(code=CIERRE_RECARGAR)
                return
            await _reemplazar(app, websocket, n_cliente)
            return
        if token:
            _preparar(self, token)
            _por_token[token] = self
        try:
            await handle_original(self, websocket)
        finally:
            if token and _por_token.get(token) is self:
                del _por_token[token]
            _terminar(self)

    async def bucle_recibir(self):
        while True:
            ws = _ws(self)
            if ws is None:
                break
            codigo = None
            try:
                while True:
                    datos = await ws.receive_bytes()
                    if _ws(self) is not ws:
                        break  # llegó tarde por la conexión vieja: la página lo repite
                    if hasattr(self, "_pbgo_token"):
                        self._pbgo_n_rec += 1
                    if not datos:
                        continue
                    tipo = datos[0]
                    if tipo == 0x00:
                        await self._FletApp__on_message(msgpack.unpackb(datos[1:], ext_hook=decodificar))
                    elif tipo == 0x01 and len(datos) >= 5:
                        canal = self._data_channels.get(int.from_bytes(datos[1:5], "little", signed=False))
                        if canal is not None:
                            canal._deliver(datos[5:])
                continue  # cambiaron la conexión: se sigue leyendo de la nueva
            except WebSocketDisconnect as ex:
                codigo = ex.code
            except Exception:
                pass
            if _ws(self) is not ws:
                continue
            if codigo in CIERRES_FINALES or not await _esperar_reemplazo(self, ws):
                break
        _terminar(self)
        cola = getattr(self, "_FletApp__send_queue", None)
        if getattr(self, "_FletApp__session", None) and cola is not None:
            await cola.put(None)  # termina el bucle de envío

    async def bucle_enviar(self):
        cola = self._FletApp__send_queue
        guardar = hasattr(self, "_pbgo_token")
        while True:
            mensaje = await cola.get()
            if mensaje is None:
                break
            if not guardar:
                try:
                    await self._FletApp__websocket.send_bytes(mensaje)
                    continue
                except Exception:
                    break
            async with self._pbgo_candado:
                self._pbgo_n_env += 1
                self._pbgo_enviados.append((self._pbgo_n_env, mensaje))
                ws = _ws(self)
                try:
                    await ws.send_bytes(mensaje)
                    continue
                except Exception:
                    pass
            # Se cayó: el mensaje quedó guardado y se repite cuando vuelva la página.
            if not await _esperar_reemplazo(self, ws):
                break
        ws = _ws(self)
        _terminar(self)
        try:
            if ws is not None:
                await ws.close()
        except Exception:
            pass
        while not cola.empty():
            cola.get_nowait()  # lo pendiente ya no tiene a quién llegar
        self._FletApp__websocket = None
        self._FletApp__send_queue = None

    handle._pbgo_reanudar = True
    FletApp.handle = handle
    FletApp._FletApp__receive_loop = bucle_recibir
    FletApp._FletApp__send_loop = bucle_enviar
