"""
Temas por temporada de PlayBar GO (Navidad, Halloween, Amor y amistad...).

El super administrador los maneja en /super → 🎨 Temas: cada tema es una plantilla con
colores, un mensaje, adornos (emojis), un efecto animado y las fechas en que se activa sola.

Qué tema se ve (para todos los bares):
    modo "normal"        sin tema (los colores de siempre)
    modo "auto"          (por defecto) el tema cuyas fechas incluyen hoy (si no hay, normal)
    modo "<clave>"       ese tema, todos los días, hasta que se cambie

Lo usan los reproductores (navegador, TV y PC) con /api/v1/tema y la página de los clientes.
"""
import json
import os
import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from services import db

COLOMBIA = ZoneInfo("America/Bogota")
EFECTOS = {
    "ninguno": "Sin efecto",
    "nieve": "❄️ Nieve",
    "murcielagos": "🦇 Murciélagos",
    "corazones": "💕 Corazones",
    "confeti": "🎉 Confeti",
    "estrellas": "✨ Estrellas",
    "hojas": "🍂 Hojas",
}
# Lo que cae en cada efecto (los reproductores dibujan estos emojis)
FIGURAS = {
    "nieve": ["❄", "❅", "❆", "•"],
    "murcielagos": ["🦇", "🦇", "🕸️", "👻"],
    "corazones": ["💖", "💕", "❤️", "💘"],
    "confeti": ["🎉", "🎊", "✨", "🎈"],
    "estrellas": ["✨", "⭐", "🌟", "💫"],
    "hojas": ["🍂", "🍁", "🍃", "🍂"],
}
COLORES = ("fondo", "panel", "acento", "acento2", "texto")
NORMAL = {"fondo": "#020617", "panel": "#0f172a", "acento": "#22d3ee", "acento2": "#a78bfa",
          "texto": "#f8fafc"}

EJEMPLOS = [
    {"clave": "navidad", "nombre": "🎄 Navidad", "orden": 1,
     "mensaje": "🎄 ¡Feliz Navidad! Pide tu canción favorita",
     "adornos": "🎄🎅🎁⭐", "efecto": "nieve", "desde": "12-01", "hasta": "01-06",
     "colores": {"fondo": "#04140d", "panel": "#0c2a1b", "acento": "#ef4444", "acento2": "#facc15",
                 "texto": "#f8fafc"}},
    {"clave": "halloween", "nombre": "🎃 Halloween", "orden": 2,
     "mensaje": "🎃 ¡Feliz Halloween! Noche de terror y buena música",
     "adornos": "🎃👻🦇🕸️", "efecto": "murcielagos", "desde": "10-20", "hasta": "10-31",
     "logo": "logohallowen.png",
     "colores": {"fondo": "#0d0716", "panel": "#1e1030", "acento": "#f97316", "acento2": "#a855f7",
                 "texto": "#fff7ed"}},
]

_cache = {"tema": None, "hasta": 0.0}
_lock = threading.Lock()
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_FECHA = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
_LOGO = re.compile(r"^[\w.-]+\.(png|jpe?g|webp|gif)$", re.I)
ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def web():
    return os.getenv("PLAYBAR_WEB_URL", "https://play.alnovix.com").strip().rstrip("/")


def logos_disponibles():
    """Los logos que hay en assets/ (logo.png, logohallowen.png, logomundial.png...)."""
    try:
        return sorted(f for f in os.listdir(ASSETS) if f.lower().startswith("logo") and _LOGO.match(f))
    except OSError:
        return []


def _ajuste(clave, defecto=""):
    f = db.uno("SELECT valor FROM ajustes WHERE clave = %s", (clave,))
    return f["valor"] if f else defecto


def _poner_ajuste(clave, valor):
    db.ejecutar("""INSERT INTO ajustes (clave, valor) VALUES (%s, %s)
                   ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor""", (clave, str(valor)))


def sembrar():
    """Crea las plantillas de ejemplo la primera vez (si el super las borra, no vuelven)."""
    if _ajuste("temas_sembrados"):
        return
    for t in EJEMPLOS:
        if not db.uno("SELECT clave FROM temas WHERE clave = %s", (t["clave"],)):
            guardar(t)
    _poner_ajuste("temas_sembrados", "1")


