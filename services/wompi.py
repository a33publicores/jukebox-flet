"""
Wompi para PlayBar GO (igual que en ALNOVIX POS).

Variables de Railway (servicio playbar-api), las mismas que usa ALNOVIX:
    WOMPI_PUBLIC_KEY        pub_test_... (pruebas) o pub_prod_... (real)
    WOMPI_PRIVATE_KEY       prv_test_... o prv_prod_...   (para confirmar pagos solo)
    WOMPI_INTEGRITY_SECRET  test_integrity_... o prod_integrity_...
    WOMPI_EVENTS_SECRET     test_events_... o prod_events_...   (para el webhook)
    WOMPI_ENVIRONMENT       sandbox | production   (si falta, se deduce de la llave)

Los secretos nunca llegan al celular ni al reproductor: la firma se hace aquí.
"""
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.parse
import urllib.request

CHECKOUT_URL = "https://checkout.wompi.co/p/"


class WompiError(RuntimeError):
    pass


def _var(nombre):
    return os.getenv(nombre, "").strip()


def configurado():
    return bool(_var("WOMPI_PUBLIC_KEY") and _var("WOMPI_INTEGRITY_SECRET"))


def ambiente():
    env = _var("WOMPI_ENVIRONMENT").lower()
    if env in ("sandbox", "test", "pruebas"):
        return "sandbox"
    if env in ("production", "produccion", "prod"):
        return "production"
    return "production" if _var("WOMPI_PUBLIC_KEY").startswith("pub_prod_") else "sandbox"


def api_url():
    return ("https://production.wompi.co/v1" if ambiente() == "production"
            else "https://sandbox.wompi.co/v1")


def _requerir(nombre):
    v = _var(nombre)
    if not v:
        raise WompiError(f"Falta la variable {nombre} en Railway (servicio playbar-api).")
    return v


def firma_integridad(referencia, centavos, moneda="COP"):
    cadena = f"{referencia}{int(centavos)}{moneda.upper()}{_requerir('WOMPI_INTEGRITY_SECRET')}"
    return hashlib.sha256(cadena.encode("utf-8")).hexdigest()


def checkout_url(referencia, monto_pesos, redirect_url=None, moneda="COP"):
    """Enlace del Web Checkout de Wompi para pagar `monto_pesos`."""
    centavos = int(monto_pesos) * 100
    params = {
        "public-key": _requerir("WOMPI_PUBLIC_KEY"),
        "currency": moneda.upper(),
        "amount-in-cents": str(centavos),
        "reference": referencia,
        "signature:integrity": firma_integridad(referencia, centavos, moneda),
    }
    if redirect_url:
        params["redirect-url"] = redirect_url
    return f"{CHECKOUT_URL}?{urllib.parse.urlencode(params)}"


def _get(url, llave):
    req = urllib.request.Request(url, headers={
        "Accept": "application/json", "Authorization": f"Bearer {llave}",
        "User-Agent": "PlayBarGO-Wompi/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detalle = e.read().decode("utf-8")[:300]
        except Exception:
            detalle = str(e)
        raise WompiError(f"Wompi respondió HTTP {e.code}: {detalle}") from e
    except urllib.error.URLError as e:
        raise WompiError(f"No se pudo consultar Wompi: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise WompiError("Wompi devolvió una respuesta no válida") from e


def consultar_transaccion(id_transaccion):
    """Estado de una transacción (con la llave pública, como hace ALNOVIX)."""
    tid = str(id_transaccion or "").strip()
    if not tid:
        raise WompiError("Falta el id de la transacción")
    data = _get(f"{api_url()}/transactions/{urllib.parse.quote(tid)}",
                _requerir("WOMPI_PUBLIC_KEY")).get("data")
    if not isinstance(data, dict):
        raise WompiError("La respuesta de Wompi no trae la transacción")
    return _normalizar(data)


def buscar_por_referencia(referencia):
    """Transacciones de una referencia (con la llave privada). Sirve para confirmar los
    pagos solo, aunque el webhook de la cuenta Wompi apunte a ALNOVIX."""
    llave = _var("WOMPI_PRIVATE_KEY")
    if not llave:
        return []
    data = _get(f"{api_url()}/transactions?reference={urllib.parse.quote(str(referencia))}",
                llave).get("data") or []
    return [_normalizar(t) for t in data if isinstance(t, dict)]


def _normalizar(t):
    def primero(*nombres):
        for n in nombres:
            if n in t and t[n] is not None:
                return t[n]
        return None
    return {
        "id": str(primero("id") or ""),
        "reference": str(primero("reference") or ""),
        "status": str(primero("status") or "").upper(),
        "amount_in_cents": primero("amount_in_cents", "amountInCents"),
        "currency": str(primero("currency") or "").upper(),
    }


def coincide(orden, tx):
    """La transacción corresponde EXACTAMENTE a la orden (referencia, monto y moneda)."""
    try:
        monto = int(tx.get("amount_in_cents"))
    except (TypeError, ValueError):
        return False
    return (tx.get("reference") == orden["referencia"]
            and tx.get("currency") == str(orden.get("moneda") or "COP").upper()
            and monto == int(orden["monto"]) * 100)


# ---------------------------------------------------------------------------
# Webhook (eventos) — misma validación que ALNOVIX
# ---------------------------------------------------------------------------
def _ruta(data, ruta):
    actual = data
    for parte in ruta.split("."):
        if not isinstance(actual, dict) or parte not in actual:
            raise KeyError(ruta)
        actual = actual[parte]
    return actual


def firma_evento_valida(evento, checksum_header=None):
    secreto = _var("WOMPI_EVENTS_SECRET")
    if not secreto:
        return False
    firma = evento.get("signature") or {}
    props = firma.get("properties")
    ts = evento.get("timestamp")
    checksum = (checksum_header or firma.get("checksum") or "").strip().lower()
    if not isinstance(props, list) or not props or ts is None or not checksum:
        return False
    try:
        valores = [str(_ruta(evento.get("data") or {}, p)) for p in props]
    except (KeyError, TypeError):
        return False
    esperado = hashlib.sha256(("".join(valores) + str(ts) + secreto).encode()).hexdigest()
    return hmac.compare_digest(esperado.lower(), checksum)


def ambiente_evento_ok(evento):
    amb = str(evento.get("environment") or "").strip().lower()
    return not amb or amb == ("test" if ambiente() == "sandbox" else "prod")


def transaccion_de_evento(evento):
    if evento.get("event") != "transaction.updated":
        return None
    t = (evento.get("data") or {}).get("transaction")
    return _normalizar(t) if isinstance(t, dict) else None
