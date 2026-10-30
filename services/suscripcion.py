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

# Lo de la PRUEBA de pagos (bar 9999 "Bar Demo Pagos" y plan de $3.000) ya se usó y se
# borra solo al arrancar. Los registros de pagos se conservan como historial.
DEMO_CODIGO = "9999"
DEMO_NOMBRE = "Bar Demo Pagos"


# ---------------------------------------------------------------------------
# Semillas: plan mensual (solo si no existe; se edita en /super) y limpieza de la prueba
# ---------------------------------------------------------------------------
def sembrar():
    db.ejecutar(
        """INSERT INTO planes (clave, nombre, precio, dias, activo, solo_para, orden)
           VALUES ('mensual', 'Plan mensual', 60000, 30, TRUE, '', 1)
           ON CONFLICT (clave) DO NOTHING""")
    db.ejecutar("DELETE FROM planes WHERE clave = 'prueba_pago'")
    demo = db.cliente(DEMO_CODIGO)
    if demo and demo.get("nombre") == DEMO_NOMBRE:  # solo el de prueba, nunca uno real
        for tabla in ("admins", "pedidos", "control", "logos"):
            db.ejecutar(f"DELETE FROM {tabla} WHERE codigo = %s", (DEMO_CODIGO,))
        db.ejecutar("DELETE FROM clientes WHERE codigo = %s", (DEMO_CODIGO,))
        print(f"🧹 Bar de prueba {DEMO_CODIGO} eliminado")


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
        es_prueba = r["plan_nombre"].lower().startswith("prueba")
        r["prueba_dias"] = es_prueba
        if vence > ahora and es_prueba:  # prueba por días (la crea el super admin)
            horas = int((vence - ahora) / 3600)
            queda = f"{horas} horas" if horas < 48 else f"{r['dias_restantes']} días"
            r.update(permitido=True, aviso=True, titulo=r["plan_nombre"],
                     mensaje=f"Prueba gratis hasta el {fecha_txt(vence)} (quedan {queda}). "
                             "Adquiere tu plan para no quedarte sin música.")
        elif es_prueba:
            r.update(estado="vencido", permitido=False, aviso=True, titulo="Tu prueba terminó",
                     mensaje="La prueba gratis terminó. Adquiere tu plan para seguir con "
                             "PlayBar GO.")
        elif vence > ahora:
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


def guardar_promo(id_plan, activa, texto="", precio=0, pagos=0, hasta=""):
    """La promoción de un plan (🔥 Promociones en /super)."""
    return db.uno(
        """UPDATE planes SET promo_activa = %s, promo_texto = %s, promo_precio = %s,
           promo_pagos = %s, promo_hasta = %s WHERE id = %s RETURNING *""",
        (bool(activa), str(texto or "").strip(), max(0, int(precio or 0)), max(0, int(pagos or 0)),
         str(hasta or "").strip(), int(id_plan)))


def promo_vigente(p):
    """True si la promoción del plan está prendida, bien armada y no se ha vencido."""
    promo, pagos = int(p.get("promo_precio") or 0), int(p.get("promo_pagos") or 0)
    if not (p.get("promo_activa") and promo and pagos and promo < int(p["precio"])):
        return False
    hasta = (p.get("promo_hasta") or "").strip()
    hoy = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 5 * 3600))  # hora de Colombia
    return not hasta or hoy <= hasta


# ---------------------------------------------------------------------------
# Promoción: los primeros N pagos de cada bar a precio especial
# ---------------------------------------------------------------------------
def pagos_hechos(codigo, id_plan):
    """Cuántos pagos aprobados de ese plan tiene el bar (para saber si sigue en promoción)."""
    if not codigo:
        return 0
    f = db.uno("SELECT COUNT(*) AS n FROM pagos WHERE codigo = %s AND plan_id = %s "
               "AND estado = 'APROBADO'", (str(codigo), int(id_plan)))
    return int((f or {}).get("n") or 0)


