"""
Cola de reproducción de PlayBar GO sobre Google Sheets (sin playlist de YouTube).

La hoja de cada cliente (A33, BAR01, ...) tiene las columnas:
    A Timestamp | B Cliente | C Usuario | D titulo | E canal | F videoId | G Estado | H Estado2

Flujo con el reproductor propio:
    la app agrega la fila con   Estado = "Agregado"  y  Estado2 = "En cola"
    el reproductor la toma:     Estado2 = "En reproduccion"
    al terminar:                Estado2 = "Reproducido"
    si el admin la quita:       Estado2 = "Eliminado"
    si no se puede reproducir:  Estado  = "Error"

Las filas antiguas (Agregado con Estado2 vacío) NO son cola: son historial. Así
el reproductor jamás intenta tocar las ~1000 canciones viejas de golpe.

Pestañas auxiliares (se crean solas):
    CONTROL      una fila por cliente: comando del admin y estado del reproductor
    REPRODUCIDAS canciones ya reproducidas, para el relleno cuando no hay cola

Todas las lecturas pasan por UNA sola petición (values_batch_get) para no
agotar la cuota de Google Sheets (60 lecturas/min).
"""
import calendar
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


@dataclass
class Instantanea:
    items: list = field(default_factory=list)  # list[Item] de la hoja del cliente
    control: dict = field(default_factory=dict)  # fila CONTROL del cliente
    control_fila: int | None = None

    @property
    def actual(self):
        for it in self.items:
            if it.estado2 == E_PLAY:
                return it
        return None

    @property
    def cola(self):
        """Canciones esperando, en orden de la hoja.

        Se ignoran las de más de COLA_MAX_HORAS: son restos de otra noche (el reproductor
        estuvo apagado) y no deben sonar al día siguiente.
        """
        limite = time.time() - COLA_MAX_HORAS * 3600
        return [
            it for it in self.items
            if it.estado2 in (E_COLA, E_SIGUE) and (it.ts is None or it.ts >= limite)
        ]


# ---------------------------------------------------------------------------
# Utilidades de hoja
# ---------------------------------------------------------------------------
_hojas_listas = set()


def _col(row, i):
    return str(row[i]).strip() if len(row) > i and row[i] is not None else ""


def _hoja_aux(nombre, encabezados):
    """Obtiene la pestaña auxiliar; la crea con encabezados si no existe."""
    ss = ps._spreadsheet_obj()
    try:
        ws = ss.worksheet(nombre)
    except Exception:
        ws = ss.add_worksheet(title=nombre, rows="1000", cols=str(len(encabezados) + 2))
        ws.append_row(encabezados)
        print(f"🆕 Pestaña creada: {nombre}")
    _hojas_listas.add(nombre)
    return ws


def _nombre_hoja(cliente):
    cfg = ps.obtener_config_cliente(cliente)
    if not cfg:
        raise ValueError(f"Cliente {cliente!r} no existe en la hoja CLIENTES")
    return cfg["sheet"]


def _epoch(texto):
    try:
        return calendar.timegm(time.strptime(str(texto).strip()[:19], "%Y-%m-%d %H:%M:%S"))
    except Exception:
        return None


def _parse_items(valores):
    items = []
    for n, row in enumerate(valores[1:], start=2):
        vid = _col(row, 5)
        if not vid:
            continue
        items.append(Item(
            fila=n,
            titulo=_col(row, 3),
            canal=_col(row, 4),
            video_id=vid,
            usuario=_col(row, 2),
            estado=_col(row, 6),
            estado2=_col(row, 7),
            ts=_epoch(_col(row, 0)),
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
        [f"'{nombre_hoja}'!A:H", f"'{HOJA_CONTROL}'!A:I"],
    )
    rangos = resp.get("valueRanges", [])
    hoja = rangos[0].get("values", []) if len(rangos) > 0 else []
    ctrl = rangos[1].get("values", []) if len(rangos) > 1 else []

    snap = Instantanea(items=_parse_items(hoja))
    for n, row in enumerate(ctrl[1:], start=2):
        if _col(row, 0) == str(cliente):
            snap.control_fila = n
            snap.control = {k: _col(row, i) for i, k in enumerate(CONTROL_COLS)}
            break
    return snap


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
def _asegurar_fila_control(cliente):
    ws = _hoja_aux(HOJA_CONTROL, CONTROL_COLS)
    col = ps._con_reintentos(ws.col_values, 1)
    for n, v in enumerate(col, start=1):
        if v.strip() == str(cliente):
            return ws, n
    ps._con_reintentos(ws.append_row, [str(cliente)] + [""] * (len(CONTROL_COLS) - 1))
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
