const MAX_OBJECT_BYTES = 12 * 1024 * 1024;

function unauthorized() {
  return new Response("Unauthorized", {
    status: 401,
    headers: { "Cache-Control": "no-store" },
  });
}

async function verifyToken(provided, expected) {
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return crypto.subtle.timingSafeEqual(providedHash, expectedHash);
}

function objectKey(request) {
  const url = new URL(request.url);
  const prefix = "/objects/";
  if (!url.pathname.startsWith(prefix)) return null;
  let key;
  try {
    key = decodeURIComponent(url.pathname.slice(prefix.length));
  } catch {
    return null;
  }
  const parts = key.split("/");
  if (
    !key.startsWith("users/") ||
    parts.some((part) => !part || part === "." || part === "..")
  ) {
    return null;
  }
  return key;
}

export default {
  async fetch(request, env) {
    try {
      const authenticated = await verifyToken(
        request.headers.get("Authorization") || "",
        `Bearer ${env.FORGE_STORAGE_TOKEN}`,
      );
      if (!authenticated) return unauthorized();
      const key = objectKey(request);
      if (!key) return new Response("Not found", { status: 404 });

      if (request.method === "PUT") {
        const declaredSize = Number(request.headers.get("Content-Length") || "0");
        if (declaredSize > MAX_OBJECT_BYTES) {
          return new Response("Object too large", { status: 413 });
        }
        const payload = await request.arrayBuffer();
        if (payload.byteLength > MAX_OBJECT_BYTES) {
          return new Response("Object too large", { status: 413 });
        }
        await env.PRIVATE_RESUMES.put(key, payload, {
          httpMetadata: {
            contentType: request.headers.get("Content-Type") || "application/octet-stream",
          },
        });
        return new Response(null, { status: 204 });
      }

      if (request.method === "GET") {
        const object = await env.PRIVATE_RESUMES.get(key);
        if (!object) return new Response("Not found", { status: 404 });
        const headers = new Headers();
        object.writeHttpMetadata(headers);
        headers.set("Cache-Control", "private, no-store");
        headers.set("X-Content-Type-Options", "nosniff");
        headers.set("ETag", object.httpEtag);
        return new Response(object.body, { headers });
      }

      if (request.method === "DELETE") {
        await env.PRIVATE_RESUMES.delete(key);
        return new Response(null, { status: 204 });
      }

      return new Response("Method not allowed", {
        status: 405,
        headers: { Allow: "GET, PUT, DELETE" },
      });
    } catch (error) {
      console.error(JSON.stringify({
        message: "private storage request failed",
        method: request.method,
        error: error instanceof Error ? error.message : "Unknown error",
      }));
      return Response.json({ error: "Internal server error" }, { status: 500 });
    }
  },
};
