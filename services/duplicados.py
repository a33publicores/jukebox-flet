"""
Canciones repetidas en la nube.

Los clientes piden la misma canción desde videos distintos (el oficial, el de letra, el
"audio"...): cada uno se sube a la nube por separado. Aquí se reconocen por el nombre y se deja
UNA sola (la más pedida); las otras se borran de la nube y quedan anotadas en la tabla
`duplicadas` (video_id -> principal). Cuando alguien vuelve a pedir una repetida, la API
entrega el archivo de la principal (ver api/servidor.py), así no se vuelve a subir.

Para no juntar canciones distintas, la clave es estricta: mismas palabras del nombre (sin
"video oficial", "letra", "hd"...) y mismo artista; y las versiones en vivo, remix, acústica,
cover o karaoke cuentan como canciones aparte.
"""
import re
import time
import unicodedata

from services import db

REVISAR_CADA_SEG = 6 * 3600
_cache = {"mapa": None, "hasta": 0.0}

RELLENO = {
    "video", "videoclip", "clip", "oficial", "official", "audio", "lyric", "lyrics", "letra",
    "visualizer", "hd", "hq", "4k", "1080p", "720p", "remastered", "remasterizado", "remaster",
    "music", "musica", "official", "vevo", "topic", "con", "y", "and", "the", "el", "la", "los",
    "las", "de", "del", "ft", "feat", "featuring", "x", "vs", "prod", "estreno", "nuevo", "new",
    "su", "sus", "combo", "orquesta", "conjunto",
}
VERSIONES = {"vivo", "live", "remix", "acustico", "acoustic", "cover", "karaoke", "instrumental",
             "version", "sesion", "session", "unplugged", "mix", "edit", "extended", "bachata",
             "salsa", "cumbia", "tecno", "techno"}
SOBRA_CANAL = re.compile(r"(?i)\b(vevo|topic|oficial|official|music|musica|records|tv|channel|"
                         r"canal|producciones|entertainment)\b")


def _palabras(texto):
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.findall(r"[a-z0-9]+", t)


def clave(titulo, canal=""):
    """Clave de la canción, o None si el nombre es muy corto para decidir con seguridad."""
    titulo = re.split(r"\s\|\s", str(titulo or ""))[0]  # lo de después de " | " suele ser la disquera
    palabras = _palabras(titulo)
    if not palabras:
        return None
    version = sorted(set(palabras) & VERSIONES)
    nucleo = set(p for p in palabras if p not in RELLENO and p not in VERSIONES)
    # Si el nombre no trae el artista ("Artista - Canción"), se toma del canal (los de YouTube
    # Music se llaman "Artista - Topic"); si lo trae, el canal no cuenta (suele ser la disquera).
    if not re.search(r"\s[-–|]\s", str(titulo)):
        canal = re.sub(r"(?i)vevo$", "", SOBRA_CANAL.sub(" ", canal or "").strip())
        nucleo |= set(p for p in _palabras(canal) if p not in RELLENO)
    if len(nucleo) < 2:
        return None  # p. ej. "Amor" sin artista: demasiado corto, mejor no juntar
    return " ".join(sorted(nucleo)) + ("|" + ",".join(version) if version else "")


def mapa():
    """{video_id repetido: video_id principal} (en memoria un rato)."""
    if _cache["mapa"] is None or time.time() > _cache["hasta"]:
        try:
            _cache["mapa"] = {f["video_id"]: f["principal"]
                              for f in db.consultar("SELECT video_id, principal FROM duplicadas")}
        except Exception:
            _cache["mapa"] = _cache["mapa"] or {}
        _cache["hasta"] = time.time() + 120
    return _cache["mapa"]


def principal(video_id):
    return mapa().get(str(video_id or ""), str(video_id or ""))


def revisar(borrar_de_la_nube):
    """Busca canciones repetidas entre las que hay en la nube. `borrar_de_la_nube(video_id)`
    borra sus archivos (True si quedó borrada). Devuelve cuántas repetidas encontró."""
    filas = db.consultar("""
        SELECT n.video_id, COALESCE(p.titulo, c.titulo, '') AS titulo,
               COALESCE(p.canal, c.canal, '') AS canal, COALESCE(p.veces, 0) AS veces,
               SUM(n.bytes) AS bytes
        FROM nube_archivos n
        LEFT JOIN (SELECT video_id, MAX(titulo) AS titulo, MAX(canal) AS canal, COUNT(*) AS veces
                   FROM pedidos GROUP BY video_id) p ON p.video_id = n.video_id
        LEFT JOIN catalogo c ON c.video_id = n.video_id
        WHERE n.video_id NOT IN (SELECT video_id FROM duplicadas)
        GROUP BY n.video_id, p.titulo, c.titulo, p.canal, c.canal, p.veces""")
    grupos = {}
    for f in filas:
        k = clave(f["titulo"], f["canal"])
        if k:
            grupos.setdefault(k, []).append(f)
    repetidas = 0
    for k, lista in grupos.items():
        if len(lista) < 2:
            continue
        # se queda la más pedida (y, si empatan, la de archivo más grande: mejor calidad)
        lista.sort(key=lambda f: (int(f["veces"] or 0), int(f["bytes"] or 0)), reverse=True)
        queda = lista[0]
        for f in lista[1:]:
            db.ejecutar("""INSERT INTO duplicadas (video_id, principal, titulo, cuando)
                           VALUES (%s, %s, %s, %s) ON CONFLICT (video_id) DO NOTHING""",
                        (f["video_id"], queda["video_id"], str(f["titulo"])[:300], time.time()))
            db.ejecutar("UPDATE duplicadas SET principal = %s WHERE principal = %s",
                        (queda["video_id"], f["video_id"]))
            if borrar_de_la_nube(f["video_id"]):
                db.ejecutar("DELETE FROM nube_archivos WHERE video_id = %s", (f["video_id"],))
            repetidas += 1
            print(f"♻️ Repetida: «{str(f['titulo'])[:50]}» ({f['video_id']}) -> queda {queda['video_id']}")
    _cache["hasta"] = 0
    return repetidas
