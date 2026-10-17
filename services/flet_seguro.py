"""
Blindaje de la conexión web de Flet (app web en Railway).

En Flet 1.0, si al servidor le llega la respuesta tardía de un control que ya no está en
pantalla (p. ej. un "desplazar" o una lectura del almacenamiento después de cambiar de
vista), lanza un error DENTRO del bucle que recibe los mensajes de esa pestaña: el bucle
se cierra y la app queda congelada ("se traba") hasta recargar.

Aquí:
  - una respuesta tardía de un control que ya no existe se ignora (no es un error);
  - cualquier otro error al procesar UN mensaje se anota en el registro y la pestaña
    sigue funcionando.
"""


def aplicar():
    try:
        from flet.messaging import session as _sesion
    except Exception as ex:
        print(f"ℹ️ flet_seguro: no se pudo revisar la sesión de Flet: {ex}")
        return

    original_resultados = _sesion.Session.handle_invoke_method_results
    if getattr(original_resultados, "_playbar_seguro", False):
        return

    def resultados_seguros(self, control_id, call_id, result, error):
        try:
            return original_resultados(self, control_id, call_id, result, error)
        except RuntimeError:
            print(f"ℹ️ Respuesta tardía ignorada (control {control_id} ya no está en pantalla)")
            return None

    resultados_seguros._playbar_seguro = True
    _sesion.Session.handle_invoke_method_results = resultados_seguros

    try:
        from flet_web.fastapi import flet_app as _app
    except Exception:
        return  # app de escritorio: no hay servidor web
    nombre = "_FletApp__on_message"
    original_mensaje = getattr(_app.FletApp, nombre, None)
    if original_mensaje is None or getattr(original_mensaje, "_playbar_seguro", False):
        return

    async def mensaje_seguro(self, data):
        try:
            return await original_mensaje(self, data)
        except Exception as ex:
            print(f"⚠️ Mensaje de la pestaña con error (la pestaña sigue): {type(ex).__name__}: {ex}")

    mensaje_seguro._playbar_seguro = True
    setattr(_app.FletApp, nombre, mensaje_seguro)

    # Si el celular corta la conexión justo mientras se le envían datos (p. ej. los
    # resultados de una búsqueda), Flet sale con error sin marcar la sesión como
    # desconectada: queda "conectada" a una conexión muerta, no vence nunca y al volver
    # el celular no la puede retomar. Aquí se cierra esa conexión y se sigue como una
    # desconexión normal.
    nombre_envio = "_FletApp__send_loop"
    original_envio = getattr(_app.FletApp, nombre_envio, None)
    if original_envio is not None and not getattr(original_envio, "_playbar_seguro", False):
        async def envio_seguro(self):
            try:
                return await original_envio(self)
            except Exception as ex:
                print(f"ℹ️ Conexión cortada mientras se enviaban datos ({type(ex).__name__})")
            ws = getattr(self, "_FletApp__websocket", None)
            try:
                if ws is not None:
                    await ws.close()
            except Exception:
                pass
            cola = getattr(self, "_FletApp__send_queue", None)
            while cola is not None and await cola.get() is not None:
                pass  # lo pendiente ya no tiene a quién llegar
            self._FletApp__websocket = None
            self._FletApp__send_queue = None

        envio_seguro._playbar_seguro = True
        setattr(_app.FletApp, nombre_envio, envio_seguro)

    # Entre el corte y el aviso de "desconectada", un page.update() no debe fallar.
    original_enviar = _app.FletApp.send_message
    if not getattr(original_enviar, "_playbar_seguro", False):
        def enviar_seguro(self, message):
            if getattr(self, "_FletApp__send_queue", None) is None:
                return
            return original_enviar(self, message)

        enviar_seguro._playbar_seguro = True
        _app.FletApp.send_message = enviar_seguro
    print("🛡️ Conexión web de Flet blindada")
