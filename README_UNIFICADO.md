# PlayBar GO — Flet + Bot unificados

Este repositorio conserva **Flet como aplicación principal**.

## Estructura

- `main.py` y `views/` → aplicación Flet.
- `services/` → cliente API y sesión.
- `assets/` → recursos visuales.
- `backend/` → backend Flask del proyecto Bot que alimenta PlayBar GO.

## Backend

El backend conserva los endpoints utilizados por el Flet:

- `GET /validar_cliente`
- `GET /buscar`
- `POST /`
- `GET /estado_usuario`
- `GET /estado_cola`
- `GET /mis_canciones`
- `GET /top`

El Flet actualmente consume el backend publicado en:

`https://jukebox-bot-production.up.railway.app`

Por eso **no se cambia la URL del Flet ni se sustituye la aplicación Flet por Flask**.

## Credenciales

Los archivos de credenciales y tokens no se incluyen en este ZIP.
Para Railway deben configurarse mediante variables de entorno del backend:

- `GOOGLE_CREDENTIALS_B64`
- `YOUTUBE_TOKEN1_B64`
- `YOUTUBE_TOKEN2_B64`
- `YOUTUBE_API_KEYS`

## Regla de despliegue

El servicio `jukebox-flet-production` debe seguir desplegando la aplicación Flet.
El backend puede seguir desplegado como servicio independiente mientras ambos comparten este repositorio.

## Próximo paso

La persistencia de sesión se debe probar sobre esta versión exacta del Flet antes de introducir cambios de URL/deep-link.
