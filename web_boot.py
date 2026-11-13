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
  <link rel="preconnect" href="https://www.gstatic.com" crossorigin>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin>
  <style>
    /* oculta el loader original de Flet (flor) por si llegara a existir */
    #loading {{ display: none !important; }}
    html, body {{ background: {BG}; }}
    #pbgo-splash {{
      position: fixed; inset: 0; z-index: 2147483647;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      background: {BG};
    }}
    /* círculo que gira debajo del logo mientras carga */
    #pbgo-splash .rueda {{
      width: 44px; height: 44px; margin-top: 18px; border-radius: 50%;
      border: 4px solid rgba(34, 211, 238, .18); border-top-color: #22d3ee; border-right-color: #a855f7;
      animation: pbgo-gira .9s linear infinite;
    }}
    @keyframes pbgo-gira {{ to {{ transform: rotate(360deg); }} }}
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
    // Recarga automática por reconexión: se hace en silencio (sin el logo grande ni la rueda),
    // para que no parezca que la página "se refresca sola". Solo vale si la marca es reciente.
    (function () {{
      try {{
        var t = parseInt(sessionStorage.getItem('pbgo-recarga') || '0', 10);
        sessionStorage.removeItem('pbgo-recarga');
        if (t && Date.now() - t < 30000) {{
          var st = document.createElement('style');
          st.textContent = '#pbgo-splash {{ display: none !important; }}';
          document.head.appendChild(st);
        }}
      }} catch (e) {{}}
    }})();
  </script>
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
      // Largos a propósito: si la conexión tarda, mejor el logo cargando que el
      // "Working..." en blanco de Flet.
      window.addEventListener('flutter-first-frame', function () {{
        setTimeout(hide, 45000);
      }}, {{ once: true }});
      // Si la sesión se retoma (recargar la página), la vista splash de Python no vuelve a
      // correr y no llega la señal: el logo no debe quedarse tapando la pantalla.
      window.addEventListener('pbgo-conectado', function () {{
        setTimeout(hide, 4000);
      }}, {{ once: true }});
      setTimeout(hide, 60000);
    }})();
  </script>
  <script>
    // Conexión que se retoma sola (ver services/flet_reanudar.py). Flet recibe una conexión
    // que nunca se cae: por debajo, si la de verdad se corta (datos móviles, pantalla
    // bloqueada), se abre otra enganchada a la MISMA sesión del servidor y cada lado repite
    // los mensajes que el otro no alcanzó a recibir. La página no se recarga ni se pierde lo
    // que hay en pantalla. Solo si el servidor ya no tiene la sesión (se reinició, o pasó
    // más de una hora) responde 4000 y la página se recarga una vez.
    (function () {{
      var W = window.WebSocket;
      if (!W || typeof EventTarget !== 'function') return;
      function avisar(texto) {{  // queda en los registros del servidor (diagnóstico)
        try {{ navigator.sendBeacon('/pbgo-diag', texto + ' · ' + location.pathname.slice(0, 40)); }} catch (e) {{}}
      }}
      function recargar(motivo) {{
        console.log('PBGO: se recarga: ' + motivo);
        avisar('recarga: ' + motivo);
        // Si la pestaña está visible, se recarga en silencio; si está oculta nadie lo ve.
        try {{ sessionStorage.setItem('pbgo-recarga', String(Date.now())); }} catch (e) {{}}
        location.reload();
      }}
      function esToque(d) {{
        // trama de Flet: [0x00][msgpack [accion, cuerpo]]; accion 3 = evento de un control
        try {{
          var b = d instanceof ArrayBuffer ? new Uint8Array(d)
                : (ArrayBuffer.isView(d) ? new Uint8Array(d.buffer, d.byteOffset, d.byteLength) : null);
          return !!b && b.length > 2 && b[0] === 0 && b[1] === 0x92 && b[2] === 3;
        }} catch (e) {{ return false; }}
      }}
      function copia(d) {{
        try {{
          if (d instanceof ArrayBuffer) return d.slice(0);
          if (ArrayBuffer.isView(d)) return d.buffer.slice(d.byteOffset, d.byteOffset + d.byteLength);
        }} catch (e) {{}}
        return d;
      }}
      function Conexion(url, prot) {{
        var dir = String(url);
        if (dir.indexOf('/ws') < 0) return prot === undefined ? new W(url) : new W(url, prot);
        var f = new EventTarget();
        var token = Math.random().toString(36).slice(2) + Date.now().toString(36);
        var base = dir + (dir.indexOf('?') > -1 ? '&' : '?') + 'pbgo_t=' + token;
        var tipo = 'blob', real = null, estado = 0, cerrando = false, poniendoAlDia = false;
        var recibidos = 0, enviados = 0, guardados = [], intentos = 0, espera = null;
        var estuvoOculta = false, tocado = 0;
        function emitir(ev) {{
          var h = f['on' + ev.type];
          if (typeof h === 'function') {{ try {{ h.call(f, ev); }} catch (e) {{ setTimeout(function () {{ throw e; }}); }} }}
          f.dispatchEvent(ev);
        }}
        function terminar(code, reason) {{
          if (estado === 3) return;
          estado = 3;
          emitir(new CloseEvent('close', {{ code: code || 1000, reason: reason || '', wasClean: true }}));
        }}
        function abrir(retomar) {{
          espera = null;
          var u = retomar ? base + '&pbgo_r=1&pbgo_n=' + recibidos : base;
          var s = prot === undefined ? new W(u) : new W(u, prot);
          s.binaryType = tipo;
          real = s; poniendoAlDia = !!retomar;
          s.addEventListener('open', function () {{
            if (s !== real) return;
            intentos = 0;
            if (!retomar) {{ estado = 1; emitir(new Event('open')); }}
          }});
          s.addEventListener('message', function (e) {{
            if (s !== real) return;
            if (typeof e.data === 'string') {{
              if (e.data.indexOf('pbgo:') === 0) {{  // el servidor dice cuántos le llegaron
                var n = parseInt(e.data.slice(5), 10) || 0;
                if (guardados.length && n < guardados[0][0] - 1) {{ recargar('se perdieron datos al retomar'); return; }}
                guardados = guardados.filter(function (g) {{ return g[0] > n; }});
                poniendoAlDia = false;
                for (var i = 0; i < guardados.length; i++) {{ try {{ s.send(guardados[i][1]); }} catch (x) {{}} }}
                avisar('conexión retomada sin recargar');
              }}
              return;
            }}
            recibidos++; tocado = 0; estuvoOculta = false;
            window.dispatchEvent(new Event('pbgo-conectado'));
            emitir(new MessageEvent('message', {{ data: e.data }}));
          }});
          s.addEventListener('close', function (e) {{
            if (s !== real) return;
            real = null;
            if (cerrando) {{ terminar(e.code, e.reason); return; }}
            if (e.code === 4000) {{ recargar('la sesión ya no existía en el servidor'); return; }}
            if (estado === 0) {{ emitir(new Event('error')); terminar(e.code, e.reason); return; }}
            reintentar(false);
          }});
        }}
        function reintentar(ya) {{
          if (cerrando || real || espera || estado === 0 || estado === 3) return;
          var ms = ya || intentos === 0 ? 0 : Math.min(10000, 500 * Math.pow(2, intentos));
          intentos++;
          espera = setTimeout(function () {{ abrir(true); }}, ms);
        }}
        function cambiar(motivo) {{  // la conexión está muerta aunque el navegador no lo sepa
          if (!real || cerrando) return;
          avisar(motivo);
          var s = real; real = null;
          try {{ s.close(4100); }} catch (e) {{}}
          reintentar(true);
        }}
        Object.defineProperty(f, 'readyState', {{ get: function () {{ return estado; }} }});
        Object.defineProperty(f, 'binaryType', {{
          get: function () {{ return tipo; }},
          set: function (v) {{ tipo = v; if (real) real.binaryType = v; }}
        }});
        Object.defineProperty(f, 'bufferedAmount', {{ get: function () {{ return real ? real.bufferedAmount : 0; }} }});
        Object.defineProperty(f, 'protocol', {{ get: function () {{ return real ? real.protocol : ''; }} }});
        f.url = dir; f.extensions = '';
        f.CONNECTING = 0; f.OPEN = 1; f.CLOSING = 2; f.CLOSED = 3;
        f.send = function (d) {{
          enviados++;
          guardados.push([enviados, copia(d)]);
          if (guardados.length > 600) guardados.shift();
          if (estuvoOculta && !tocado && esToque(d)) tocado = Date.now();
          if (real && real.readyState === 1 && !poniendoAlDia) {{ try {{ real.send(d); }} catch (e) {{}} }}
        }};
        f.close = function (code, reason) {{
          cerrando = true;
          if (estado < 2) estado = 2;
          if (espera) {{ clearTimeout(espera); espera = null; }}
          if (real) {{ try {{ real.close(code, reason); }} catch (e) {{ real.close(); }} }}
          else terminar(code, reason);
        }};
        document.addEventListener('visibilitychange', function () {{
          if (document.hidden) estuvoOculta = true;
          else reintentar(true);  // si se había caído, se retoma ya, sin esperar
        }});
        window.addEventListener('online', function () {{ reintentar(true); }});
        setInterval(function () {{
          if (tocado && Date.now() - tocado > 10000) {{
            tocado = 0;
            cambiar('un toque sin respuesta en 10 s al volver: se retoma la conexión');
          }}
        }}, 1000);
        abrir(false);
        return f;
      }}
      Conexion.prototype = W.prototype;
      ['CONNECTING', 'OPEN', 'CLOSING', 'CLOSED'].forEach(function (k) {{ Conexion[k] = W[k]; }});
      window.WebSocket = Conexion;
    }})();
  </script>
"""

_BODY_OVERLAY = (
    '\n  <div id="pbgo-splash" role="status" aria-label="PlayBar GO">'
    '<img src="logo.png" alt="PlayBar GO"><div class="rueda"></div></div>\n'
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
