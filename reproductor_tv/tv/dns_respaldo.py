"""
Respaldo de DNS para el TV.

Algunos TV / TV Box (o la red del bar) no logran "encontrar" las direcciones de internet
(error "Failed to resolve ... No address associated with hostname") aunque sí tengan
internet. Si eso pasa, aquí se pregunta la dirección a Cloudflare (1.1.1.1) o Google
(8.8.8.8) directamente por su número, sin depender del DNS del TV, y se guarda un rato.

Si el TV de verdad no tiene internet, esto tampoco funciona y se muestra el aviso normal.
"""
import json
import socket
import ssl
import threading
import time
import http.client
import urllib.parse

_SERVIDORES = (("1.1.1.1", "/dns-query"), ("8.8.8.8", "/resolve"))
_CACHE_SEG = 30 * 60
_cache = {}  # host -> (ips, hasta)
_lock = threading.Lock()
_original = socket.getaddrinfo


def _contexto():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _preguntar(host):
    for ip, ruta in _SERVIDORES:
        try:
            c = http.client.HTTPSConnection(ip, 443, timeout=5, context=_contexto())
            c.request("GET", f"{ruta}?name={urllib.parse.quote(host)}&type=A",
                      headers={"accept": "application/dns-json"})
            r = c.getresponse()
            datos = json.loads(r.read().decode("utf-8", "replace"))
            c.close()
            ips = [a["data"] for a in datos.get("Answer", []) if a.get("type") == 1]
            if ips:
                return ips
        except Exception:
            continue
    return []


def _getaddrinfo(host, port, *args, **kw):
    try:
        return _original(host, port, *args, **kw)
    except socket.gaierror:
        if not isinstance(host, str) or not host or host.replace(".", "").isdigit():
            raise
        ahora = time.time()
        with _lock:
            guardado = _cache.get(host)
        ips = guardado[0] if guardado and guardado[1] > ahora else _preguntar(host)
        if not ips:
            raise
        with _lock:
            if not guardado or guardado[1] <= ahora:
                print(f"🌐 DNS del TV falló para {host}: se usa el respaldo ({ips[0]})")
            _cache[host] = (ips, ahora + _CACHE_SEG)
        resultado = []
        for ip in ips:
            try:
                resultado += _original(ip, port, *args, **kw)
            except socket.gaierror:
                pass
        if not resultado:
            raise
        return resultado


def activar():
    if socket.getaddrinfo is not _getaddrinfo:
        socket.getaddrinfo = _getaddrinfo


def explicar_error(ex):
    """Mensaje claro para la pantalla del TV en vez del error técnico."""
    t = f"{type(ex).__name__}: {ex}"
    if any(s in t for s in ("NameResolution", "Failed to resolve", "getaddrinfo",
                            "No address associated", "Name or service not known")):
        return ("El TV no logra conectarse a internet (no encuentra el servidor). Revisa que "
                "el TV tenga Wi-Fi o cable conectado y que otras apps abran, y vuelve a intentar.")
    if any(s in t for s in ("ConnectTimeout", "ReadTimeout", "Timeout", "timed out")):
        return "El internet del TV está muy lento o se cortó. Vuelve a intentar en un momento."
    if any(s in t for s in ("ConnectionError", "Connection refused", "Max retries",
                            "Network is unreachable", "Connection reset")):
        return ("No hay conexión con el servidor de PlayBar GO. Revisa el internet del TV y "
                "vuelve a intentar.")
    if "SSL" in t or "CERTIFICATE" in t.upper():
        return ("El TV tiene la fecha u hora mal puestas (la conexión segura falla). "
                "Corrige la fecha y hora del TV y vuelve a intentar.")
    return str(ex)
