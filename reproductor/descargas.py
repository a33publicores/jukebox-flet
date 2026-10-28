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

LIBRE_AVISO = 3 * 1024 ** 3      # por debajo de esto el reproductor avisa "queda poco espacio"
LIBRE_CRITICO = 400 * 1024 ** 2  # por debajo de esto no se intenta descargar (sin borrar nada)


class DiscoLleno(RuntimeError):
    """El disco del PC no tiene espacio: NO es culpa del video (no se busca otro ni se
    marca como dañado)."""


def es_disco_lleno(ex):
    t = str(ex)
    return isinstance(ex, DiscoLleno) or "No space left" in t or "Errno 28" in t \
        or "espacio en disco" in t.lower()


# --- yt-dlp al día (YouTube cambia seguido y la versión vieja da "403 Forbidden") ------
YTDLP_ZIP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
YTDLP_CADA_DIAS = 2


def activar_ytdlp_actualizado(carpeta):
    """Si hay un yt-dlp más nuevo descargado en PlayBarGo, se usa ese (antes de importarlo)."""
    zip_ = Path(carpeta) / "yt-dlp.zip"
    siguiente = Path(carpeta) / "yt-dlp.siguiente.zip"
    if siguiente.is_file() and str(zip_) not in sys.path:
        try:  # la que se bajó mientras el reproductor estaba abierto: se activa al arrancar
            os.replace(siguiente, zip_)
        except OSError as ex:
            print(f"ℹ️ No se pudo activar el yt-dlp nuevo: {ex}")
    if zip_.is_file() and str(zip_) not in sys.path:
        sys.path.insert(0, str(zip_))


