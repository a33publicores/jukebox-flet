"""
Volumen parejo entre canciones.

Unas canciones vienen mucho más duras que otras. El servidor mide UNA vez qué tan duro se oye
cada canción que está en la nube (volumen percibido, EBU R128 / LUFS: la medida que usan
Spotify y YouTube) y guarda cuánto hay que bajarla para que suene como las demás. Los
reproductores (PC, TV y navegador) aplican ese factor al volumen de la canción.

Solo se BAJAN las canciones duras (un reproductor no puede pasar del 100%): las demás quedan
igual. Si una canción todavía no está medida, suena como siempre (factor 1).

La medición corre en la API (hilo aparte, una canción a la vez) con el ffmpeg de imageio-ffmpeg.
"""
import os
import re
import subprocess
import tempfile
import threading
import time

from services import db

OBJETIVO_LUFS = -14.0  # nivel al que se llevan las canciones duras (el de YouTube)
MINIMO = 0.35          # nunca se baja más de esto (por si una medición sale rara)
CADA_SEG = 15          # una medición cada 15 s como mucho (no cargar el servidor)
REINTENTAR_SEG = 6 * 3600
_iniciado = {"v": False}


def factor(lufs):
    """De LUFS a cuánto multiplicar el volumen (1 = igual; 0.5 = la mitad)."""
    if lufs is None:
        return 1.0
    return round(max(MINIMO, min(1.0, 10 ** ((OBJETIVO_LUFS - float(lufs)) / 20))), 3)


def factores(ids):
    """{video_id: factor} de las canciones ya medidas (las que no están, no vienen)."""
    ids = [str(i) for i in ids if i][:60]
    if not ids:
        return {}
    filas = db.consultar("SELECT video_id, lufs FROM volumenes WHERE video_id = ANY(%s) AND lufs IS NOT NULL",
                         (ids,))
    return {f["video_id"]: factor(f["lufs"]) for f in filas}


def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def medir_archivo(ruta):
    """LUFS integrado del audio del archivo (o None si no se pudo)."""
    r = subprocess.run([_ffmpeg(), "-hide_banner", "-nostats", "-i", str(ruta), "-vn",
                        "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=300)
    encontrados = re.findall(r"I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", r.stderr or "")
    return float(encontrados[-1]) if encontrados else None


def medir(video_id):
    """Baja la canción de la nube, la mide y guarda el resultado. True si quedó medida."""
    import requests
    from services import nube
    archivo = nube.buscar(video_id)
    if not archivo:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        ruta = os.path.join(tmp, "c.mp4")
        with requests.get(nube.direccion("GET", archivo), stream=True, timeout=(10, 120)) as r:
            r.raise_for_status()
            with open(ruta, "wb") as f:
                for trozo in r.iter_content(512 * 1024):
                    f.write(trozo)
        lufs = medir_archivo(ruta)
    db.ejecutar("""INSERT INTO volumenes (video_id, lufs, medido) VALUES (%s, %s, %s)
                   ON CONFLICT (video_id) DO UPDATE SET lufs = EXCLUDED.lufs, medido = EXCLUDED.medido""",
                (video_id, lufs, time.time()))
    if lufs is not None:
        print(f"🔊 Volumen {video_id}: {lufs:.1f} LUFS → x{factor(lufs)}")
    return lufs is not None


def _pendiente():
    """La canción pedida más reciente que todavía no está medida (y no se intentó hace poco)."""
    f = db.uno("""SELECT p.video_id FROM pedidos p
                  LEFT JOIN volumenes v ON v.video_id = p.video_id
                  WHERE p.ts > %s AND p.video_id <> ''
                    AND (v.video_id IS NULL OR (v.lufs IS NULL AND v.medido < %s))
                  GROUP BY p.video_id ORDER BY MAX(p.ts) DESC LIMIT 1""",
               (time.time() - 90 * 86400, time.time() - REINTENTAR_SEG))
    if not f:  # después, las del catálogo (diciembre...) que ya hayan subido a la nube
        f = db.uno("""SELECT c.video_id FROM catalogo c
                      LEFT JOIN volumenes v ON v.video_id = c.video_id
                      WHERE v.video_id IS NULL OR (v.lufs IS NULL AND v.medido < %s)
                      LIMIT 1""", (time.time() - REINTENTAR_SEG,))
    return f["video_id"] if f else None


def _marcar_intento(video_id):
    db.ejecutar("""INSERT INTO volumenes (video_id, lufs, medido) VALUES (%s, NULL, %s)
                   ON CONFLICT (video_id) DO UPDATE SET medido = EXCLUDED.medido""",
                (video_id, time.time()))


def _bucle():
    from services import nube
    time.sleep(20)
    while True:
        try:
            if nube.activa():
                vid = _pendiente()
                if vid:
                    try:
                        if not medir(vid):
                            _marcar_intento(vid)  # no está en la nube todavía: se reintenta luego
                    except Exception as ex:
                        print(f"⚠️ Volumen {vid}: {type(ex).__name__}: {ex}")
                        _marcar_intento(vid)
        except Exception as ex:
            print(f"⚠️ Volumen: {ex}")
        time.sleep(CADA_SEG)


def iniciar():
    if _iniciado["v"] or os.getenv("VOLUMEN_PAREJO", "1") == "0":
        return
    _iniciado["v"] = True
    threading.Thread(target=_bucle, daemon=True, name="volumen-parejo").start()
