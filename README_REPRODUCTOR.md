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
En la app: pantalla "¿Qué deseas hacer?" → **🔧 Administrador** → PIN (`ADMIN_PIN` en Railway).
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
- `ADMIN_PIN` — PIN del administrador.
- `MODO_REPRODUCTOR=propio` — activa el reproductor propio (canciones directo a la cola). Sin esta variable la app sigue como antes, con la playlist de YouTube.
- `DUPLICADO_HORAS` (12) — una canción pedida hace más de esto se puede volver a pedir.
- `COLA_MAX_HORAS` (12) — canciones en cola más viejas que esto no se reproducen.
