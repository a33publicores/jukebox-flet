import json
import os
from datetime import datetime


class KaraokeQueue:

    FILE = "data/karaoke_queue.json"

    @classmethod
    def cargar(cls):

        if not os.path.exists(cls.FILE):
            return []

        with open(
            cls.FILE,
            "r",
            encoding="utf-8"
        ) as f:

            return json.load(f)

    @classmethod
    def guardar(cls, cola):

        os.makedirs("data", exist_ok=True)

        with open(
            cls.FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                cola,
                f,
                indent=4,
                ensure_ascii=False
            )

    @classmethod
    def agregar(cls, cliente, telefono, cancion):

        cola = cls.cargar()

        cola.append({

            "id": len(cola) + 1,

            "cliente": cliente,

            "telefono": telefono,

            "titulo": cancion["titulo"],

            "artista": cancion["artista"],

            "ruta": cancion["ruta"],

            "hora": datetime.now().strftime("%H:%M:%S"),

            "estado": "Pendiente"

        })

        cls.guardar(cola)

        return len(cola)

    @classmethod
    def eliminar(cls, id_cancion):

        cola = cls.cargar()

        cola = [

            c

            for c in cola

            if c["id"] != id_cancion

        ]

        cls.guardar(cola)

    @classmethod
    def actualizar_estado(cls, id_cancion, estado):

        cola = cls.cargar()

        for c in cola:

            if c["id"] == id_cancion:

                c["estado"] = estado

        cls.guardar(cola)