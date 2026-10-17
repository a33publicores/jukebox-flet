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
import sys
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
  <script>
    // Vigilante de la conexión. En el celular, al bloquear la pantalla o cambiar de app,
    // la conexión con el servidor puede quedar "muerta" sin que el navegador se entere:
    // la página se ve normal pero tocar la lupa no hace nada hasta recargar.
    // Si un toque no recibe NINGUNA respuesta del servidor en 8 s, se cierra esa conexión
    // (Flet se reconecta solo y la sesión del dispositivo se recupera); si aun así no
    // responde, se recarga la página.
    (function () {{
      var W = window.WebSocket;
      if (!W) return;
      var actual = null, tocado = 0, cerrado = 0;
      function esToque(d) {{
        // trama de Flet: [0x00][msgpack [accion, cuerpo]]; accion 3 = evento de un control
        try {{
          var b = d instanceof ArrayBuffer ? new Uint8Array(d)
                : (ArrayBuffer.isView(d) ? new Uint8Array(d.buffer, d.byteOffset, d.byteLength) : null);
          return !!b && b.length > 2 && b[0] === 0 && b[1] === 0x92 && b[2] === 3;
        }} catch (e) {{ return false; }}
      }}
      function Envuelto(url, prot) {{
        var s = prot === undefined ? new W(url) : new W(url, prot);
        if (String(url).indexOf('/ws') < 0) return s;
        actual = s; tocado = 0;
        s.addEventListener('message', function () {{
          if (s === actual) {{ tocado = 0; cerrado = 0; }}
        }});
        var enviar = s.send;
        s.send = function (d) {{
          if (s === actual && !tocado && esToque(d)) tocado = Date.now();
          return enviar.apply(s, arguments);
        }};
        return s;
      }}
      Envuelto.prototype = W.prototype;
      ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach(function (k) {{ Envuelto[k] = W[k]; }});
      window.WebSocket = Envuelto;
      setInterval(function () {{
        var ahora = Date.now();
        if (cerrado && ahora - cerrado > 10000) {{
          console.log('PBGO: sin respuesta tras reconectar, se recarga');
          cerrado = 0;
          location.reload();
          return;
        }}
        if (tocado && !cerrado && actual && ahora - tocado > 8000) {{
          console.log('PBGO: conexión sin respuesta, se reconecta');
          tocado = 0;
          cerrado = ahora;
          try {{ actual.close(); }} catch (e) {{ location.reload(); }}
        }}
      }}, 1000);
    }})();
  </script>
"""

_BODY_OVERLAY = (
    '\n  <div id="pbgo-splash" role="status" aria-label="PlayBar GO">'
    '<img src="logo.png" alt="PlayBar GO"></div>\n'
)


def _flet_web_dir() -> Path | None:
    """Carpeta web de flet-web. En Railway, flet-web se instala al arrancar
    (dentro de ft.run), así que si todavía no está lo instalamos aquí con la
    misma función que usa Flet; ft.run después lo encuentra y no reinstala."""
    import importlib

    def _try():
        import flet_web

        importlib.invalidate_caches()
        return Path(flet_web.get_package_web_dir())

    try:
        return _try()
    except Exception:
        pass
    try:
        from flet.utils.pip import ensure_flet_web_package_installed

        ensure_flet_web_package_installed()
        importlib.invalidate_caches()
        for name in [m for m in list(sys.modules) if m.startswith("flet_web")]:
            del sys.modules[name]
        return _try()
    except Exception as ex:
        print(f"⚠️ No se pudo preparar flet-web: {ex}")
    return None


def _flet_index_path() -> Path | None:
    web = _flet_web_dir()
    if web and (web / "index.html").exists():
        return web / "index.html"
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
