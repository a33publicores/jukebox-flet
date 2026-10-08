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


def _hoja(cliente):
    from services import playbar_service as ps
    try:
        ps._spreadsheet_obj()
    except FileNotFoundError:
        from pathlib import Path
        carpeta = os.environ.get("PLAYBAR_HOME", str(Path.home() / "PlayBarGo"))
        return (False, "No se encontró credenciales.json.",
                f"Copia credenciales.json en {carpeta} (botón Abrir carpeta) y pulsa Reintentar.")
    except Exception as ex:
        txt = str(ex)
        if "invalid_grant" in txt or "account not found" in txt:
            return (False, "La llave de credenciales.json ya no es válida (cuenta de servicio borrada o llave revocada).",
                    "Usa el credenciales.json actual (el mismo de Railway) o crea una llave nueva en Google Cloud.")
        return False, f"No se pudo abrir la hoja de Google: {ex}", \
            "Revisa internet y que la hoja esté compartida con la cuenta de servicio."
    try:
        if not ps.obtener_config_cliente(cliente):
            return (False, f"El código {cliente} no existe en la pestaña CLIENTES.",
                    "Borra reproductor_config.json (carpeta PlayBarGo del usuario) para escribir otro código.")
    except Exception as ex:
        return False, f"No se pudo leer CLIENTES: {ex}", "Intenta de nuevo en unos segundos."
    return True, "", ""


def revisar(cliente):
    """Devuelve la lista de problemas [(mensaje, solucion)]; vacía si todo está bien."""
    problemas = []
    ok, m, s = _internet()
    if not ok:
        return [(m, s)]  # sin internet las demás no tienen sentido
    for f in (_ffmpeg, lambda: _hoja(cliente)):
        ok, m, s = f()
        if not ok:
            problemas.append((m, s))
            if "credenciales" in m:
                break
    return problemas
