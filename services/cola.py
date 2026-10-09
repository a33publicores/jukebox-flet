"""
Cola de reproducción de PlayBar GO sobre Google Sheets (sin playlist de YouTube).

La hoja de cada cliente (A33, BAR01, ...) tiene las columnas:
    A Timestamp | B Cliente | C Usuario | D titulo | E canal | F videoId | G Estado | H Estado2

Flujo con el reproductor propio:
    la app agrega la fila con   Estado = "Agregado"  y  Estado2 = "Siguiente"
    (Timestamp en hora de Colombia)
    el reproductor la toma:     Estado2 = "En reproduccion"
    al terminar:                Estado2 = "Reproducido"
    si el admin la quita:       Estado2 = "Eliminado"
    si no se puede reproducir:  Estado  = "Error"

Solo las filas de HOY (desde JORNADA_HORA, 6 a. m. por defecto) son cola. Las de
fechas anteriores son el repertorio ALEATORIO que suena mientras nadie pide; en cuanto
alguien agrega, esa canción pasa a sonar, y cuando la cola se vacía vuelve el aleatorio.

Pestañas auxiliares (se crean solas):
    CONTROL      una fila por cliente: comando del admin y estado del reproductor
    REPRODUCIDAS canciones ya reproducidas, para el relleno cuando no hay cola

Todas las lecturas pasan por UNA sola petición (values_batch_get) para no
agotar la cuota de Google Sheets (60 lecturas/min).
"""
import html
import os
import random
import time
import uuid
from dataclasses import dataclass, field

from services import playbar_service as ps

E_COLA = "En cola"
E_PLAY = "En reproduccion"
E_SIGUE = "Siguiente"  # compatibilidad con el esquema anterior
E_HECHO = "Reproducido"
E_ELIM = "Eliminado"
E_ERROR = "Error"
ACTIVOS = {E_COLA, E_PLAY, E_SIGUE}

HOJA_CONTROL = "CONTROL"
HOJA_HIST = "REPRODUCIDAS"
CONTROL_COLS = [
    "cliente", "comando", "comando_id", "estado", "actual", "siguiente",
    "latido", "ack", "param",
]
HIST_COLS = ["cliente", "videoId", "titulo", "canal", "veces", "ultima"]

# Un reproductor se considera "en línea" si su último latido es más reciente.
LATIDO_MAX_SEG = 45

# Canciones "En cola" más viejas que esto se consideran restos y no se reproducen.
COLA_MAX_HORAS = float(os.getenv("COLA_MAX_HORAS", "12"))


@dataclass
class Item:
    fila: int | None  # fila 1-based en la hoja; None = canción de relleno
    titulo: str
    canal: str
    video_id: str
    usuario: str = ""
    estado: str = ""
    estado2: str = ""
    ts: float | None = None  # epoch UTC del Timestamp de la fila
    orden: float | None = None  # columna I "Orden" (al mover canciones en el reproductor)

    @property
    def clave(self):
        return self.orden if self.orden is not None else float(self.fila or 0)


