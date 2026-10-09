"""Cliente de la API de PlayBar GO para el reproductor del bar (sin Google, sin base)."""
import threading
import time

import requests

from services import cola as C


class LlaveInvalida(Exception):
    """La llave del bar no existe, fue regenerada o el negocio está inactivo."""


class ApiCliente:
    """timeout = (segundos para conectar, segundos para responder). Las lecturas se
    reintentan una vez: un corte de 1-2 s de internet no debe verse como error."""

    def __init__(self, url, llave, timeout=(6, 10), reintentos=1):
        self.url = str(url or "").strip().rstrip("/")
        if self.url and not self.url.startswith("http"):
            self.url = "https://" + self.url
        self.llave = str(llave or "").strip()
        self.timeout = timeout
        self.reintentos = reintentos
        self._local = threading.local()  # una sesión por hilo (requests no es seguro entre hilos)

    @property
    def s(self):
        ses = getattr(self._local, "s", None)
        if ses is None:
            ses = requests.Session()
            ses.headers.update({"X-Llave": self.llave, "User-Agent": "PlayBarGO-Reproductor"})
            self._local.s = ses
        return ses

    def _pedir(self, metodo, ruta, reintentar=True, **kw):
        intentos = 1 + (self.reintentos if reintentar else 0)
        for n in range(intentos):
            try:
                return self._revisar(getattr(self.s, metodo)(self.url + ruta, timeout=self.timeout, **kw))
            except (requests.ConnectionError, requests.Timeout):
                if n + 1 >= intentos:
                    raise
                self._local.s = None  # conexión dañada: se abre una nueva
                time.sleep(1.5)

    def _revisar(self, r):
        if r.status_code == 401:
            raise LlaveInvalida("La llave del bar no es válida (o el negocio está inactivo).")
        r.raise_for_status()
        d = r.json()
        if not d.get("ok", False):
            raise RuntimeError(d.get("error", "Error de la API"))
        return d

    def _get(self, ruta, **params):
        return self._pedir("get", ruta, params=params)

    def _post(self, ruta, datos):
        # las escrituras dejan el mismo resultado si se repiten (poner un estado), se reintentan
        return self._pedir("post", ruta, json=datos)

    # --------------------------------------------------------------- lecturas
    def salud(self):
        return self._pedir("get", "/api/salud", reintentar=False)

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
