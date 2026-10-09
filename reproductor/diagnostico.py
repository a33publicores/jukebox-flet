"""Verificaciones al abrir el reproductor. Cada una devuelve (ok, mensaje, solucion)."""
import os
import socket


def _internet():
    for host in (("8.8.8.8", 53), ("1.1.1.1", 53)):
        try:
            socket.create_connection(host, timeout=4).close()
            return True, "", ""
        except OSError:
            continue
    return False, "No hay conexión a internet.", "Conecta el PC a internet y vuelve a abrir el reproductor."


def _ffmpeg():
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return True, "", ""
    except Exception as ex:
        return False, f"Falta ffmpeg ({ex}).", "Reinstala el reproductor."
    return False, "Falta ffmpeg.", "Reinstala el reproductor."


def _servidor(api, cliente):
    from services.api_cliente import LlaveInvalida
    try:
        api.salud()
    except Exception as ex:
        return (False, f"No responde el servidor de PlayBar GO ({api.url}): {ex}",
                "Revisa la dirección del servidor (botón Cambiar código o llave) o espera un momento.")
    try:
        datos = api.config()
    except LlaveInvalida:
        return (False, "La llave del bar no es válida (o el negocio está inactivo).",
                "Pide la llave actual al super administrador y escríbela con 'Cambiar código o llave'.")
    except Exception as ex:
        return False, f"No se pudo leer la configuración del bar: {ex}", "Intenta de nuevo."
    if str(datos.get("codigo")) != str(cliente):
        return (False, f"La llave es del lugar {datos.get('codigo')}, no del {cliente}.",
                "Usa 'Cambiar código o llave'.")
    return True, "", ""


def revisar(api, cliente):
    """Devuelve la lista de problemas [(mensaje, solucion)]; vacía si todo está bien."""
    ok, m, s = _internet()
    if not ok:
        return [(m, s)]  # sin internet las demás no tienen sentido
    problemas = []
    for f in (_ffmpeg, lambda: _servidor(api, cliente)):
        ok, m, s = f()
        if not ok:
            problemas.append((m, s))
    return problemas
