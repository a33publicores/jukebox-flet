import json
import os



class KaraokeScanner:

    CONFIG_FILE = "data/config.json"

    def __init__(self):
        self.ruta = self.cargar_ruta()

    def cargar_ruta(self):

        if not os.path.exists(self.CONFIG_FILE):
            return ""

        try:
            with open(
                self.CONFIG_FILE,
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            return data.get("ruta_karaokes", "")

        except:
            return ""

    def guardar_ruta(self, ruta):

        os.makedirs("data", exist_ok=True)

        with open(
            self.CONFIG_FILE,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                {
                    "ruta_karaokes": ruta
                },
                f,
                indent=4,
                ensure_ascii=False
            )

        self.ruta = ruta

    
    def escanear(self):

        canciones = []

        print("=" * 70)
        print("RUTA:", self.ruta)
        print("EXISTE:", os.path.exists(self.ruta))
        print("=" * 70)

        if not self.ruta:
            return canciones

        extensiones = (
            ".mp4",
            ".avi",
            ".mkv",
            ".mpg",
            ".mpeg",
            ".wmv",
            ".mov",
            ".flv"
        )

        for carpeta, subcarpetas, archivos in os.walk(self.ruta):

            print("\n📁 Carpeta:", carpeta)
            print("Subcarpetas:", len(subcarpetas))
            print("Archivos:", len(archivos))

            for archivo in archivos:

                nombre, extension = os.path.splitext(archivo)

                print(f"   {archivo}  ->  {extension}")

                if extension.lower() in extensiones:

                    canciones.append({

                        "artista": os.path.basename(carpeta),

                        "titulo": nombre,

                        "ruta": os.path.join(carpeta, archivo)

                    })

        print("\nTOTAL ENCONTRADAS:", len(canciones))

        return canciones