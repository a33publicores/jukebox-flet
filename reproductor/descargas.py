"""
Descarga de canciones con yt-dlp a una carpeta del PC (caché).

Una canción se descarga UNA vez; las repeticiones salen del disco y no tocan
YouTube. Las canciones siguientes en cola se precargan mientras suena la actual.
No usa la API ni los tokens de YouTube (esos quedan solo para buscar).
"""
import os
import shutil
from pathlib import Path

_EXT_TEMP = (".part", ".ytdl", ".temp", ".tmp")


class Descargador:
    def __init__(self, carpeta, cookies=None, max_gb=5.0, altura_max=720):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.cookies = cookies if cookies and os.path.exists(cookies) else None
        self.max_bytes = int(max_gb * 1024 ** 3)
        self.altura = altura_max

    # -- caché ---------------------------------------------------------
    def ruta(self, video_id):
        """Ruta del archivo ya descargado, o None."""
        for p in self.carpeta.glob(f"{video_id}.*"):
            if p.suffix.lower() not in _EXT_TEMP and p.stat().st_size > 50_000:
                return str(p)
        return None

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
        """Descarga (si hace falta) y devuelve la ruta del archivo. Bloqueante."""
        ya = self.ruta(video_id)
        if ya:
            os.utime(ya, None)
            return ya

        import yt_dlp

        h = self.altura
        ffmpeg = self._ffmpeg()
        if ffmpeg is False:
            formato = f"b[height<={h}][ext=mp4]/b[ext=mp4]/b"
        else:
            formato = (
                f"bv*[height<={h}][vcodec^=avc1]+ba[acodec^=mp4a]/"
                f"b[height<={h}][ext=mp4]/b[height<={h}]/b"
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

