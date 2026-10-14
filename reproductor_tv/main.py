"""PlayBar GO TV: reproductor para Android TV, Google TV, Fire TV y TV Box.

Probar en el PC:   py -3.12 probar_en_pc.py
Crear el .apk:     py -3.12 construir_apk.py
Publicar código:   py -3.12 publicar_tv.py 0.1.1   (los TV se actualizan solos)
"""
import flet as ft

import arranque

arranque.elegir_codigo()          # código del .apk o la versión descargada más nueva
from tv.app_tv import preparar    # noqa: E402  (va después de elegir el código)

preparar()                        # registro y yt-dlp al día (una sola vez)
ft.run(arranque.main, assets_dir="assets")
