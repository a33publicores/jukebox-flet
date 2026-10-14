"""Modelo de la cola (solo lo que necesita el TV: sin base de datos).

Es la parte de services/cola.py que usa el reproductor: estados, Item, Instantanea y
la conversión desde el JSON de la API. El TV nunca se conecta a la base, solo a la API.
"""
from dataclasses import dataclass, field

E_COLA = "En cola"
E_PLAY = "En reproduccion"
E_SIGUE = "Siguiente"
E_HECHO = "Reproducido"
E_ELIM = "Eliminado"
E_ERROR = "Error"
ACTIVOS = {E_COLA, E_PLAY, E_SIGUE}


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
    aleatorio: list = field(default_factory=list)

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
        return sorted([
            it for it in self.items
            if self.de_hoy(it) and it.estado != E_ERROR and it.estado2 in (E_COLA, E_SIGUE)
        ], key=lambda it: it.clave)


def desde_dict(d):
    campos = set(Item.__dataclass_fields__)
    return Instantanea(
        items=[Item(**{k: v for k, v in i.items() if k in campos}) for i in d.get("items", [])],
        control=d.get("control") or {},
        inicio=float(d.get("inicio") or 0),
    )
