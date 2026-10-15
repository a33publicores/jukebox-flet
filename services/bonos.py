"""
Bonos de referido de PlayBar GO: un código (PBG-XXXXXX) que descuenta DESCUENTO pesos de
UN pago (la compra en /comprar o una renovación en "Mi plan"). Los crea el super
administrador en /super → Bonos.

Reglas:
  - Cada bono sirve una sola vez y solo para ese pago (no para las mensualidades).
  - Al crear la orden de pago el bono queda RESERVADO a esa orden (nadie más lo puede
    usar mientras tanto). Queda USADO cuando Wompi aprueba; si el pago se rechaza o se
    abandona (pasan RESERVA_SEG sin aprobarse), vuelve a quedar libre.
  - El precio con descuento se calcula aquí, en el servidor (el navegador no lo decide),
    y nunca baja de MINIMO_WOMPI.
"""
import os
import secrets
import time

from services import db

DESCUENTO = int(os.getenv("BONO_DESCUENTO") or 15000)  # pesos que descuenta un bono nuevo
MINIMO_WOMPI = 1500        # Wompi no acepta pagos menores
RESERVA_SEG = 2 * 3600     # cuánto queda apartado un bono mientras se paga
PREFIJO = "PBG-"
_ALFABETO = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # sin 0/O, 1/I/L


def normalizar(codigo):
    c = "".join(str(codigo or "").split()).upper()
    if c and not c.startswith(PREFIJO):
        c = PREFIJO + c.replace("PBG", "", 1).lstrip("-")
    return c


def crear(nota=""):
    for _ in range(50):
        codigo = PREFIJO + "".join(secrets.choice(_ALFABETO) for _ in range(6))
        fila = db.uno("""INSERT INTO bonos (codigo, nota, descuento, creado) VALUES (%s, %s, %s, %s)
                         ON CONFLICT (codigo) DO NOTHING RETURNING *""",
                      (codigo, str(nota or "").strip()[:120], DESCUENTO, time.time()))
        if fila:
            return fila
    raise RuntimeError("No se pudo generar un bono único")


def lista(limite=300):
    return db.consultar("SELECT * FROM bonos ORDER BY creado DESC LIMIT %s", (int(limite),))


def poner_activo(codigo, activo):
    db.ejecutar("UPDATE bonos SET activo = %s WHERE codigo = %s AND usado_ref = ''",
                (bool(activo), normalizar(codigo)))


def estado_txt(b):
    if b["usado_ref"]:
        return "usado"
    if not b["activo"]:
        return "desactivado"
    if b["reservado_ref"] and b["reservado_hasta"] > time.time():
        return "reservado"
    return "sin usar"


def precio_con_bono(precio, bono):
    """(monto a cobrar, descuento aplicado). Nunca por debajo del mínimo de Wompi."""
    precio = int(precio)
    if not bono:
        return precio, 0
    monto = max(precio - int(bono["descuento"]), MINIMO_WOMPI, 0)
    monto = min(monto, precio)
    return monto, precio - monto


def revisar(codigo, codigo_bar=None):
    """(bono, "") si se puede usar ahora, o (None, mensaje para la persona). No reserva."""
    c = normalizar(codigo)
    if not c:
        return None, ""
    b = db.uno("SELECT * FROM bonos WHERE codigo = %s", (c,))
    if not b or not b["activo"]:
        return None, "Ese código de bono no existe o no está activo."
    if b["usado_ref"]:
        return None, "Ese código de bono ya fue usado."
    if b["reservado_ref"] and b["reservado_hasta"] > time.time():
        propio = codigo_bar and db.uno(
            "SELECT 1 AS x FROM pagos WHERE referencia = %s AND codigo = %s",
            (b["reservado_ref"], str(codigo_bar)))
        if not propio:
            return None, "Ese código de bono se está usando en otro pago. Intenta en un rato."
    return b, ""


def reservar(codigo, referencia, codigo_bar):
    """Aparta el bono para esta orden, en una sola operación (dos personas no pueden
    tomarlo a la vez). Devuelve el bono o None."""
    ahora = time.time()
    return db.uno(
        """UPDATE bonos SET reservado_ref = %s, reservado_hasta = %s
           WHERE codigo = %s AND activo AND usado_ref = ''
             AND (reservado_ref = '' OR reservado_hasta < %s
                  OR reservado_ref IN (SELECT referencia FROM pagos
                                       WHERE codigo = %s AND estado = 'PENDIENTE'))
           RETURNING *""",
        (str(referencia), ahora + RESERVA_SEG, normalizar(codigo), ahora, str(codigo_bar)))


def usar(orden):
    """Wompi aprobó la orden: el bono queda usado por ese bar."""
    if not orden.get("bono"):
        return
    fila = db.uno(
        """UPDATE bonos SET usado_ref = %s, usado_bar = %s, usado_en = %s,
                  reservado_ref = '', reservado_hasta = 0
           WHERE codigo = %s AND usado_ref = '' RETURNING codigo""",
        (orden["referencia"], orden["codigo"], time.time(), orden["bono"]))
    if not fila:
        print(f"⚠️ Bono {orden['bono']} ya estaba usado (orden {orden['referencia']})")


def liberar(referencia):
    """El pago no se aprobó: el bono vuelve a quedar libre."""
    db.ejecutar("UPDATE bonos SET reservado_ref = '', reservado_hasta = 0 "
                "WHERE reservado_ref = %s AND usado_ref = ''", (str(referencia),))