@dataclass
class Instantanea:
    items: list = field(default_factory=list)  # list[Item] de la hoja del cliente
    control: dict = field(default_factory=dict)  # fila CONTROL del cliente
    control_fila: int | None = None

    inicio: float = 0.0  # epoch del inicio de la jornada (hoy)

    def de_hoy(self, it):
        return it.ts is not None and it.ts >= self.inicio

    @property
    def actual(self):
        for it in self.items:
            if it.estado2 == E_PLAY and self.de_hoy(it):
                return it
        return None

    @property
    def cola(self):
        """Canciones pedidas HOY que esperan turno, en orden (columna Orden o fila).
        También toma las "Pendiente" de hoy (las que guardó una versión vieja de la app)."""
        return sorted([
            it for it in self.items
            if self.de_hoy(it) and it.estado != E_ERROR and (
                it.estado2 in (E_COLA, E_SIGUE)
                or (it.estado == "Pendiente" and not it.estado2)
            )
        ], key=lambda it: it.clave)

    @property
    def aleatorio(self):
        """Repertorio para cuando nadie pide: canciones de fechas anteriores (sin repetir).
        Si el lugar es nuevo y no tiene historial, usa lo ya sonado hoy."""
        def sirve(it):
            return it.estado != E_ERROR and it.estado2 not in (E_ELIM, E_ERROR)

        vistos, lista = set(), []
        for it in reversed(self.items):
            if it.video_id in vistos or not sirve(it) or self.de_hoy(it):
                continue
            vistos.add(it.video_id)
            lista.append(it)
        if not lista:
            for it in reversed(self.items):
                if it.video_id not in vistos and sirve(it) and it.estado2 == E_HECHO:
                    vistos.add(it.video_id)
                    lista.append(it)
        return lista

    @property
    def atascadas(self):
        """Filas de días anteriores que quedaron como activas (p. ej. En reproduccion)."""
        return [it.fila for it in self.items
                if not self.de_hoy(it) and it.estado2 in ACTIVOS]


# ---------------------------------------------------------------------------
# Utilidades de hoja
# ---------------------------------------------------------------------------
_hojas_listas = set()


def _col(row, i):
    return str(row[i]).strip() if len(row) > i and row[i] is not None else ""


_aux_cache = {}


def _hoja_aux(nombre, encabezados):
    """Obtiene la pestaña auxiliar (en memoria); la crea con encabezados si no existe."""
    ws = _aux_cache.get(nombre)
    if ws is not None:
        return ws
    ss = ps._spreadsheet_obj()
    try:
        ws = ps._con_reintentos(ss.worksheet, nombre)
    except Exception as ex:
        if not ps._no_existe(ex):
            raise
        ws = ss.add_worksheet(title=nombre, rows="1000", cols=str(len(encabezados) + 2))
        ws.append_row(encabezados)
        print(f"🆕 Pestaña creada: {nombre}")
    _hojas_listas.add(nombre)
    _aux_cache[nombre] = ws
    return ws


def _nombre_hoja(cliente):
    cfg = ps.obtener_config_cliente(cliente)
    if not cfg:
        raise ValueError(f"Cliente {cliente!r} no existe en la hoja CLIENTES")
    return cfg["sheet"]


def _epoch(texto):
    return ps.epoch_local(texto)


