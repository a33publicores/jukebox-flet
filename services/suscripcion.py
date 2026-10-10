"""
Suscripción de los negocios de PlayBar GO: prueba gratis y planes pagos (Wompi).

Estados de un negocio (columna clientes.plan_estado):
    prueba     prueba gratis: puede pedir hasta `prueba_limite` canciones (30 por defecto)
    activo     pagó un plan: funciona hasta `plan_vence`
    vencido    se acabó el plan (o el super admin lo suspendió)
    cortesia   sin cobro (los negocios que ya existían; el super admin lo decide)

Cuando la prueba se acaba o el plan vence, la app no deja pedir canciones, el panel del
bar muestra "Adquirir plan" y el reproductor se detiene con el botón de pago.
El pago funciona igual que en ALNOVIX: orden PENDIENTE -> Wompi -> APROBADO.
"""
import hashlib
import hmac
import secrets
import time

from services import db

ESTADOS = ("prueba", "activo", "vencido", "cortesia")
NO_CUENTAN = ("Eliminado", "Error")  # pedidos que no gastan la prueba
AVISAR_DIAS = 3  # avisar que el plan está por vencer

# Bar de ejemplo para probar los pagos (lo pidió el dueño de PlayBar GO).
DEMO_CODIGO = "9999"
DEMO_USUARIO = "demo"
# Clave cifrada (la clave en texto NO está en el código: se la dio Claude al dueño).
DEMO_CLAVE_CIFRADA = "pbkdf2$527c1dd253e407ea$6ef40847b46c637513f32ff5d6e87a17f901bd7c00b6488eb37639a701cca673"


# ---------------------------------------------------------------------------
# Semillas: planes y bar de ejemplo (solo si no existen; se pueden editar en /super)
# ---------------------------------------------------------------------------
def sembrar():
    db.ejecutar(
        """INSERT INTO planes (clave, nombre, precio, dias, activo, solo_para, orden)
           VALUES ('mensual', 'Plan mensual', 60000, 30, TRUE, '', 1)
           ON CONFLICT (clave) DO NOTHING""")
    db.ejecutar(
        """INSERT INTO planes (clave, nombre, precio, dias, activo, solo_para, orden)
           VALUES ('prueba_pago', 'Prueba de pago', 3000, 1, TRUE, %s, 9)
           ON CONFLICT (clave) DO NOTHING""", (DEMO_CODIGO,))
    if not db.cliente(DEMO_CODIGO):
        db.guardar_cliente(DEMO_CODIGO, "Bar Demo Pagos")
        db.ejecutar("UPDATE clientes SET prueba_limite = 3 WHERE codigo = %s", (DEMO_CODIGO,))
        print(f"🧪 Bar de ejemplo {DEMO_CODIGO} creado (prueba de 3 canciones)")
    if DEMO_CLAVE_CIFRADA and not db.uno(
            "SELECT id FROM admins WHERE codigo = %s AND lower(usuario) = %s",
            (DEMO_CODIGO, DEMO_USUARIO)):
        db.ejecutar("INSERT INTO admins (codigo, usuario, clave, rol, nota) "
                    "VALUES (%s, %s, %s, 'admin', 'Usuario de ejemplo para probar pagos')",
                    (DEMO_CODIGO, DEMO_USUARIO, DEMO_CLAVE_CIFRADA))


# ---------------------------------------------------------------------------
# Estado de la suscripción
# ---------------------------------------------------------------------------
def usadas(codigo, desde):
    fila = db.uno(
        "SELECT COUNT(*) AS n FROM pedidos WHERE codigo = %s AND ts >= %s "
        "AND estado2 NOT IN ('Eliminado', 'Error') AND estado <> 'Error'",
        (str(codigo), float(desde or 0)))
    return int((fila or {}).get("n") or 0)


def fecha_txt(epoch):
    from services.playbar_service import ahora_local_txt
    return ahora_local_txt(epoch)[:10] if epoch else ""


