import os
import threading
import time

def iniciar_backend():
    """
    Arranca el backend Flask en localhost dentro del mismo contenedor que Flet.
    El puerto público de Railway queda reservado para Flet.
    """
    from backend.main import app

    port = int(os.environ.get("PLAYBAR_BACKEND_PORT", "5000"))

    def _run():
        print(f"🔧 Backend interno iniciando en 127.0.0.1:{port}")
        app.run(
            host="127.0.0.1",
            port=port,
            debug=False,
            use_reloader=False,
            threaded=True,
        )

    hilo = threading.Thread(
        target=_run,
        name="PlayBarBackend",
        daemon=True,
    )
    hilo.start()

    # Dar un pequeño margen para que Flask abra el puerto antes de la primera petición.
    time.sleep(0.5)
    print("✅ Backend interno iniciado")

    return hilo