def limpiar(t):
    """Deja el tema con valores válidos (lo que llegue del formulario)."""
    colores = dict(NORMAL)
    for k in COLORES:
        v = str((t.get("colores") or {}).get(k) or "").strip()
        if _HEX.match(v):
            colores[k] = v.lower()
    efecto = t.get("efecto") if t.get("efecto") in EFECTOS else "ninguno"
    desde, hasta = str(t.get("desde") or "").strip(), str(t.get("hasta") or "").strip()
    logo = str(t.get("logo") or "").strip()
    if not (_LOGO.match(logo) or (logo.startswith("https://") and len(logo) < 300)):
        logo = ""
    return {
        "clave": str(t.get("clave") or "").strip()[:40],
        "nombre": str(t.get("nombre") or "Tema").strip()[:60],
        "mensaje": str(t.get("mensaje") or "").strip()[:120],
        "adornos": str(t.get("adornos") or "").strip()[:24],
        "efecto": efecto,
        "desde": desde if _FECHA.match(desde) else "",
        "hasta": hasta if _FECHA.match(hasta) else "",
        "colores": colores,
        "logo": logo,
        "orden": int(t.get("orden") or 0),
    }


def _clave_nueva(nombre):
    base = re.sub(r"[^a-z0-9]+", "-", nombre.lower()).strip("-")[:30] or "tema"
    clave, n = base, 2
    while db.uno("SELECT clave FROM temas WHERE clave = %s", (clave,)):
        clave, n = f"{base}-{n}", n + 1
    return clave


def guardar(t):
    t = limpiar(t)
    if not t["clave"]:
        t["clave"] = _clave_nueva(t["nombre"])
    datos = {k: v for k, v in t.items() if k not in ("clave", "nombre", "orden")}
    db.ejecutar("""INSERT INTO temas (clave, nombre, datos, orden, actualizado)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (clave) DO UPDATE SET nombre = EXCLUDED.nombre, datos = EXCLUDED.datos,
                       orden = EXCLUDED.orden, actualizado = EXCLUDED.actualizado""",
                (t["clave"], t["nombre"], json.dumps(datos, ensure_ascii=False), t["orden"], time.time()))
    olvidar()
    return t


def borrar(clave):
    db.ejecutar("DELETE FROM temas WHERE clave = %s", (clave,))
    if modo() == clave:
        poner_modo("normal")
    olvidar()


def lista():
    temas = []
    for f in db.consultar("SELECT clave, nombre, datos, orden FROM temas ORDER BY orden, nombre"):
        try:
            datos = json.loads(f["datos"] or "{}")
        except ValueError:
            datos = {}
        temas.append(limpiar({**datos, "clave": f["clave"], "nombre": f["nombre"], "orden": f["orden"]}))
    return temas


def modo():
    # Por defecto, automático por fechas: cada tema se ve solo en su temporada.
    return _ajuste("tema_modo", "auto") or "auto"


def poner_modo(valor):
    _poner_ajuste("tema_modo", valor or "normal")
    olvidar()


def olvidar():
    with _lock:
        _cache.update(tema=None, hasta=0.0)


def en_fechas(t, hoy):
    """¿`hoy` ("MM-DD") está entre desde y hasta? (sirve también si cruza el año: 12-01 a 01-06)"""
    d, h = t.get("desde"), t.get("hasta")
    if not d or not h:
        return False
    return d <= hoy <= h if d <= h else (hoy >= d or hoy <= h)


def actual():
    """El tema que se ve ahora (dict) o None si es el normal. Se recalcula cada minuto."""
    with _lock:
        if time.time() < _cache["hasta"]:
            return _cache["tema"]
    try:
        m = modo()
        temas = lista()
        tema = None
        if m == "auto":
            hoy = datetime.now(COLOMBIA).strftime("%m-%d")
            tema = next((t for t in temas if en_fechas(t, hoy)), None)
        elif m != "normal":
            tema = next((t for t in temas if t["clave"] == m), None)
        if tema:
            logo = tema.get("logo") or ""
            tema = {**tema, "figuras": FIGURAS.get(tema["efecto"], []),
                    # dirección completa para los reproductores (TV/PC la bajan de la web)
                    "logo_url": logo if logo.startswith("https://") else (f"{web()}/{logo}" if logo else ""),
                    "logo_ruta": "" if logo.startswith("https://") else (f"/{logo}" if logo else "")}
    except Exception as ex:
        print(f"⚠️ Tema: {ex}")
        tema = None
    with _lock:
        _cache.update(tema=tema, hasta=time.time() + 60)
    return tema