def estado(codigo, cli=None):
    """Todo lo que la app, el panel y el reproductor necesitan saber del plan."""
    c = cli or db.cliente(codigo)
    if not c:
        return {"estado": "desconocido", "permitido": False, "titulo": "Negocio no encontrado",
                "mensaje": "", "usadas": 0, "limite": 0, "restantes": 0, "vence": 0,
                "dias_restantes": 0, "plan_nombre": "", "aviso": True}
    ahora = time.time()
    est = (c.get("plan_estado") or "prueba").strip().lower()
    limite = int(c.get("prueba_limite") or 0)
    vence = float(c.get("plan_vence") or 0)
    r = {"estado": est, "usadas": 0, "limite": limite, "restantes": 0, "vence": vence,
         "dias_restantes": 0, "plan_nombre": c.get("plan_nombre") or "", "aviso": False}

    if est == "cortesia":
        r.update(permitido=True, titulo="Plan de cortesía", mensaje="Sin cobro.")
    elif est == "activo":
        dias = (vence - ahora) / 86400
        r["dias_restantes"] = max(0, int(dias + 0.999))
        if vence > ahora:
            r.update(permitido=True, titulo=f"{r['plan_nombre'] or 'Plan'} activo",
                     mensaje=f"Vence el {fecha_txt(vence)} ({r['dias_restantes']} días).")
            r["aviso"] = dias <= AVISAR_DIAS
            if r["aviso"]:
                r["mensaje"] += " Renueva para no quedarte sin música."
        else:
            r.update(estado="vencido", permitido=False, aviso=True, titulo="Tu plan venció",
                     mensaje=f"Venció el {fecha_txt(vence)}. Renueva tu plan para seguir.")
    elif est == "prueba":
        n = usadas(codigo, c.get("prueba_desde"))
        r["usadas"], r["restantes"] = n, max(0, limite - n)
        if n < limite:
            r.update(permitido=True, titulo="Prueba gratis",
                     mensaje=f"Van {n} de {limite} canciones gratis. Quedan {r['restantes']}.")
            r["aviso"] = r["restantes"] <= max(3, limite // 10)
        else:
            r.update(permitido=False, aviso=True, titulo="Tu prueba gratis terminó",
                     mensaje=f"Ya se usaron las {limite} canciones gratis. "
                             "Adquiere tu plan para seguir con PlayBar GO.")
    else:  # vencido / suspendido
        r.update(estado="vencido", permitido=False, aviso=True, titulo="Servicio suspendido",
                 mensaje="Adquiere tu plan para seguir con PlayBar GO.")
    return r


def puede_pedir(codigo):
    """(True, "") o (False, mensaje para el cliente del bar)."""
    try:
        e = estado(codigo)
    except Exception as ex:  # si la base falla aquí, no se le corta la música a nadie
        print("⚠️ suscripción:", ex)
        return True, ""
    if e["permitido"]:
        return True, ""
    return False, ("Este lugar no tiene un plan activo de PlayBar GO en este momento. "
                   "Pide al administrador del lugar que active su plan.")


# ---------------------------------------------------------------------------
# Planes
# ---------------------------------------------------------------------------
def planes(todos=False):
    if todos:
        return db.consultar("SELECT * FROM planes ORDER BY orden, precio, id")
    return db.consultar("SELECT * FROM planes WHERE activo ORDER BY orden, precio, id")


def planes_para(codigo):
    """Los planes que ese negocio puede comprar (los de "solo_para" son de prueba/especiales)."""
    codigo = str(codigo).strip()
    return [p for p in planes()
            if not p["solo_para"].strip()
            or codigo in [x.strip() for x in p["solo_para"].split(",")]]


def plan(id_plan):
    return db.uno("SELECT * FROM planes WHERE id = %s", (int(id_plan),))


def guardar_plan(id_plan, nombre, precio, dias, activo=True, solo_para="", orden=0):
    if id_plan:
        return db.uno(
            """UPDATE planes SET nombre = %s, precio = %s, dias = %s, activo = %s,
               solo_para = %s, orden = %s WHERE id = %s RETURNING *""",
            (str(nombre).strip(), int(precio), int(dias), bool(activo),
             str(solo_para or "").replace(" ", ""), int(orden), int(id_plan)))
    return db.uno(
        """INSERT INTO planes (nombre, precio, dias, activo, solo_para, orden)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
        (str(nombre).strip(), int(precio), int(dias), bool(activo),
         str(solo_para or "").replace(" ", ""), int(orden)))


# ---------------------------------------------------------------------------
# Lo que hace el super administrador
# ---------------------------------------------------------------------------
def poner_estado(codigo, nuevo, dias=None, limite=None, reiniciar_prueba=False):
    nuevo = str(nuevo).strip().lower()
    if nuevo not in ESTADOS:
        raise ValueError(f"Estado no válido: {nuevo}")
    sets, params = ["plan_estado = %s"], [nuevo]
    if nuevo == "activo" and dias:
        c = db.cliente(codigo) or {}
        base = max(time.time(), float(c.get("plan_vence") or 0)) \
            if c.get("plan_estado") == "activo" else time.time()
        sets.append("plan_vence = %s")
        params.append(base + int(dias) * 86400)
        sets.append("plan_nombre = COALESCE(NULLIF(plan_nombre, ''), 'Plan manual')")
    if limite is not None:
        sets.append("prueba_limite = %s")
        params.append(max(0, int(limite)))
    if reiniciar_prueba:
        sets.append("prueba_desde = %s")
        params.append(time.time())
    params.append(str(codigo))
    return db.uno(f"UPDATE clientes SET {', '.join(sets)} WHERE codigo = %s RETURNING *",
                  tuple(params))


# ---------------------------------------------------------------------------
# Pagos (órdenes)
# ---------------------------------------------------------------------------
def crear_orden(codigo, id_plan):
    p = plan(id_plan)
    if not p or not p["activo"]:
        raise ValueError("Ese plan no está disponible.")
    if p not in planes_para(codigo):
        raise ValueError("Ese plan no está disponible para este negocio.")
    ref = f"PBG-{codigo}-{int(time.time())}-{secrets.token_hex(3).upper()}"
    return db.uno(
        """INSERT INTO pagos (referencia, codigo, plan_id, plan_nombre, monto, dias, creado)
           VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING *""",
        (ref, str(codigo), p["id"], p["nombre"], int(p["precio"]), int(p["dias"]), time.time()))


def orden(referencia):
    return db.uno("SELECT * FROM pagos WHERE referencia = %s", (str(referencia),))


def pagos(codigo=None, limite=200):
    if codigo:
        return db.consultar("SELECT * FROM pagos WHERE codigo = %s ORDER BY creado DESC LIMIT %s",
                            (str(codigo), int(limite)))
    return db.consultar("SELECT * FROM pagos ORDER BY creado DESC LIMIT %s", (int(limite),))


def pendientes(horas=48):
    return db.consultar("SELECT * FROM pagos WHERE estado = 'PENDIENTE' AND creado >= %s "
                        "ORDER BY creado", (time.time() - horas * 3600,))


def aplicar_aprobado(referencia, id_transaccion=""):
    """Activa (o alarga) el plan. Idempotente: si Wompi avisa dos veces, se aplica una."""
    o = db.uno(
        """UPDATE pagos SET estado = 'APROBADO', id_transaccion = %s, pagado = %s
           WHERE referencia = %s AND estado <> 'APROBADO' RETURNING *""",
        (str(id_transaccion or ""), time.time(), str(referencia)))
    if not o:
        return orden(referencia)  # ya estaba aplicado
    c = db.cliente(o["codigo"]) or {}
    ahora = time.time()
    base = ahora
    if c.get("plan_estado") == "activo" and float(c.get("plan_vence") or 0) > ahora:
        base = float(c["plan_vence"])  # renovó antes de vencer: se suman los días
    db.ejecutar("UPDATE clientes SET plan_estado = 'activo', plan_vence = %s, plan_nombre = %s "
                "WHERE codigo = %s", (base + int(o["dias"]) * 86400, o["plan_nombre"], o["codigo"]))
    print(f"💳 Pago APROBADO {o['referencia']}: {o['codigo']} +{o['dias']} días ({o['monto']} COP)")
    return o


def marcar_orden(referencia, estado_nuevo, id_transaccion=""):
    db.ejecutar("UPDATE pagos SET estado = %s, id_transaccion = %s "
                "WHERE referencia = %s AND estado = 'PENDIENTE'",
                (str(estado_nuevo), str(id_transaccion or ""), str(referencia)))


# ---------------------------------------------------------------------------
# Enlace de pago sin contraseña (para el botón del reproductor)
# ---------------------------------------------------------------------------
def token_pago(cli):
    firma = hmac.new(str(cli["llave"]).encode(), f"pago:{cli['codigo']}".encode(),
                     hashlib.sha256).hexdigest()[:24]
    return f"{cli['codigo']}.{firma}"


def cliente_de_token(token):
    try:
        codigo, _ = str(token).split(".", 1)
    except ValueError:
        return None
    c = db.cliente(codigo)
    if c and c.get("llave") and hmac.compare_digest(token_pago(c), str(token)):
        return c
    return None
