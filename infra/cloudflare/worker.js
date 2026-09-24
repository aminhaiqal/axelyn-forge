export default {
  async fetch(request, env) {
    const publicUrl = new URL(request.url);
    const originUrl = new URL(request.url);

    originUrl.protocol = "http:";
    originUrl.hostname = "web";
    originUrl.port = "8080";

    const originRequest = new Request(originUrl, request);
    originRequest.headers.set("x-forwarded-host", publicUrl.host);
    originRequest.headers.set("x-forwarded-proto", "https");

    const clientIp = request.headers.get("cf-connecting-ip");
    if (clientIp) {
      originRequest.headers.set("x-forwarded-for", clientIp);
    }

    return env.FORGE_ORIGIN.fetch(originRequest);
  },
};
