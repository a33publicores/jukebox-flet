"""
Canciones en la nube (Cloudflare R2) para el reproductor de PC y el de TV.

  * Antes de bajar una canción de YouTube, se pregunta a la nube: si otro bar ya la subió,
    se baja de ahí (más rápido y sin depender de YouTube).
  * Si hubo que bajarla de YouTube, se sube a la nube en segundo plano para los demás.
  * Con la nube activa, el equipo guarda solo las canciones recientes (tope de espacio);
    las viejas se borran y, si las vuelven a pedir, se bajan de la nube.

La API de PlayBar GO firma las direcciones (solo con llave válida). Si la nube no está
configurada, todo sigue como antes. Este archivo es igual en reproductor/ y en tv/.
"""
import os
import queue
import threading
import time
from pathlib import Path

import requests

MAX_SUBIR = 300 * 1024 * 1024
APAGADA_SEG = 10 * 60  # si la API dice que no hay nube, no se vuelve a preguntar en 10 min


class Nube:
    def __init__(self, pedir):
        """`pedir(archivo)` -> {"activo", "get", "put"} (lo da la API con la llave del bar)."""
        self._pedir = pedir
        self._apagada_hasta = 0.0
        self._cola = queue.Queue()
        self._subidas = set()
        threading.Thread(target=self._subir_en_orden, daemon=True).start()

    def _direcciones(self, archivo):
        if time.time() < self._apagada_hasta:
            return None
        try:
            d = self._pedir(archivo) or {}
        except Exception as ex:
            print(f"ℹ️ Nube: sin respuesta de la API ({type(ex).__name__})")
            return None
        if not d.get("activo"):
            self._apagada_hasta = time.time() + APAGADA_SEG
            return None
        return d

    def bajar(self, archivo, destino):
        """Baja `archivo` de la nube a `destino`. True si quedó completa."""
        d = self._direcciones(archivo)
        if not d:
            return False
        destino = Path(destino)
        tmp = destino.with_name(destino.name + ".nube")
        t0 = time.time()
        try:
            with requests.get(d["get"], stream=True, timeout=(8, 30)) as r:
                if r.status_code == 404:
                    return False
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0)
                with open(tmp, "wb") as f:
                    for trozo in r.iter_content(512 * 1024):
                        f.write(trozo)
            tam = tmp.stat().st_size
            if tam < 50_000 or (total and tam != total):
                raise IOError(f"llegó incompleta ({tam} de {total} bytes)")
            os.replace(tmp, destino)
            print(f"☁️ {archivo}: bajada de la nube ({tam / 1048576:.1f} MB, {time.time() - t0:.1f} s)")
            return True
        except Exception as ex:
            print(f"ℹ️ Nube: no se pudo bajar {archivo}: {str(ex)[:100]}")
            return False
        finally:
            try:
                tmp.unlink()
            except OSError:
                pass

    def subir_luego(self, archivo, ruta):
        """Sube la canción en segundo plano (una a la vez, sin frenar la música)."""
        if archivo in self._subidas or time.time() < self._apagada_hasta:
            return
        self._subidas.add(archivo)
        self._cola.put((archivo, str(ruta)))

    def _subir_en_orden(self):
        while True:
            archivo, ruta = self._cola.get()
            try:
                tam = os.path.getsize(ruta)
                if tam < 50_000 or tam > MAX_SUBIR:
                    continue
                d = self._direcciones(archivo)
                if not d:
                    continue
                t0 = time.time()
                with open(ruta, "rb") as f:
                    r = requests.put(d["put"], data=f, timeout=(8, 600),
                                     headers={"content-type": "video/mp4",
                                              "content-length": str(tam)})
                if r.ok:
                    ya = (r.json() or {}).get("ya") if r.headers.get("content-type", "").startswith(
                        "application/json") else False
                    if not ya:
                        print(f"☁️ {archivo}: subida a la nube ({tam / 1048576:.1f} MB, "
                              f"{time.time() - t0:.0f} s)")
                else:
                    print(f"ℹ️ Nube: no se pudo subir {archivo} ({r.status_code})")
            except Exception as ex:
                print(f"ℹ️ Nube: no se pudo subir {archivo}: {str(ex)[:100]}")


def limpiar_por_tamano(carpeta, max_bytes, extensiones=(".mp4", ".webm", ".mkv", ".m4v"),
                       reciente_seg=30 * 60):
    """Con la nube activa: si las canciones guardadas pasan de `max_bytes`, se borran las que
    hace más tiempo no suenan (nunca lo de los últimos 30 min). Devuelve cuántas borró."""
    ahora = time.time()
    archivos = []
    try:
        for p in Path(carpeta).iterdir():
            if p.is_file() and p.suffix.lower() in extensiones:
                st = p.stat()
                archivos.append((st.st_mtime, st.st_size, p))
    except OSError:
        return 0
    total = sum(a[1] for a in archivos)
    if total <= max_bytes:
        return 0
    borradas = 0
    for mtime, tam, p in sorted(archivos):
        if total <= max_bytes * 0.85:  # se deja un margen para no borrar a cada rato
            break
        if ahora - mtime < reciente_seg:
            continue
        try:
            p.unlink()
            total -= tam
            borradas += 1
        except OSError:
            pass
    if borradas:
        print(f"🧹 Nube activa: se borraron {borradas} canciones viejas del equipo "
              f"(quedan {total / 1024 ** 3:.1f} GB); si las piden, se bajan de la nube")
    return borradas
