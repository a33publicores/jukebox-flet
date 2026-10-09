"""Cliente de la API de PlayBar GO para el reproductor del bar (sin Google, sin base)."""
import requests

from services import cola as C


class LlaveInvalida(Exception):
    """La llave del bar no existe, fue regenerada o el negocio está inactivo."""


class ApiCliente:
    def __init__(self, url, llave, timeout=12):
        self.url = str(url or "").strip().rstrip("/")
        if self.url and not self.url.startswith("http"):
            self.url = "https://" + self.url
        self.s = requests.Session()
        self.s.headers.update({"X-Llave": str(llave or "").strip(),
                               "User-Agent": "PlayBarGO-Reproductor"})
        self.timeout = timeout

    def _revisar(self, r):
        if r.status_code == 401:
            raise LlaveInvalida("La llave del bar no es válida (o el negocio está inactivo).")
        r.raise_for_status()
        d = r.json()
        if not d.get("ok", False):
            raise RuntimeError(d.get("error", "Error de la API"))
        return d

    def _get(self, ruta, **params):
        return self._revisar(self.s.get(self.url + ruta, params=params, timeout=self.timeout))

    def _post(self, ruta, datos):
        return self._revisar(self.s.post(self.url + ruta, json=datos, timeout=self.timeout))

    # --------------------------------------------------------------- lecturas
    def salud(self):
        return self._revisar(self.s.get(self.url + "/api/salud", timeout=self.timeout))

    def config(self):
        return self._get("/api/v1/config")

    def instantanea(self):
        return C.desde_dict(self._get("/api/v1/instantanea"))

    def aleatorio(self):
        return [C.Item(None, i["titulo"], i["canal"], i["video_id"])
                for i in self._get("/api/v1/aleatorio").get("items", [])]

    def tabla(self, dias=0, limite=1000):
        return self._get("/api/v1/tabla", dias=dias, limite=limite)

    # ------------------------------------------------------------- escrituras
    def marcar(self, fila, estado2=None, estado=None):
        self._post("/api/v1/marcar", {"fila": fila, "estado2": estado2, "estado": estado})

    def estado(self, estado, actual="", siguiente="", ack=None):
        self._post("/api/v1/estado", {"estado": estado, "actual": actual,
                                      "siguiente": siguiente, "ack": ack})

    def reordenar(self, filas):
        self._post("/api/v1/reordenar", {"filas": list(filas)})
