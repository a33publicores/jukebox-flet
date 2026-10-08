# Reproductor propio PlayBar GO (todo en Python)

## Cómo funciona
1. El cliente busca en la app (la búsqueda sigue usando YouTube) y la canción entra a la
   hoja del lugar como `Estado = Agregado`, `Estado2 = En cola`. **Ya no se usa el token
   de YouTube para agregar a una playlist.**
2. El reproductor del PC lee la hoja cada 3 s (una sola petición), descarga la canción con
   yt-dlp a `~/PlayBarGo/cache` y la reproduce. Las que siguen se precargan.
3. Si no hay cola, suena una canción de la pestaña **REPRODUCIDAS** (se crea sola y la
   primera vez se llena con lo que ya pidieron en esa hoja). Si llega un pedido mientras
   suena relleno, entra de inmediato; si suena una canción pedida, la nueva espera su turno.
4. Estados en la hoja: `En cola` → `En reproduccion` → `Reproducido` (o `Eliminado` / `Error`).
   Las filas viejas (Agregado sin Estado2) se consideran historial y no se reproducen.

## Administrador
En la app: pantalla "¿Qué deseas hacer?" → **🔧 Administrador** → usuario y contraseña de la pestaña **ADMINS** de la hoja.
Muestra qué suena y qué sigue, la playlist (con 🗑 para quitar) y los botones
⏮ ⏯ ⏭. Los comandos viajan por la pestaña **CONTROL**; el reproductor los ejecuta en ~3 s.

## Instalar el reproductor (Windows)
1. Copia la carpeta del proyecto al PC del bar.
2. Pon junto a `reproductor.py` el archivo `credenciales.json` (o define `GOOGLE_CREDENTIALS_B64`).
3. Doble clic en `INICIAR_REPRODUCTOR.bat`. La primera vez pide el código del lugar (ej. 8523).
4. Teclas: Espacio pausa · → siguiente · ← anterior · F pantalla completa.

Si YouTube pide verificación al descargar, exporta las cookies a `~/PlayBarGo/cookies.txt`
(o variable `YTDLP_COOKIES`).

## Variables de Railway
- `ADMIN_USER` / `ADMIN_PASS` — usuario y contraseña del administrador (`ADMIN_PIN` solo como respaldo).
- `MODO_REPRODUCTOR=propio` — activa el reproductor propio (canciones directo a la cola). Sin esta variable la app sigue como antes, con la playlist de YouTube.
- `DUPLICADO_HORAS` (12) — una canción pedida hace más de esto se puede volver a pedir.
- `COLA_MAX_HORAS` (12) — canciones en cola más viejas que esto no se reproducen.


## v17.1 — Reproductor instalable (.exe)
- **Administrador:** usuario y contraseña en Railway: `ADMIN_USER` y `ADMIN_PASS` (el `ADMIN_PIN` viejo sigue sirviendo solo si no pones esas dos).
- **Crear el .exe:** doble clic en `CONSTRUIR_EXE.bat` (en tu PC). Genera `dist\PlayBarGO_Reproductor.exe` y, con Inno Setup 6 instalado, `instalador\Output\PlayBarGO_Reproductor_Setup.exe`.
- **credenciales.json:** ponlo junto al .exe (o en la carpeta del proyecto antes de crear el instalador).
- **Actualizaciones:** al abrir, el reproductor lee `reproductor_version.json` del repo (rama main). Para avisar una versión nueva: sube el nuevo Setup.exe (p. ej. a GitHub Releases), cambia `version` y `url` en ese JSON, súbelo al repo. Al abrir, sale la ventana con **Descargar**. Con `"obligatoria": true` no se puede cerrar. Sube también `VERSION` en `reproductor/version.py` y `--product-version`/`#define Version` antes de compilar.
- **Verificaciones:** al abrir revisa internet, ffmpeg, credenciales y el código del lugar, y muestra qué falla y cómo arreglarlo.


## v18.1 — Admins en la hoja y .exe arreglado
- **Administradores:** pestaña **ADMINS** de la hoja Jukebox (se crea sola la primera vez que alguien abre el admin).
  Columnas: `Codigo | Usuario | Clave | Activo | Nota`. `Codigo` = código del lugar (ej. 8523) o `*` para un admin de todos los lugares.
  `Activo` en FALSE desactiva sin borrar. Los cambios valen en ~30 s, sin redeploy. `ADMIN_USER`/`ADMIN_PASS` de Railway quedan como respaldo.
- **.exe:** `CONSTRUIR_EXE.bat` usa Python 3.12 (python.org) y compila en modo carpeta: `dist\PlayBarGO_Reproductor\PlayBarGO_Reproductor.exe`. Copia la carpeta completa, no solo el .exe.
- **credenciales.json:** se busca en `%USERPROFILE%\PlayBarGo`, junto al .exe y en la carpeta padre del proyecto. El build lo copia solo si está en el proyecto o en `D:\Python\Musica`.

## v18.2 — Sin playlist de YouTube, cola por fecha
- Al elegir una canción en la app se guarda directo en la hoja: `Estado = Agregado`, `Estado2 = Siguiente`, con la **hora de Colombia** en Timestamp. Ya no pasa por la playlist de YouTube (para volver al modo viejo: `MODO_REPRODUCTOR=youtube` en Railway).
- **Cola = lo pedido HOY** (desde las 6 a. m.; cambia con `JORNADA_HORA`, 0 = medianoche). Lo pedido de madrugada sigue contando para la misma noche.
- **Aleatorio = canciones de fechas anteriores**. Cuando alguien agrega, esa suena; cuando la cola se vacía, vuelve el aleatorio.
- Al abrir, el reproductor pasa a `Reproducido` las filas viejas que quedaron "En reproduccion" o "Siguiente".
- `INTERRUMPIR_RELLENO=0` (variable de Windows) hace que la canción pedida espere a que termine la aleatoria en vez de entrar apenas se descarga.
