# PlayBar GO TV — reproductor para televisores

Código **separado** del reproductor de Windows (`../reproductor/`). Usa la misma API
(`playbar-api`), la misma llave del bar y las mismas reglas de cola, relleno y géneros.

Sirve en: **Android TV, Google TV (Chromecast), Fire TV Stick y TV Box Android**.
Para Samsung (Tizen) o LG (webOS): conectarles un Chromecast con Google TV, un Fire TV
Stick o un TV Box.

## Estructura

```
reproductor_tv/
├── main.py              inicio de la app
├── arranque.py          elige el código (el del .apk o uno actualizado) y lo recarga
├── publicar_tv.py       publica una actualización del código para todos los TV
├── pyproject.toml       configuración del .apk (com.a33.playbargo.tv)
├── construir_apk.py     crea el .apk  (CONSTRUIR_APK.bat)
├── PROBAR_EN_PC.bat     lo abre en el PC para probar
├── assets/              logo, ícono, splash y banner del TV
└── tv/
    ├── app_tv.py        pantalla para TV + control remoto
    ├── actualizador_tv.py  revisa GitHub y baja el código nuevo
    ├── motor.py         copia de reproductor/motor.py (solo cambian imports y textos)
    ├── descargas_tv.py  yt-dlp SIN ffmpeg + limpieza de memoria del TV
    ├── unir_mp4.py      une video y audio en un .mp4 (Python puro, sin ffmpeg)
    ├── api_cliente.py   copia de services/api_cliente.py
    ├── cola.py          modelo de la cola (sin base de datos)
    ├── generos.py       copia de services/generos.py
    ├── config.py        carpeta de datos y configuración
    └── version.py
```

> Si cambias las reglas en `reproductor/motor.py` o `services/generos.py`, copia el
> cambio también aquí.

## 1. Probar en el PC

Doble clic en `PROBAR_EN_PC.bat`. Las flechas y Enter del teclado hacen lo mismo que
el control remoto. Los datos quedan en `%USERPROFILE%\PlayBarGoTV` (no se mezclan con
los del reproductor .exe).

## 2. Crear el .apk

Doble clic en `CONSTRUIR_APK.bat`. La primera vez Flet descarga Flutter, el SDK de
Android y Java (tarda bastante). Resultado:

```
reproductor_tv\salida_apk\PlayBarGO_TV.apk
```

Es un solo .apk que sirve en todos los TV (32 y 64 bits). Va firmado con la llave de
pruebas de este PC: **crea siempre las versiones nuevas desde este mismo PC**; si no,
el TV no deja actualizar y toca desinstalar primero.

## 3. Instalar en el TV

No va en Google Play (Google no acepta apps que descarguen de YouTube). Se instala a mano:

1. En el TV: **Ajustes → Dispositivo / Mi Fire TV → Opciones de desarrollador** y
   activa *Fuentes desconocidas* (o *Apps de origen desconocido*) para la app que usarás.
   En Google TV primero toca 7 veces *Ajustes → Sistema → Acerca de → Compilación del SO*.
2. Instala la app **Downloader** (de AFTVnews) desde la tienda del TV.
3. Sube `PlayBarGO_TV.apk` a una URL (por ejemplo, como archivo de un Release de GitHub)
   y escribe esa URL en Downloader. También sirve una memoria USB con un explorador
   de archivos.
4. Abre **PlayBar GO TV**, escribe el código del lugar y la llave del bar (la misma del
   reproductor .exe).

## Control remoto

| Botón | Acción |
|---|---|
| OK / ▶❚❚ | pausar / reanudar |
| ▶ derecha / ⏭ | siguiente canción |
| ◀ izquierda / ⏮ | canción anterior |
| ▲ ▼ / Menú | menú: pausar, siguiente, anterior, cambiar código, ver registro |

Las teclas que la app no reconoce quedan anotadas en el registro (menú → *Ver registro*).
Si un control tiene botones distintos, se agregan en `T_PAUSA`, `T_SIGUIENTE`, etc.
de `tv/app_tv.py`.

## Diferencias con el reproductor del PC

- **Calidad:** 720p, igual que el PC. Video y audio se unen con `unir_mp4.py` en vez de ffmpeg.
- **Memoria (solo TV):** las canciones quedan guardadas en la memoria interna del TV. Cuando
  quedan menos de 1,2 GB libres se borran las que hace más tiempo no suenan, hasta volver a
  1,6 GB. Nunca se borra lo que sonó o se bajó en las últimas 3 horas. Si alguien pide una
  borrada, se vuelve a bajar. (El reproductor del PC NO borra nada.)
- **Pago del plan:** muestra el enlace en pantalla para abrirlo en el celular.
- **Sin** tabla de pedidos, Excel ni arrastrar para reordenar (eso se hace desde la app).
- **Actualizaciones:** ver abajo. yt-dlp también se actualiza solo cada 2 días.

## Actualizaciones automáticas

Los TV se actualizan solos, sin reinstalar el .apk ni tocar nada en el bar.

```
py -3.12 publicar_tv.py 0.1.1
```

1. Cambia la versión en `tv/version.py` y crea `salida_apk/tv_codigo.zip` (carpeta `tv/`).
2. Lo publica en GitHub como release **`tv-v0.1.1` marcada como pre-release**. Si tienes
   `gh` (GitHub CLI) con sesión iniciada lo hace solo; si no, abre GitHub con todo lleno y
   solo arrastras el .zip y das *Publish release*. Al ser pre-release, el reproductor del PC
   no la ve.
3. Cada TV revisa al abrir y cada 3 horas: baja el .zip, revisa que esté completo y sin
   errores, avisa en pantalla y se recarga al terminar la canción. Con una línea `[ahora]`
   en la descripción de la release se instala sin esperar la canción.

Si la versión nueva no carga, o la app se cierra 3 veces seguidas antes de funcionar
90 segundos, el TV vuelve solo a la última versión que funcionó (o a la del .apk).

**Esto actualiza solo la carpeta `tv/`.** Si cambias `main.py`, `arranque.py`,
`pyproject.toml`, `assets/` o agregas librerías, hay que crear e instalar un .apk nuevo.
