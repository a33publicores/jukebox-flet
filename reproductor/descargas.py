"""
Descarga de canciones con yt-dlp a una carpeta del PC (caché).

Una canción se descarga UNA vez; las repeticiones salen del disco y no tocan
YouTube. Las canciones siguientes en cola se precargan mientras suena la actual.
No usa la API ni los tokens de YouTube (esos quedan solo para buscar).
"""
import json
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
        self._archivo_revisadas = self.carpeta / "revisadas.json"
        self._lock_rev = threading.Lock()
        self._revisados = self._leer_revisadas()  # nombre -> tamaño de canciones comprobadas
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
    def archivo_sano(self, ruta):
        """True si la canción trae VIDEO y AUDIO y se puede reproducir hasta el final
        (no quedó cortada). Cada archivo se revisa una sola vez (queda anotado en
        revisadas.json). Si no hay ffmpeg para revisar, se da por buena."""
        ruta = str(ruta)
        nombre = os.path.basename(ruta)
        try:
            tam = os.stat(ruta).st_size
        except OSError:
            return False
        if self._revisados.get(nombre) == tam:
            return True
        ffmpeg = self._ffmpeg() or shutil.which("ffmpeg")
        if not ffmpeg:
            return True
        try:
            r = subprocess.run([ffmpeg, "-hide_banner", "-i", ruta], capture_output=True,
                               text=True, errors="ignore", timeout=30, creationflags=_SIN_VENTANA)
        except Exception as ex:
            print(f"ℹ️ No se pudo revisar {nombre}: {ex}")
            return True
        info = r.stderr or ""
        if "Stream #" not in info:
            if re.search(r"moov atom not found|Invalid data found|End of file", info):
                print(f"✂️ {nombre}: archivo incompleto o dañado")
                return False
            return True  # otro problema al leer: no se descarta por las dudas
        if not re.search(r"Stream #\S+.*: Video:", info):
            print(f"🎞️ {nombre}: no tiene video")
            return False
        if not re.search(r"Stream #\S+.*: Audio:", info):
            print(f"🔇 {nombre}: no tiene sonido")
            return False
        m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", info)
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0
        if dur > 10:  # que el final se pueda reproducir (archivo no cortado)
            try:
                r = subprocess.run([ffmpeg, "-hide_banner", "-ss", f"{dur - 5:.1f}", "-i", ruta,
                                    "-map", "0:v:0", "-t", "2", "-f", "null", "-"],
                                   capture_output=True, text=True, errors="ignore", timeout=60,
                                   creationflags=_SIN_VENTANA)
                cuadros = re.findall(r"frame=\s*(\d+)", r.stderr or "")
                if not cuadros or int(cuadros[-1]) == 0:
                    print(f"✂️ {nombre}: el archivo está cortado (no llega al final)")
                    return False
            except Exception as ex:
                print(f"ℹ️ No se pudo revisar el final de {nombre}: {ex}")
        self._anotar_revisada(nombre, tam)
        return True

    tiene_audio = archivo_sano  # nombre anterior

    def _leer_revisadas(self):
        try:
            return {k: int(v) for k, v in json.loads(self._archivo_revisadas.read_text("utf-8")).items()}
        except Exception:
            return {}

    def _anotar_revisada(self, nombre, tam):
        with self._lock_rev:
            self._revisados[nombre] = tam
            try:
                self._archivo_revisadas.write_text(json.dumps(self._revisados), "utf-8")
            except Exception:
                pass

    def revisar_cache(self):
        """Al abrir: borra pedazos viejos de descargas cortadas y las canciones dañadas
        (sin video, sin sonido o cortadas). Se vuelven a bajar bien cuando toque."""
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
                        and not self.archivo_sano(p):
                    p.unlink()
                    print(f"🗑️ Canción dañada borrada (se bajará de nuevo): {nombre}")
            except OSError as ex:
                print(f"ℹ️ No se pudo revisar {p.name}: {ex}")

    def limpiar(self, conservar=()):
        """Borra lo más antiguo si la caché supera el límite."""
        archivos = [p for p in self.carpeta.iterdir()
                    if p.is_file() and p.suffix.lower() in _EXT_VIDEO]
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
            print(f"🔁 {video_id} estaba dañada: se vuelve a descargar")
            self._borrar(video_id)
        ruta = self._bajar(video_id, combinado=False)
        if not self.tiene_audio(ruta):
            print(f"🔁 {video_id} bajó dañada: pruebo con el formato ya combinado")
            self._borrar(video_id)
            ruta = self._bajar(video_id, combinado=True)
            if not self.tiene_audio(ruta):
                self._borrar(video_id)
                raise RuntimeError(f"{video_id} viene dañada desde YouTube")
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
        with self._lock_rev:
            self._revisados = {k: v for k, v in self._revisados.items() if not k.startswith(video_id + ".")}

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

