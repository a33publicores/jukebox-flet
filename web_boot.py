"""
Pantalla de arranque web de PlayBar GO.

Flet (modo web) muestra por defecto su logo de flor, luego el texto
"Working..." y la pestaña del navegador con el icono de Flet. Nada de eso
se puede cambiar desde la vista de Python, porque ocurre ANTES de que la
app de Python arranque.

Solucion: antes de iniciar Flet generamos `assets/index.html` a partir del
index.html de la version de Flet instalada, y le aplicamos:

  * titulo "PlayBar GO" y favicon propio (archivos *_v8, para saltar cache)
  * una capa (overlay) con el logo de PlayBar GO sobre fondo #020617 que
    aparece al instante y tapa el "Working..." de Flet
  * la capa se retira sola cuando la vista splash de Python carga la
    imagen de senal `pbgo_ready.png` (ver views/splash.py), asi el cambio
    del splash HTML al splash de Python es imperceptible

Si algo falla (version de Flet distinta, sin permisos de escritura...),
se borra el index.html generado y Flet usa el suyo: la app sigue
funcionando igual que antes.
"""

import os
import re
from pathlib import Path

ASSETS = Path(__file__).parent / "assets"
FAVICON_32 = "pbgo_favicon_v8_32.png"
FAVICON_192 = "pbgo_favicon_v8_192.png"
BG = "#020617"

_HEAD_EXTRA = f"""
  <link rel="icon" type="image/png" sizes="32x32" href="{FAVICON_32}">
  <link rel="icon" type="image/png" sizes="192x192" href="{FAVICON_192}">
  <link rel="apple-touch-icon" href="{FAVICON_192}">
  <meta name="theme-color" content="{BG}">
  <link rel="preload" as="image" href="logo.png">
  <style>
    /* oculta el loader original de Flet (flor) por si llegara a existir */
    #loading {{ display: none !important; }}
    html, body {{ background: {BG}; }}
    #pbgo-splash {{
      position: fixed; inset: 0; z-index: 2147483647;
      display: flex; align-items: center; justify-content: center;
      background: {BG};
    }}
    #pbgo-splash img {{
      width: 300px; height: 220px; max-width: 80vw; object-fit: contain;
      animation: pbgo-in .65s cubic-bezier(.215,.61,.355,1) both;
    }}
    @keyframes pbgo-in {{
      from {{ opacity: 0; transform: scale(.72); }}
      to   {{ opacity: 1; transform: scale(1); }}
    }}
  </style>
  <script>
    (function () {{
      var done = false;
      function hide() {{
        if (done) return;
        done = true;
        var el = document.getElementById('pbgo-splash');
        if (!el) return;
        el.style.transition = 'opacity .25s ease';
        el.style.opacity = '0';
        setTimeout(function () {{ el.remove(); }}, 320);
      }}
      // Senal: la vista splash de Python carga pbgo_ready.png.
      try {{
        var po = new PerformanceObserver(function (list) {{
          list.getEntries().forEach(function (e) {{
            if (e.name.indexOf('pbgo_ready') > -1) setTimeout(hide, 250);
          }});
        }});
        po.observe({{ type: 'resource', buffered: true }});
      }} catch (e) {{}}
      // Respaldos para que la capa nunca se quede pegada.
      window.addEventListener('flutter-first-frame', function () {{
        setTimeout(hide, 9000);
      }}, {{ once: true }});
      setTimeout(hide, 20000);
    }})();
  </script>
"""

_BODY_OVERLAY = (
    '\n  <div id="pbgo-splash" role="status" aria-label="PlayBar GO">'
    '<img src="logo.png" alt="PlayBar GO"></div>\n'
)


def _flet_index_path() -> Path | None:
    try:
        from flet_web import get_package_web_dir

        p = Path(get_package_web_dir()) / "index.html"
        if p.exists():
            return p
    except Exception:
        pass
    env = os.environ.get("FLET_WEB_PATH")
    if env and (Path(env) / "index.html").exists():
        return Path(env) / "index.html"
    return None


def _transform(html: str) -> str | None:
    if "</head>" not in html or not re.search(r"<body[^>]*>", html):
        return None
    if "flutter_bootstrap" not in html and "flutter" not in html:
        return None

    # titulo y metadatos
    html = re.sub(r"<title>.*?</title>", "<title>PlayBar GO</title>", html,
                  count=1, flags=re.S)
    html = re.sub(
        r'(<meta\s+name="apple-mobile-web-app-title"\s+content=")[^"]*(")',
        r"\1PlayBar GO\2", html)
    html = re.sub(
        r'(<meta\s+name="description"\s+content=")[^"]*(")',
        r"\1PlayBar GO - Música y Karaoke\2", html)

    # quitar iconos de Flet (favicon / apple-touch / shortcut icon)
    html = re.sub(
        r'<link\s+[^>]*rel="(?:shortcut icon|icon|apple-touch-icon)"[^>]*>',
        "", html, flags=re.I)

    html = html.replace("</head>", _HEAD_EXTRA + "</head>", 1)
    html = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + _BODY_OVERLAY,
                  html, count=1)
    return html


def preparar_index_web() -> bool:
    """Genera assets/index.html. Devuelve True si se aplico el splash propio."""
    target = ASSETS / "index.html"
    try:
        src = _flet_index_path()
        if src is None:
            raise RuntimeError("no se encontro el index.html de Flet")
        out = _transform(src.read_text(encoding="utf-8"))
        if out is None:
            raise RuntimeError("estructura de index.html no reconocida")
        target.write_text(out, encoding="utf-8")
        print("✅ index.html de PlayBar GO generado (splash + favicon)")
        return True
    except Exception as ex:
        print(f"⚠️ No se pudo personalizar index.html ({ex}); se usa el de Flet")
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass
        return False