def actualizar_ytdlp(carpeta):
    """Baja la última versión de yt-dlp (un solo archivo) y la deja lista para el próximo
    arranque. Se valida antes de reemplazar la anterior. Nunca lanza errores."""
    import zipfile
    zip_ = Path(carpeta) / "yt-dlp.zip"
    try:
        siguiente = Path(carpeta) / "yt-dlp.siguiente.zip"
        if siguiente.is_file() or (
                zip_.is_file() and time.time() - zip_.stat().st_mtime < YTDLP_CADA_DIAS * 86400):
            return
        import requests
        nuevo = zip_.with_suffix(".nuevo")
        with requests.get(YTDLP_ZIP_URL, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(nuevo, "wb") as f:
                for trozo in r.iter_content(256 * 1024):
                    f.write(trozo)
        with zipfile.ZipFile(nuevo) as z:  # el archivo trae un zip con el paquete yt_dlp
            if "yt_dlp/__init__.py" not in z.namelist():
                raise ValueError("no es yt-dlp")
        # El que está en uso NO se toca (si cambia mientras el reproductor lo usa, todas las
        # descargas fallan con "bad local file header" hasta reiniciar): queda esperando.
        os.replace(nuevo, siguiente if str(zip_) in sys.path else zip_)
        print("⬆️ yt-dlp actualizado (se usa desde el próximo arranque)")
    except Exception as ex:
        print(f"ℹ️ No se pudo actualizar yt-dlp: {ex}")


ALT_VENCE_SEG = 7 * 86400


def _bono_duracion(dur, ref):
    """Puntos extra (o menos) según la duración de un video que reemplaza a otro."""
    if ref and dur:
        return 0.3 if abs(dur - ref) <= max(20, ref * 0.15) else -0.5  # misma versión
    if dur:
        return 0.15 if dur >= 150 else -0.4  # menos de 2:30: casi siempre recortada
    return 0.0


class Descargador:
    def __init__(self, carpeta, cookies=None, max_gb=5.0, altura_max=720):
        self.carpeta = Path(carpeta)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        self.cookies = cookies if cookies and os.path.exists(cookies) else None
        self.max_bytes = int(max_gb * 1024 ** 3)
        self.altura = altura_max
        self.nube = None  # nube_cliente.Nube (la pone la app); None = sin nube
        self.max_nube_bytes = 8 * 1024 ** 3  # con nube: el PC guarda solo ~8 GB de canciones
        self._archivo_revisadas = self.carpeta / "revisadas.json"
        self._lock_rev = threading.Lock()
        self._revisados = self._leer_revisadas()  # nombre -> tamaño de canciones comprobadas
        # video que no sirve -> otro video de la MISMA canción que sí se pudo bajar
        self._archivo_alt = self.carpeta / "alternativas.json"
        try:
            self._alt = json.loads(self._archivo_alt.read_text("utf-8"))
        except Exception:
            self._alt = {}
        # cuándo se escogió cada reemplazo: pasados ALT_VENCE_SEG se vuelve a probar el original
        # (un error de YouTube puede ser pasajero y el reemplazo puede ser una versión corta)
        self._archivo_alt_fecha = self.carpeta / "alternativas_fechas.json"
        try:
            self._alt_fecha = json.loads(self._archivo_alt_fecha.read_text("utf-8"))
        except Exception:
            self._alt_fecha = {}
        threading.Thread(target=self.revisar_cache, daemon=True).start()

    # -- caché ---------------------------------------------------------
    def ruta(self, video_id):
        """Ruta de la canción ya descargada y COMPLETA (video + audio unidos), o None.
        Si ese video no servía y se usó otro de la misma canción, devuelve el otro."""
        directa = self._ruta_directa(video_id)
        if directa is None and video_id in self._alt and self._alias_vigente(video_id):
            return self._ruta_directa(self._alt[video_id])
        return directa

    def _alias_vigente(self, video_id):
        return time.time() - float(self._alt_fecha.get(video_id) or 0) < ALT_VENCE_SEG

    def _guardar_alias(self, video_id, alt):
        self._alt[video_id] = alt
        self._alt_fecha[video_id] = time.time()
        try:
            self._archivo_alt.write_text(json.dumps(self._alt), "utf-8")
            self._archivo_alt_fecha.write_text(json.dumps(self._alt_fecha), "utf-8")
        except Exception:
            pass

    def _ruta_directa(self, video_id):
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

    def espacio_libre(self):
        try:
            return shutil.disk_usage(self.carpeta).free
        except Exception:
            return 10 ** 12

    def asegurar_espacio(self, conservar=()):
        """Antes de descargar. Las canciones guardadas NUNCA se borran (la biblioteca del bar
        solo crece). Solo se borran pedazos de descargas que quedaron a medias. Si el disco
        está casi lleno se avisa (DiscoLleno) para que alguien libere espacio."""
        try:
            self.limpiar(conservar)  # con la nube activa: tope de espacio en el PC
        except Exception as ex:
            print("ℹ️ limpiar:", ex)
        if self.espacio_libre() >= LIBRE_CRITICO:
            return
        for p in list(self.carpeta.iterdir()):  # pedazos (ID.f136.mp4.part…), no canciones
            if p.is_file() and ("." in p.stem or p.suffix.lower() in _EXT_TEMP):
                try:
                    p.unlink()
                except OSError:
                    pass
        libre = self.espacio_libre()
        if libre < LIBRE_CRITICO:
            raise DiscoLleno(f"El disco del computador está lleno (quedan {libre / 1048576:.0f} MB). "
                             "Libera espacio en el disco C: para que las canciones puedan descargarse.")

    def limpiar(self, conservar=()):
        """Sin nube no borra canciones (la biblioteca del bar se conserva completa). Con la
        nube activa el PC guarda solo las recientes: lo demás se baja de la nube."""
        if self.nube is not None and not getattr(self.nube, "_apagada_hasta", 0) > time.time():
            from reproductor.nube_cliente import limpiar_por_tamano
            limpiar_por_tamano(self.carpeta, self.max_nube_bytes)

    # -- descarga ------------------------------------------------------
    def _ffmpeg(self):
        if shutil.which("ffmpeg"):
            return None  # yt-dlp lo encuentra solo
        try:
            import imageio_ffmpeg

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return False  # sin ffmpeg: solo formatos ya combinados

    def obtener(self, video_id, titulo=None, canal=None):
        """Descarga (si hace falta) y devuelve la ruta del archivo. Bloqueante.
        Si ese video no se puede usar (bloqueado, borrado, sin sonido...) y se conoce el
        nombre, busca en YouTube la MISMA canción (nombre y artista) y usa otro video."""
        if not self._ruta_directa(video_id):
            self.asegurar_espacio(conservar=(video_id,))
        try:
            return self._obtener_directo(video_id)
        except Exception as ex:
            if es_disco_lleno(ex):
                raise DiscoLleno(str(ex)) from ex
            if not titulo or "not a bot" in str(ex).lower():
                raise  # YouTube bloqueó la conexión: otros videos tampoco van a bajar
            print(f"⚠️ El video {video_id} no sirve ({str(ex)[:120]}): busco otro de «{titulo}»")
            error = ex
        previo = self._alt.get(video_id)
        candidatos = self.alternativas(titulo, canal, excluir={video_id})
        if previo and previo not in candidatos:
            candidatos.append(previo)  # el de antes, solo si no hay uno mejor
        for alt in candidatos[:4]:
            try:
                ruta = self._obtener_directo(alt)
            except Exception as ex:
                if es_disco_lleno(ex):
                    raise DiscoLleno(str(ex)) from ex
                print(f"   ✗ {alt} tampoco sirve: {str(ex)[:80]}")
                continue
            self._guardar_alias(video_id, alt)
            print(f"   ✓ Uso {alt} en lugar de {video_id}")
            return ruta
        raise RuntimeError(f"Ningún video de «{titulo}» se pudo usar ({str(error)[:100]})")

    @staticmethod
    def _palabras(texto):
        import unicodedata
        texto = re.sub(r"[\(\[].*?[\)\]]", " ", str(texto or "").lower())  # (Video Oficial)…
        texto = "".join(c for c in unicodedata.normalize("NFD", texto)
                        if unicodedata.category(c) != "Mn")  # ilusioné = ilusione
        ruido = {"video", "oficial", "official", "lyric", "lyrics", "letra", "audio", "hd",
                 "en", "vivo", "live", "ft", "feat", "the", "de", "la", "el", "los", "las", "y"}
        return {w for w in re.findall(r"[a-z0-9]+", texto) if len(w) > 1 and w not in ruido}

    def alternativas(self, titulo, canal=None, excluir=(), maximo=6):
        """Otros videos de la misma canción, del más parecido al menos. Sin usar la API de
        YouTube (yt-dlp hace la búsqueda). Descarta lo que no se parece o dura demasiado."""
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
        entradas = [e for e in (datos or {}).get("entries") or [] if e and e.get("id")]
        # el video original suele salir en la búsqueda: su duración dice cuánto debe durar
        ref = next((e.get("duration") for e in entradas if e["id"] in excluir and e.get("duration")), 0)
        for e in entradas:
            vid = e.get("id")
            if not vid or vid in excluir:
                continue
            dur = e.get("duration") or 0
            if dur and (dur < 60 or dur > 15 * 60):  # ni cortos ni mezclas de una hora
                continue
            if e.get("live_status") in ("is_live", "is_upcoming"):
                continue
            tiene = self._palabras(e.get("title"))
            parecido = len(buscadas & tiene) / max(1, len(buscadas))
            if parecido >= 0.6:  # que de verdad sea la misma canción
                puntajes.append((parecido + _bono_duracion(dur, ref), vid))
        puntajes.sort(key=lambda x: -x[0])
        return [vid for _, vid in puntajes[:maximo]]

    def _obtener_directo(self, video_id):
        ya = self._ruta_directa(video_id)
        if ya:
            if self.tiene_audio(ya):
                os.utime(ya, None)
                return ya
            print(f"🔁 {video_id} estaba dañada: se vuelve a descargar")
            self._borrar(video_id)
        if self.nube is not None:  # ¿otro bar ya la subió a la nube?
            destino = self.carpeta / f"{video_id}.mp4"
            if self.nube.bajar(self._archivo_nube(video_id), destino):
                if self.tiene_audio(str(destino)):
                    return str(destino)
                self._borrar(video_id)
        ruta = self._a_nube(video_id, self._bajar_sano(video_id))
        return ruta

    def _archivo_nube(self, video_id):
        return f"{video_id}_{self.altura}.mp4"

    def _a_nube(self, video_id, ruta):
        if self.nube is not None and ruta:
            self.nube.subir_luego(self._archivo_nube(video_id), ruta)
        return ruta

    def _bajar_sano(self, video_id):
        ruta = self._bajar(video_id, combinado=False)
        if not self.tiene_audio(ruta):
            print(f"🔁 {video_id} bajó dañada: pruebo con el formato ya combinado")
            self._borrar(video_id)
            ruta = self._bajar(video_id, combinado=True)
            if not self.tiene_audio(ruta):
                self._borrar(video_id)
                raise RuntimeError(f"{video_id} viene dañada desde YouTube")
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

        ruta = self._ruta_directa(video_id)
        if not ruta:
            raise RuntimeError(f"No se pudo descargar {video_id}")
        return ruta