def precio_de(p, codigo=None):
    """Precio que paga ESTE bar por el plan `p`. Devuelve una copia de `p` con:
    precio (el que se cobra), precio_normal, en_promo, promo_quedan (pagos que le quedan a
    precio de promoción, contando este) y promo_txt (para mostrar)."""
    q = dict(p)
    normal = int(p["precio"])
    promo, n_promo = int(p.get("promo_precio") or 0), int(p.get("promo_pagos") or 0)
    q.update(precio_normal=normal, en_promo=False, promo_quedan=0, promo_txt="")
    if promo_vigente(p):
        hechos = pagos_hechos(codigo, p["id"])
        if hechos < n_promo:
            quedan = n_promo - hechos
            q.update(precio=promo, en_promo=True, promo_quedan=quedan)
            meses = "mes" if n_promo == 1 else f"{n_promo} meses"
            q["promo_txt"] = (f"Promoción: los primeros {meses} a {_pesos_txt(promo)}, "
                              f"luego {_pesos_txt(normal)}")
            if (p.get("promo_texto") or "").strip():
                q["promo_txt"] = f"{p['promo_texto'].strip()} · {q['promo_txt']}"
            if hechos:
                q["promo_txt"] += f" (te queda{'n' if quedan > 1 else ''} {quedan} a precio de promoción)"
    return q


def _pesos_txt(n):
    return "$" + f"{int(n):,}".replace(",", ".")


def planes_con_precio(codigo, lista=None):
    """Los planes que puede comprar el bar, con el precio que le toca (promoción incluida)."""
    return [precio_de(p, codigo) for p in (lista if lista is not None else planes_para(codigo))]


# ---------------------------------------------------------------------------
# Lo que hace el super administrador
# ---------------------------------------------------------------------------
def crear_prueba_dias(codigo, dias):
    """Prueba gratis por días (la da el super admin): música sin límite hasta que se
    cumplan los días; luego se corta sola y el bar ve "Tu prueba terminó"."""
    dias = max(1, min(30, int(dias or 2)))
    return db.uno("""UPDATE clientes SET plan_estado = 'activo', plan_vence = %s, plan_nombre = %s
                     WHERE codigo = %s RETURNING *""",
                  (time.time() + dias * 86400, f"Prueba {dias} días", str(codigo)))


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
        sets.append("plan_nombre = CASE WHEN plan_nombre = '' OR plan_nombre ILIKE 'prueba%%' "
                    "THEN 'Plan manual' ELSE plan_nombre END")
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
def crear_orden(codigo, id_plan, bono=""):
    """Orden PENDIENTE. Con `bono` (código de referido) el bono queda reservado a esta
    orden y el monto baja; el precio lo calcula siempre el servidor."""
    from services import bonos

    p = plan(id_plan)
    if not p or not p["activo"]:
        raise ValueError("Ese plan no está disponible.")
    if p not in planes_para(codigo):
        raise ValueError("Ese plan no está disponible para este negocio.")
    ref = f"PBG-{codigo}-{int(time.time())}-{secrets.token_hex(3).upper()}"
    b = None
    if bonos.normalizar(bono):
        _, msg = bonos.revisar(bono, codigo)
        b = None if msg else bonos.reservar(bono, ref, codigo)
        if not b:
            raise ValueError(msg or "Ese código de bono ya no está disponible.")
    monto, descuento = bonos.precio_con_bono(precio_de(p, codigo)["precio"], b)
    try:
        return db.uno(
            """INSERT INTO pagos (referencia, codigo, plan_id, plan_nombre, monto, dias, creado,
                                  bono, descuento)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
            (ref, str(codigo), p["id"], p["nombre"], monto, int(p["dias"]), time.time(),
             b["codigo"] if b else "", descuento))
    except Exception:
        bonos.liberar(ref)
        raise


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
    if o.get("bono"):
        from services import bonos
        bonos.usar(o)
        print(f"🎁 Bono {o['bono']} usado por {o['codigo']} (-{o.get('descuento', 0)} COP)")
    return o


def marcar_orden(referencia, estado_nuevo, id_transaccion=""):
    db.ejecutar("UPDATE pagos SET estado = %s, id_transaccion = %s "
                "WHERE referencia = %s AND estado = 'PENDIENTE'",
                (str(estado_nuevo), str(id_transaccion or ""), str(referencia)))
    from services import bonos
    bonos.liberar(referencia)  # pago rechazado/anulado: el bono vuelve a quedar libre


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
