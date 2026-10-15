"""
Registro de bares nuevos desde la web (play.alnovix.com/comprar).

El bar se crea con su código (4 dígitos al azar, sin repetir) y su usuario administrador,
pero SIN prueba gratis: queda "vencido" hasta que Wompi apruebe el pago. Así nadie usa
PlayBar GO sin pagar, y si la persona cierra el navegador antes de pagar puede entrar a
/admin con su código y terminar el pago desde "Mi plan".

La llave del reproductor NO se entrega aquí: la asigna el super administrador cuando el
dueño del bar escribe por WhatsApp.
"""
import re
import secrets

from services import db

RESERVADOS = {"9999"}  # bar de pruebas de pagos


def nuevo_codigo():
    for _ in range(200):
        codigo = str(1000 + secrets.randbelow(9000))
        if codigo not in RESERVADOS and not db.cliente(codigo):
            return codigo
    raise RuntimeError("No se pudo generar un código de bar libre")


def limpiar_celular(valor):
    numero = "".join(c for c in str(valor or "") if c.isdigit())
    if len(numero) == 12 and numero.startswith("57"):
        numero = numero[2:]
    return numero


def validar(nombre, ciudad, celular, usuario, clave, clave2):
    """Devuelve un mensaje de error para la persona, o "" si todo está bien."""
    if len(str(nombre or "").strip()) < 3:
        return "Escribe el nombre de tu bar."
    if len(str(ciudad or "").strip()) < 3:
        return "Escribe la ciudad."
    cel = limpiar_celular(celular)
    if not (len(cel) == 10 and cel.startswith("3")):
        return "El celular debe tener 10 dígitos y empezar por 3 (sin +57)."
    if not re.fullmatch(r"[A-Za-z0-9._-]{3,30}", str(usuario or "").strip()):
        return "El usuario debe tener de 3 a 30 letras o números, sin espacios."
    if len(str(clave or "")) < 6:
        return "La contraseña debe tener al menos 6 caracteres."
    if str(clave) != str(clave2):
        return "Las dos contraseñas no coinciden."
    return ""


def crear_bar(nombre, ciudad, celular, usuario, clave):
    """Crea el bar (sin servicio hasta pagar) y su administrador. Devuelve el bar."""
    codigo = nuevo_codigo()
    bar = db.guardar_cliente(codigo, str(nombre).strip())
    try:
        db.ejecutar("UPDATE clientes SET plan_estado = 'vencido', prueba_limite = 0 "
                    "WHERE codigo = %s", (codigo,))
        nota = f"Registro web · cel {limpiar_celular(celular)} · {str(ciudad).strip()}"
        db.agregar_admin(codigo, str(usuario).strip(), str(clave), rol="admin", nota=nota)
    except Exception:
        db.ejecutar("DELETE FROM admins WHERE codigo = %s", (codigo,))
        db.ejecutar("DELETE FROM clientes WHERE codigo = %s", (codigo,))
        raise
    print(f"🆕 Bar registrado desde la web: {codigo} «{bar['nombre']}» ({ciudad}) — pendiente de pago")
    return db.cliente(codigo)
