"""
Descarga de canciones para el TV (yt-dlp SIN ffmpeg).

YouTube ya casi no entrega archivos con video y audio juntos. En el PC ffmpeg los une;
en Android no hay ffmpeg. Por eso aquí se bajan video (h264) y audio (m4a) por separado y
se unen en un solo .mp4 con unir_mp4.py (Python puro, sin recodificar: es rápido).

Igual que en el PC: cada canción se baja UNA vez y queda guardada; nunca se borran
canciones, solo pedazos de descargas cortadas. Si un video no sirve se busca otro de
la misma canción.
"""
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

_EXT_TEMP = (".part", ".ytdl", ".temp", ".tmp")
_EXT_VIDEO = (".mp4", ".webm", ".mkv", ".m4v", ".mov", ".ts")
LIVIANA = 480  # calidad para TV básicos (menos de 2 GB de RAM) o videos que fallaron

# Un TV o TV Box tiene poca memoria (8-16 GB): los avisos son más bajos que en el PC.
LIBRE_AVISO = 1 * 1024 ** 3      # menos de 1 GB: "queda poco espacio"
LIBRE_CRITICO = 300 * 1024 ** 2  # menos de 300 MB: no se descarga (sin borrar nada)


class DiscoLleno(RuntimeError):
    """La memoria del TV está llena: NO es culpa del video."""


def es_disco_lleno(ex):
    t = str(ex)
    return isinstance(ex, DiscoLleno) or "No space left" in t or "Errno 28" in t


# --- yt-dlp al día (YouTube cambia seguido y la versión vieja da "403 Forbidden") ------
YTDLP_ZIP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
YTDLP_CADA_DIAS = 2


def activar_ytdlp_actualizado(carpeta):
    """Si hay un yt-dlp más nuevo descargado, se usa ese (antes de importarlo)."""
    zip_ = Path(carpeta) / "yt-dlp.zip"
    if zip_.is_file() and str(zip_) not in sys.path:
        sys.path.insert(0, str(zip_))


