// =============================================================
// PlayBar GO · canciones en la nube (Cloudflare R2)
// =============================================================
// Cada canción se guarda UNA vez (la sube el primer reproductor que la baja de YouTube)
// y los demás TV / PC la bajan de aquí: más rápido y sin depender de YouTube.
//
//   GET/HEAD /v/<archivo>.mp4?exp=<epoch>&sig=<firma>   baja la canción (acepta Range)
//   PUT      /v/<archivo>.mp4?exp=<epoch>&sig=<firma>   la sube (si ya existe, no la cambia)
//   DELETE   /v/<archivo>.mp4?exp=<epoch>&sig=<firma>   la borra (canción eliminada en /super)
//   GET      /salud                                       {"ok": true}
//
// Las direcciones las firma la API de PlayBar GO (solo a reproductores con llave válida):
//   sig = HMAC-SHA256(FIRMA, "<METODO>:<archivo>:<exp>") en hexadecimal; GET y HEAD usan "GET".
// Secreto (wrangler secret put FIRMA): el mismo valor que NUBE_FIRMA en la API.
// Almacenamiento: bucket R2 "playbar-canciones" (binding CANCIONES).
// =============================================================

const MAX_BYTES = 300 * 1024 * 1024; // un video musical en 720p pesa 20-120 MB
const ARCHIVO = /^[A-Za-z0-9_-]{6,20}(_\d{3,4})?\.mp4$/;

async function firmar(secreto, texto) {
    const llave = await crypto.subtle.importKey(
        "raw", new TextEncoder().encode(secreto), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
    const firma = await crypto.subtle.sign("HMAC", llave, new TextEncoder().encode(texto));
    return [...new Uint8Array(firma)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function igual(a, b) {
    if (a.length !== b.length) return false;
    let r = 0;
    for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
    return r === 0;
}

async function autorizado(env, metodo, archivo, url) {
    const exp = Number(url.searchParams.get("exp") || 0);
    const sig = String(url.searchParams.get("sig") || "");
    if (!env.FIRMA || !exp || exp < Date.now() / 1000 || !sig) return false;
    return igual(await firmar(env.FIRMA, `${metodo}:${archivo}:${exp}`), sig);
}

function rango(cabecera, tamano) {
    const m = /^bytes=(\d*)-(\d*)$/.exec(cabecera || "");
    if (!m) return null;
    let ini = m[1] === "" ? null : Number(m[1]);
    let fin = m[2] === "" ? null : Number(m[2]);
    if (ini === null && fin === null) return null;
    if (ini === null) { ini = Math.max(0, tamano - fin); fin = tamano - 1; }
    if (fin === null || fin >= tamano) fin = tamano - 1;
    if (ini > fin) return null;
    return { offset: ini, length: fin - ini + 1 };
}

export default {
    async fetch(request, env) {
        const url = new URL(request.url);
        if (url.pathname === "/salud") {
            return Response.json({ ok: true });
        }
        const m = /^\/v\/([^/]+)$/.exec(url.pathname);
        if (!m || !ARCHIVO.test(m[1])) {
            return new Response("No encontrado", { status: 404 });
        }
        const archivo = m[1];
        const clave = `v/${archivo}`;
        const metodo = request.method === "HEAD" ? "GET" : request.method;

        if (!(await autorizado(env, metodo, archivo, url))) {
            return new Response("Firma no válida o vencida", { status: 403 });
        }

        if (metodo === "GET") {
            const cabeza = await env.CANCIONES.head(clave);
            if (!cabeza) return new Response("No está en la nube", { status: 404 });
            const r = rango(request.headers.get("range"), cabeza.size);
            const comunes = {
                "content-type": "video/mp4",
                "accept-ranges": "bytes",
                "cache-control": "private, max-age=3600",
                "etag": cabeza.httpEtag,
            };
            if (request.method === "HEAD") {
                return new Response(null, { headers: { ...comunes, "content-length": String(cabeza.size) } });
            }
            if (r) {
                const obj = await env.CANCIONES.get(clave, { range: r });
                return new Response(obj.body, {
                    status: 206,
                    headers: {
                        ...comunes,
                        "content-length": String(r.length),
                        "content-range": `bytes ${r.offset}-${r.offset + r.length - 1}/${cabeza.size}`,
                    },
                });
            }
            const obj = await env.CANCIONES.get(clave);
            return new Response(obj.body, { headers: { ...comunes, "content-length": String(cabeza.size) } });
        }

        if (metodo === "PUT") {
            const largo = Number(request.headers.get("content-length") || 0);
            if (!largo || largo > MAX_BYTES) {
                return new Response("Tamaño no válido", { status: 413 });
            }
            if (await env.CANCIONES.head(clave)) {
                return Response.json({ ok: true, ya: true }); // otro reproductor la subió primero
            }
            await env.CANCIONES.put(clave, request.body, {
                httpMetadata: { contentType: "video/mp4" },
            });
            return Response.json({ ok: true });
        }

        if (metodo === "DELETE") {
            // el super administrador eliminó la canción (no sirve): la API firma el borrado
            await env.CANCIONES.delete(clave);
            return Response.json({ ok: true });
        }

        return new Response("Método no permitido", { status: 405 });
    },
};
