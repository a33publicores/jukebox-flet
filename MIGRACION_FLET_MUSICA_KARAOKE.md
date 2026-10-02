# PlayBar GO — Flet unificado Música + Karaoke

Migración del cliente Flet actual con las funciones del proyecto PlayBarGo.

## Arquitectura
- Flet como aplicación única.
- Música: búsqueda YouTube + Google Sheets + procesamiento de playlist.
- Karaoke: scanner/cola/búsqueda heredados del proyecto PlayBarGo.
- Sesión persistente en el dispositivo.
- Sin Flask/Bot como dependencia de ejecución.

## Variables Railway
- GOOGLE_CREDENTIALS_B64
- YOUTUBE_API_KEYS
- YOUTUBE_TOKEN1_B64
- YOUTUBE_TOKEN2_B64
- FLET_FORCE_WEB_SERVER
- FLET_SERVER_PORT

## Importante sobre Karaoke
El scanner heredado busca archivos de karaoke mediante `data/config.json` y una ruta local.
En Railway Web esa ruta pertenece al servidor, no al PC del cliente. Por tanto la UI y la cola
quedan migradas, pero el catálogo físico de archivos debe ubicarse en el entorno donde se
ejecute Karaoke (por ejemplo, una instalación local/desktop) o migrarse posteriormente a un
catálogo/almacenamiento accesible desde la aplicación.
