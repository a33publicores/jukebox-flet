"""
Descarga de canciones con yt-dlp a una carpeta del PC (caché).

Una canción se descarga UNA vez; las repeticiones salen del disco y no tocan
YouTube. Las canciones siguientes en cola se precargan mientras suena la actual.
No usa la API ni los tokens de YouTube (esos quedan solo para buscar).
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

_EXT_TEMP = (".part", ".ytdl", ".temp", ".tmp")
_EXT_VIDEO = (".mp4", ".webm", ".mkv", ".m4v", ".mov")
# yt-dlp baja video y audio por separado (ID.f136.mp4 + ID.f140.m4a) y después los une en
# ID.mp4. Esos pedazos NO son la canción: el de video no tiene sonido.
_SIN_VENTANA = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW


class Descargador:
    def __init__(self, carpeta, cookies=None, max_gb=5.0, altura_max=720):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.cookies = cookies if cookies and os.path.exists(cookies) else None
        self.max_bytes = int(max_gb * 1024 ** 3)
        self.altura = altura_max
        self._revisados = {}   # ruta -> (tamaño, fecha) de archivos con audio comprobado
        threading.Thread(target=self.revisar_cache, daemon=True).start()

    # -- caché ---------------------------------------------------------
    def ruta(self, video_id):
        """Ruta de la canción ya descargada y COMPLETA (video + audio unidos), o None."""
        for ext in _EXT_VIDEO:
            p = self.carpeta / f"{video_id}{ext}"
            try:
                if p.stat().st_size > 50_000:
                    return str(p)
            except OSError:
                pass
        return None

    # -- sonido ----------------------------------------------------------
    def tiene_audio(self, ruta):
        """True si el archivo trae pista de sonido. Si no hay ffmpeg para revisar, True."""
        try:
            st = os.stat(ruta)
        except OSError:
            return False
        firma = (st.st_size, int(st.st_mtime))
        if self._revisados.get(str(ruta)) == firma:
            return True
        ffmpeg = self._ffmpeg() or shutil.which("ffmpeg")
        if not ffmpeg:
            return True
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-i", str(ruta)], capture_output=True,
                               text=True, errors="ignore", timeout=30, creationflags=_SIN_VENTANA)
        except Exception as ex:
            print(f"ℹ️ No se pudo revisar el sonido de {ruta}: {ex}")
            return True
        info = r.stderr or ""
        if "Stream #" not in info:
            return True  # no se pudo leer: no se descarta por las dudas
        ok = re.search(r"Stream #\S+.*: Audio:", info) is not None
        if ok:
            self._revisados[str(ruta)] = firma
        return ok

    def revisar_cache(self):
        """Al abrir: borra pedazos viejos de descargas cortadas y las canciones sin sonido
        (se vuelven a bajar bien cuando toque)."""
        ahora = time.time()
        try:
            archivos = list(self.carpeta.iterdir())
        except OSError:
            return
        for p in archivos:
            try:
                if not p.is_file():
                    continue
                nombre = p.name
                # Los IDs de YouTube no tienen punto: "ID.f136.mp4", "ID.temp.mp4",
                # "ID.mp4.part"... son pedazos o temporales, no canciones.
                if "." in p.stem or p.suffix.lower() in _EXT_TEMP:
                    if ahora - p.stat().st_mtime > 1800:  # más de 30 min: descarga muerta
                        p.unlink()
                        print(f"🧹 Pedazo de descarga incompleta borrado: {nombre}")
                    continue
                if p.suffix.lower() in _EXT_VIDEO and ahora - p.stat().st_mtime > 60 \
                        and not self.tiene_audio(p):
                    p.unlink()
                    print(f"🔇 Canción sin sonido borrada (se bajará de nuevo): {nombre}")
            except OSError as ex:
                print(f"ℹ️ No se pudo revisar {p.name}: {ex}")

    def limpiar(self, conservar=()):
        """Borra lo más antiguo si la caché supera el límite."""
        archivos = [p for p in self.carpeta.iterdir() if p.is_file()]
        total = sum(p.stat().st_size for p in archivos)
        if total <= self.max_bytes:
            return
        conservar = set(conservar)
        for p in sorted(archivos, key=lambda x: x.stat().st_mtime):
            if p.stem in conservar:
                continue
            total -= p.stat().st_size
            try:
                p.unlink()
            except OSError:
                pass
            if total <= self.max_bytes * 0.9:
                break

    # -- descarga ------------------------------------------------------
    def _ffmpeg(self):
        if shutil.which("ffmpeg"):
            return None  # yt-dlp lo encuentra solo
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return False  # sin ffmpeg: solo formatos ya combinados

    def obtener(self, video_id):
        """Descarga (si hace falta) y devuelve la ruta del archivo. Bloqueante.
        Siempre devuelve un archivo CON sonido (si no, lo vuelve a bajar)."""
        ya = self.ruta(video_id)
        if ya:
            if self.tiene_audio(ya):
                os.utime(ya, None)
                return ya
            print(f"🔇 {video_id} estaba sin sonido: se vuelve a descargar")
            self._borrar(video_id)
        ruta = self._bajar(video_id, combinado=False)
        if not self.tiene_audio(ruta):
            print(f"🔇 {video_id} bajó sin sonido: pruebo con el formato ya combinado")
            self._borrar(video_id)
            ruta = self._bajar(video_id, combinado=True)
            if not self.tiene_audio(ruta):
                self._borrar(video_id)
                raise RuntimeError(f"{video_id} no tiene sonido en YouTube")
        try:
            self.limpiar(conservar=(video_id,))
        except Exception:
            pass
        return ruta

    def _borrar(self, video_id):
        for p in self.carpeta.glob(f"{video_id}.*"):
            try:
                p.unlink()
            except OSError:
                pass
        self._revisados = {k: v for k, v in self._revisados.items() if video_id not in k}

    def _bajar(self, video_id, combinado=False):

        import yt_dlp

        h = self.altura
        ffmpeg = self._ffmpeg()
        if ffmpeg is False or combinado:
            # un solo archivo que ya trae video y audio juntos
            formato = (f"b[height<={h}][ext=mp4][acodec!=none]/b[ext=mp4][acodec!=none]/"
                       f"b[acodec!=none]/b")
        else:
            formato = (
                f"bv*[height<={h}][vcodec^=avc1]+ba[acodec^=mp4a]/"
                f"bv*[height<={h}]+ba/"
                f"b[height<={h}][ext=mp4][acodec!=none]/b[acodec!=none]/b"
            )
        opts = {
            "format": formato,
            "outtmpl": str(self.carpeta / "%(id)s.%(ext)s"),
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 20,
            "concurrent_fragment_downloads": 4,  # baja video y audio en paralelo (más rápido)
            "overwrites": False,
        }
        if ffmpeg:
            opts["ffmpeg_location"] = ffmpeg
        if self.cookies:
            opts["cookiefile"] = self.cookies

        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        ruta = self.ruta(video_id)
        if not ruta:
            raise RuntimeError(f"No se pudo descargar {video_id}")
        return ruta