def _num(texto):
    try:
        return float(str(texto).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _parse_items(valores):
    items = []
    for n, row in enumerate(valores[1:], start=2):
        vid = _col(row, 5)
        if not vid:
            continue
        items.append(Item(
            fila=n,
            titulo=html.unescape(_col(row, 3)),
            canal=html.unescape(_col(row, 4)),
            video_id=vid,
            usuario=_col(row, 2),
            estado=_col(row, 6),
            estado2=_col(row, 7),
            ts=_epoch(_col(row, 0)),
            orden=_num(_col(row, 8)),
        ))
    return items


def instantanea(cliente, nombre_hoja=None):
    """Lee cola + CONTROL en UNA petición."""
    ss = ps._spreadsheet_obj()
    nombre_hoja = nombre_hoja or _nombre_hoja(cliente)
    if HOJA_CONTROL not in _hojas_listas:
        _hoja_aux(HOJA_CONTROL, CONTROL_COLS)
    resp = ps._con_reintentos(
        ss.values_batch_get,
        [f"'{nombre_hoja}'!A:I", f"'{HOJA_CONTROL}'!A:I"],
    )
    rangos = resp.get("valueRanges", [])
    hoja = rangos[0].get("values", []) if len(rangos) > 0 else []
    ctrl = rangos[1].get("values", []) if len(rangos) > 1 else []

    snap = Instantanea(items=_parse_items(hoja), inicio=ps.inicio_jornada())
    for n, row in enumerate(ctrl[1:], start=2):
        if _col(row, 0) == str(cliente):
            snap.control_fila = n
            _fila_control[str(cliente)] = n
            snap.control = {k: _col(row, i) for i, k in enumerate(CONTROL_COLS)}
            break
    return snap


def reordenar(cliente, snap, filas, nombre_hoja=None):
    """Guarda el nuevo orden de la cola en la columna I (Orden), en UNA petición.
    Reparte las mismas claves que ya tenían esas canciones, así las que pidan
    después siguen quedando al final."""
    if not filas or snap is None:
        return
    por_fila = {it.fila: it for it in snap.items}
    elegidas = [por_fila[f] for f in filas if f in por_fila]
    claves = sorted(it.clave for it in elegidas)
    datos = [{"range": "I1", "values": [["Orden"]]}]
    for it, k in zip(elegidas, claves):
        datos.append({"range": f"I{it.fila}", "values": [[k]]})
        it.orden = k
    ws = _ws_cliente(nombre_hoja or _nombre_hoja(cliente))
    ps._con_reintentos(ws.batch_update, datos)
    print(f"↕️ Nuevo orden guardado ({len(elegidas)} canciones)")


def cerrar_atascadas(cliente, filas, nombre_hoja=None):
    """Marca como Reproducido, en UNA petición, las filas viejas que quedaron activas."""
    if not filas:
        return
    ws = _ws_cliente(nombre_hoja or _nombre_hoja(cliente))
    ps._con_reintentos(ws.batch_update, [
        {"range": f"H{f}", "values": [[E_HECHO]]} for f in filas
    ])
    print(f"🧹 {len(filas)} filas de días anteriores pasaron a Reproducido")


def _ws_cliente(nombre_hoja):
    return ps.obtener_hoja_cliente(nombre_hoja)


def marcar(cliente, fila, estado2=None, estado=None, nombre_hoja=None):
    """Cambia Estado2 (col H) y/o Estado (col G) de una fila."""
    ws = _ws_cliente(nombre_hoja or _nombre_hoja(cliente))
    if estado is not None:
        ps._con_reintentos(ws.update_cell, fila, 7, estado)
    if estado2 is not None:
        ps._con_reintentos(ws.update_cell, fila, 8, estado2)


# ---------------------------------------------------------------------------
# CONTROL: comandos del admin y estado del reproductor
# ---------------------------------------------------------------------------
_fila_control = {}


def _asegurar_fila_control(cliente):
    ws = _hoja_aux(HOJA_CONTROL, CONTROL_COLS)
    if str(cliente) in _fila_control:
        return ws, _fila_control[str(cliente)]
    col = ps._con_reintentos(ws.col_values, 1)
    for n, v in enumerate(col, start=1):
        if v.strip() == str(cliente):
            _fila_control[str(cliente)] = n
            return ws, n
    ps._con_reintentos(ws.append_row, [str(cliente)] + [""] * (len(CONTROL_COLS) - 1))
    _fila_control[str(cliente)] = len(col) + 1
    return ws, len(col) + 1


def enviar_comando(cliente, comando, param=""):
    """Admin -> reproductor. Comandos: pausar, reanudar, siguiente, anterior."""
    ws, fila = _asegurar_fila_control(cliente)
    cid = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"
    ps._con_reintentos(ws.update, f"B{fila}:C{fila}", [[comando, cid]])
    if param != "":
        ps._con_reintentos(ws.update, f"I{fila}", [[str(param)]])
    return cid


def publicar_estado(cliente, estado, actual="", siguiente="", ack=None):
    """Reproductor -> hoja: estado, qué suena, qué sigue, latido y ack."""
    ws, fila = _asegurar_fila_control(cliente)
    ps._con_reintentos(
        ws.update, f"D{fila}:G{fila}",
        [[estado, actual, siguiente, str(int(time.time()))]],
    )
    if ack is not None:
        ps._con_reintentos(ws.update, f"H{fila}", [[ack]])


def estado_reproductor(cliente):
    """Para el panel admin: estado + si el reproductor está en línea."""
    snap = instantanea(cliente)
    c = snap.control
    try:
        edad = time.time() - float(c.get("latido") or 0)
    except ValueError:
        edad = 1e9
    return {
        "online": edad <= LATIDO_MAX_SEG,
        "estado": c.get("estado", ""),
        "actual": snap.actual.titulo if snap.actual else c.get("actual", ""),
        "siguiente": (snap.cola[0].titulo if snap.cola else c.get("siguiente", "")),
        "cola": snap.cola,
        "comando_pendiente": bool(c.get("comando_id")) and c.get("comando_id") != c.get("ack"),
    }


def eliminar_de_cola(cliente, fila):
    """Quita una canción que aún está en cola (no la que suena)."""
    snap = instantanea(cliente)
    for it in snap.cola:
        if it.fila == fila:
            marcar(cliente, fila, estado2=E_ELIM)
            return True
    return False


# ---------------------------------------------------------------------------
# Historial para relleno
# ---------------------------------------------------------------------------
class Historial:
    """Canciones ya reproducidas (pestaña REPRODUCIDAS) usadas como relleno."""

    def __init__(self, cliente):
        self.cliente = str(cliente)
        self.filas = {}  # video_id -> (fila, titulo, canal, veces)
        self.cargado = False

    def cargar(self, sembrar_desde=None):
        ws = _hoja_aux(HOJA_HIST, HIST_COLS)
        valores = ps._con_reintentos(ws.get_all_values)
        self.filas = {}
        for n, row in enumerate(valores[1:], start=2):
            if _col(row, 0) != self.cliente:
                continue
            try:
                veces = int(_col(row, 4) or 0)
            except ValueError:
                veces = 0
            self.filas[_col(row, 1)] = (n, _col(row, 2), _col(row, 3), veces)
        self.cargado = True
        if not self.filas and sembrar_desde:
            self._sembrar(ws, sembrar_desde)

    def _sembrar(self, ws, items):
        """Primera vez: usa las canciones que ya pidieron los clientes."""
        vistos, nuevas = set(), []
        for it in reversed(items):  # las más recientes primero
            if it.video_id in vistos or it.estado2 == E_ELIM or it.estado == E_ERROR:
                continue
            if it.estado != "Agregado":
                continue
            vistos.add(it.video_id)
            nuevas.append([self.cliente, it.video_id, it.titulo, it.canal, 0, ""])
            if len(nuevas) >= 300:
                break
        if nuevas:
            ps._con_reintentos(ws.append_rows, nuevas)
            print(f"🌱 Historial sembrado con {len(nuevas)} canciones")
            self.cargar()

    def registrar(self, item):
        """Suma una reproducción (crea la fila si es nueva)."""
        ws = _hoja_aux(HOJA_HIST, HIST_COLS)
        ahora = time.strftime("%Y-%m-%d %H:%M:%S")
        if item.video_id in self.filas:
            fila, t, c, veces = self.filas[item.video_id]
            ps._con_reintentos(ws.update, f"E{fila}:F{fila}", [[veces + 1, ahora]])
            self.filas[item.video_id] = (fila, t, c, veces + 1)
        else:
            ps._con_reintentos(ws.append_row, [
                self.cliente, item.video_id, item.titulo, item.canal, 1, ahora,
            ])
            self.cargar()

    def elegir(self, excluir=()):
        """Canción de relleno al azar, evitando las recientes."""
        candidatas = [
            Item(None, t, c, vid) for vid, (_, t, c, _) in self.filas.items()
            if vid not in set(excluir)
        ]
        if not candidatas and self.filas:
            candidatas = [Item(None, t, c, vid) for vid, (_, t, c, _) in self.filas.items()]
        return random.choice(candidatas) if candidatas else None