def actualizar_ytdlp(carpeta):
    """Baja la última versión de yt-dlp y la deja lista para el próximo arranque.
    Así el TV no depende de que se publique un .apk nuevo cada vez que YouTube cambia."""
    import zipfile
    zip_ = Path(carpeta) / "yt-dlp.zip"
    try:
        if zip_.is_file() and time.time() - zip_.stat().st_mtime < YTDLP_CADA_DIAS * 86400:
            return
        import requests
        Path(carpeta).mkdir(parents=True, exist_ok=True)
        nuevo = zip_.with_suffix(".nuevo")
        with requests.get(YTDLP_ZIP_URL, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(nuevo, "wb") as f:
                for trozo in r.iter_content(256 * 1024):
                    f.write(trozo)
        with zipfile.ZipFile(nuevo) as z:
            if "yt_dlp/__init__.py" not in z.namelist():
                raise ValueError("no es yt-dlp")
        os.replace(nuevo, zip_)
        print("⬆️ yt-dlp actualizado (se usa desde el próximo arranque)")
    except Exception as ex:
        print(f"ℹ️ No se pudo actualizar yt-dlp: {ex}")


class Descargador:
    def __init__(self, carpeta, cookies=None, altura_max=720):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.cookies = cookies if cookies and os.path.exists(cookies) else None
        self.altura = altura_max
        self.livianos = set()  # videos que el TV no pudo reproducir: se vuelven a bajar en 480p
        self._archivo_alt = self.carpeta / "alternativas.json"
        try:
            self._alt = json.loads(self._archivo_alt.read_text("utf-8"))
        except Exception:
            self._alt = {}
        self._lock = threading.Lock()
        threading.Thread(target=self.revisar_cache, daemon=True).start()

    def reintentar_liviano(self, video_id):
        """El TV no pudo reproducir este video: se borra y la próxima vez se baja en 480p
        (más liviano para TV básicos). False si ya se intentó así (entonces se salta)."""
        if video_id in self.livianos:
            return False
        self.livianos.add(video_id)
        for vid in {video_id, self._alt.get(video_id, video_id)}:
            for p in list(self.carpeta.glob(f"{vid}.*")) + list(self.carpeta.glob(f"{vid}_*")):
                try:
                    p.unlink()
                except OSError:
                    pass
        print(f"↩️ {video_id}: se vuelve a bajar en {min(self.altura, LIVIANA)}p")
        return True

    # -- caché ---------------------------------------------------------
    def ruta(self, video_id):
        directa = self._ruta_directa(video_id)
        if directa is None and video_id in self._alt:
            return self._ruta_directa(self._alt[video_id])
        return directa

    def _ruta_directa(self, video_id):
        for ext in _EXT_VIDEO:
            p = self.carpeta / f"{video_id}{ext}"
            try:
                if p.stat().st_size > 50_000:
                    return str(p)
            except OSError:
                pass
        return None

    def _partes(self, video_id):
        """(video, audio) ya bajados por separado, o None."""
        def una(sufijo):
            for p in self.carpeta.glob(f"{video_id}_{sufijo}.*"):
                try:
                    if p.suffix.lower() not in _EXT_TEMP and p.stat().st_size > 20_000:
                        return p
                except OSError:
                    pass
            return None
        v, a = una("v"), una("a")
        if not (v and a):  # partes con el nombre de yt-dlp (ID.f136.mp4 + ID.f140.m4a)
            vids = [p for p in self.carpeta.glob(f"{video_id}.f*.mp4")]
            auds = [p for p in self.carpeta.glob(f"{video_id}.f*.m4a")]
            if vids and auds:
                v, a = vids[0], auds[0]
        return (v, a) if v and a else None

    def revisar_cache(self):
        """Al abrir: borra pedazos viejos de descargas que quedaron a medias."""
        ahora = time.time()
        try:
            archivos = list(self.carpeta.iterdir())
        except OSError:
            return
        for p in archivos:
            try:
                if p.is_file() and ("." in p.stem or p.suffix.lower() in _EXT_TEMP) \
                        and p.suffix.lower() != ".json" and ahora - p.stat().st_mtime > 1800:
                    p.unlink()
                    print(f"🧹 Pedazo de descarga incompleta borrado: {p.name}")
            except OSError:
                pass

    def espacio_libre(self):
        try:
            return shutil.disk_usage(self.carpeta).free
        except Exception:
            return 10 ** 12

    def asegurar_espacio(self):
        if self.espacio_libre() >= LIBRE_CRITICO:
            return
        for p in list(self.carpeta.iterdir()):
            if p.is_file() and p.suffix.lower() != ".json" and (
                    "." in p.stem or p.suffix.lower() in _EXT_TEMP):
                try:
                    p.unlink()
                except OSError:
                    pass
        libre = self.espacio_libre()
        if libre < LIBRE_CRITICO:
            raise DiscoLleno(f"La memoria del TV está llena (quedan {libre / 1048576:.0f} MB).")

    # -- descarga ------------------------------------------------------
    def obtener(self, video_id, titulo=None, canal=None):
        """Descarga (si hace falta) y devuelve la ruta. Bloqueante. Si el video no sirve
        y se conoce el nombre, busca otro video de la MISMA canción."""
        ya = self._ruta_directa(video_id)
        if ya:
            try:
                os.utime(ya, None)
            except OSError:
                pass
            return ya
        self.asegurar_espacio()
        try:
            if self._partes(video_id):  # quedaron video y audio de antes: solo se unen
                return self._unir(video_id, *self._partes(video_id))
            return self._bajar(video_id)
        except Exception as ex:
            if es_disco_lleno(ex):
                raise DiscoLleno(str(ex)) from ex
            if not titulo:
                raise
            print(f"⚠️ El video {video_id} no sirve ({str(ex)[:120]}): busco otro de «{titulo}»")
            error = ex
        previo = self._alt.get(video_id)
        candidatos = ([previo] if previo else []) + [
            c for c in self.alternativas(titulo, canal, excluir={video_id}) if c != previo]
        for alt in candidatos[:4]:
            try:
                ruta = self._ruta_directa(alt) or self._bajar(alt)
            except Exception as ex:
                if es_disco_lleno(ex):
                    raise DiscoLleno(str(ex)) from ex
                print(f"   ✗ {alt} tampoco sirve: {str(ex)[:80]}")
                continue
            with self._lock:
                self._alt[video_id] = alt
                try:
                    self._archivo_alt.write_text(json.dumps(self._alt), "utf-8")
                except Exception:
                    pass
            print(f"   ✓ Uso {alt} en lugar de {video_id}")
            return ruta
        raise RuntimeError(f"Ningún video de «{titulo}» se pudo usar ({str(error)[:100]})")

    @staticmethod
    def _palabras(texto):
        import unicodedata
        texto = re.sub(r"[\(\[].*?[\)\]]", " ", str(texto or "").lower())
        texto = "".join(c for c in unicodedata.normalize("NFD", texto)
                        if unicodedata.category(c) != "Mn")
        ruido = {"video", "oficial", "official", "lyric", "lyrics", "letra", "audio", "hd",
                 "en", "vivo", "live", "ft", "feat", "the", "de", "la", "el", "los", "las", "y"}
        return {w for w in re.findall(r"[a-z0-9]+", texto) if len(w) > 1 and w not in ruido}

    def alternativas(self, titulo, canal=None, excluir=(), maximo=6):
        import yt_dlp

        canal_txt = "" if not canal or re.search(r"(?i)vevo|topic|records|music", canal) else canal
        consulta = f"{titulo} {canal_txt}".strip()
        opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
                "skip_download": True, "socket_timeout": 20}
        if self.cookies:
            opts["cookiefile"] = self.cookies
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                datos = ydl.extract_info(f"ytsearch{maximo + 4}:{consulta}", download=False)
        except Exception as ex:
            print(f"⚠️ No se pudo buscar otro video: {ex}")
            return []
        buscadas = self._palabras(titulo)
        puntajes = []
        for e in (datos or {}).get("entries") or []:
            vid = (e or {}).get("id")
            if not vid or vid in excluir:
                continue
            dur = e.get("duration") or 0
            if dur and (dur < 60 or dur > 15 * 60):
                continue
            if e.get("live_status") in ("is_live", "is_upcoming"):
                continue
            parecido = len(buscadas & self._palabras(e.get("title"))) / max(1, len(buscadas))
            if parecido >= 0.6:
                puntajes.append((parecido, vid))
        puntajes.sort(key=lambda x: -x[0])
        return [vid for _, vid in puntajes[:maximo]]

    def _bajar(self, video_id):
        """Consulta y descarga en UNA sola llamada a yt-dlp (igual que el reproductor del
        PC; si se separan, YouTube responde 403). Sin ffmpeg, yt-dlp deja el video y el
        audio como dos archivos (ID.f136.mp4 + ID.f140.m4a) en vez de unirlos."""
        import yt_dlp

        h = min(self.altura, LIVIANA) if video_id in self.livianos else self.altura
        opts = {
            # 1º video h264 + audio m4a (lo que mejor decodifica un TV), luego cualquiera,
            # y si YouTube diera un archivo con todo junto, ese.
            # Solo MP4 + M4A: es lo que unir_mp4 sabe juntar sin ffmpeg.
            "format": (f"bv*[height<={h}][vcodec^=avc1]+ba[ext=m4a]/"
                       f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/"
                       f"b[height<={h}][acodec!=none]/b[acodec!=none]"),
            "outtmpl": str(self.carpeta / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            # Sin esto, al no haber ffmpeg yt-dlp se niega a bajar video y audio aparte.
            # Los errores se siguen viendo en el registro; aquí se revisan los archivos.
            "ignoreerrors": True,
            "retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 20,
            "concurrent_fragment_downloads": 4,
            "overwrites": False,
            "fixup": "never",
        }
        if self.cookies:
            opts["cookiefile"] = self.cookies
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=True)

        ruta = self._ruta_directa(video_id)
        if ruta:  # ffmpeg presente (PC) o archivo con todo junto
            return ruta
        # yt-dlp los deja como ID.f<formato>.<ext>, en el orden pedido: video y luego audio
        pedidos = (info or {}).get("requested_formats") or []
        archivos = [self.carpeta / f"{video_id}.f{f.get('format_id')}.{f.get('ext')}" for f in pedidos]
        if len(archivos) != 2 or not all(a.is_file() and a.stat().st_size > 20_000 for a in archivos):
            raise RuntimeError(f"YouTube no dejó descargar {video_id} (mira el error de arriba)")
        return self._unir(video_id, *archivos)

    def _unir(self, video_id, video, audio):
        """Une video y audio en ID.mp4 (Python puro) y borra las partes."""
        from tv.unir_mp4 import unir
        destino = self.carpeta / f"{video_id}.mp4"
        t = time.time()
        unir(video, audio, destino)
        for p in (video, audio, self.carpeta / f"{video_id}.edl"):
            try:
                Path(p).unlink()
            except OSError:
                pass
        print(f"⬇️ {video_id}: video + audio unidos en {destino.name} "
              f"({destino.stat().st_size / 1048576:.1f} MB, {time.time() - t:.1f} s)")
        return str(destino)
