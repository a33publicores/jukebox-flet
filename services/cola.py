"""
Cola de reproducción de PlayBar GO (base de datos PostgreSQL en Railway).

Flujo:
    la app agrega el pedido con   estado = "Agregado"  y  estado2 = "Siguiente"
    el reproductor lo toma:       estado2 = "En reproduccion"
    al terminar:                  estado2 = "Reproducido"
    si el admin lo quita:         estado2 = "Eliminado"
    si no se puede reproducir:    estado  = "Error"

Solo lo pedido HOY (desde JORNADA_HORA, 6 a. m.) es cola. Lo de fechas anteriores es
el repertorio ALEATORIO que suena mientras nadie pide.

`Item.fila` es el id del pedido en la base (antes era la fila de la hoja).
Este módulo se usa en Railway (app web y API). El reproductor del bar NO se conecta
a la base: usa la API con la llave de su negocio (services/api_cliente.py).
"""
import time
from dataclasses import asdict, dataclass, field

from services import db
from services import playbar_service as ps

E_COLA = "En cola"
E_PLAY = "En reproduccion"
E_SIGUE = "Siguiente"
E_HECHO = "Reproducido"
E_ELIM = "Eliminado"
E_ERROR = "Error"
ACTIVOS = {E_COLA, E_PLAY, E_SIGUE}

# Un reproductor se considera "en línea" si su último latido es más reciente.
LATIDO_MAX_SEG = 45
_ultima_limpieza = {}


@dataclass
class Item:
    fila: int | None  # id del pedido; None = canción aleatoria (relleno)
    titulo: str
    canal: str
    video_id: str
    usuario: str = ""
    estado: str = ""
    estado2: str = ""
    ts: float | None = None
    orden: float | None = None

    @property
    def clave(self):
        return self.orden if self.orden is not None else float(self.fila or 0)


@dataclass
class Instantanea:
    items: list = field(default_factory=list)      # pedidos de HOY
    control: dict = field(default_factory=dict)
    inicio: float = 0.0                            # inicio de la jornada
    aleatorio: list = field(default_factory=list)  # lo llena quien lo necesite

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
        """Canciones pedidas HOY que esperan turno, en orden (columna orden o llegada)."""
        return sorted([
            it for it in self.items
            if self.de_hoy(it) and it.estado != E_ERROR and it.estado2 in (E_COLA, E_SIGUE)
        ], key=lambda it: it.clave)


def _item(f):
    return Item(
        fila=f["id"], titulo=f.get("titulo", ""), canal=f.get("canal", ""),
        video_id=f["video_id"], usuario=f.get("usuario", ""), estado=f.get("estado", ""),
        estado2=f.get("estado2", ""), ts=float(f["ts"]) if f.get("ts") is not None else None,
        orden=float(f["orden"]) if f.get("orden") is not None else None,
    )


# ---------------------------------------------------------------------------
# Lecturas
# ---------------------------------------------------------------------------
def instantanea(cliente, nombre_hoja=None):
    """Pedidos de hoy + control. Limpia filas viejas atascadas cada 10 min."""
    cliente = str(cliente)
    inicio = ps.inicio_jornada()
    if time.time() - _ultima_limpieza.get(cliente, 0) > 600:
        n = db.cerrar_atascadas(cliente, inicio)
        if n:
            print(f"🧹 {n} pedidos de días anteriores pasaron a Reproducido")
        _ultima_limpieza[cliente] = time.time()
    items = [_item(f) for f in db.pedidos_desde(cliente, inicio)]
    return Instantanea(items=items, control=db.control(cliente), inicio=inicio)


def aleatorio(cliente):
    return [Item(None, f["titulo"], f["canal"], f["video_id"])
            for f in db.aleatorio(str(cliente), ps.inicio_jornada())]


# ---------------------------------------------------------------------------
# Escrituras
# ---------------------------------------------------------------------------
def marcar(cliente, fila, estado2=None, estado=None, nombre_hoja=None):
    db.marcar(str(cliente), fila, estado2=estado2, estado=estado)


def reordenar(cliente, filas):
    db.reordenar(str(cliente), filas)


def enviar_comando(cliente, comando, param=""):
    """Admin -> reproductor. Comandos: pausar, reanudar, siguiente, anterior."""
    return db.enviar_comando(str(cliente), comando, param)


def publicar_estado(cliente, estado, actual="", siguiente="", ack=None):
    db.publicar_estado(str(cliente), estado, actual, siguiente, ack)


def estado_reproductor(cliente):
    """Para el panel admin: estado + si el reproductor está en línea."""
    snap = instantanea(cliente)
    c = snap.control
    try:
        edad = time.time() - float(c.get("latido") or 0)
    except (TypeError, ValueError):
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
    for it in instantanea(cliente).cola:
        if it.fila == fila:
            marcar(cliente, fila, estado2=E_ELIM)
            return True
    return False


# ---------------------------------------------------------------------------
# Para la API: convertir a JSON y de vuelta
# ---------------------------------------------------------------------------
def a_dict(snap):
    return {
        "items": [asdict(i) for i in snap.items],
        "control": {k: v for k, v in (snap.control or {}).items()},
        "inicio": snap.inicio,
    }


def desde_dict(d):
    return Instantanea(
        items=[Item(**i) for i in d.get("items", [])],
        control=d.get("control") or {},
        inicio=float(d.get("inicio") or 0),
    )
