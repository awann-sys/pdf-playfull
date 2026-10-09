// Cloudflare Worker for https://awanhujan.web.id/pdf/
// Route this worker on both awanhujan.web.id/pdf and awanhujan.web.id/pdf/*.
// Render remains the backend; requests stream through Cloudflare.
// Opsional: atur variable RENDER_ORIGIN di Cloudflare Worker Settings > Variables
// bila URL Render baru berbeda dari contoh di bawah.
const DEFAULT_RENDER_ORIGIN = 'https://pdf-playfull.onrender.com';
const PREFIX = '/pdf';

export default {
  async fetch(request, env) {
    const RENDER_ORIGIN = (env && env.RENDER_ORIGIN) || DEFAULT_RENDER_ORIGIN;
    const incoming = new URL(request.url);
    if (incoming.pathname === PREFIX) {
      // Normalisasi trailing slash untuk tautan relatif: ./advanced.html
      return Response.redirect(`${incoming.origin}${PREFIX}/${incoming.search}`, 308);
    }
    if (!incoming.pathname.startsWith(PREFIX + '/')) {
      return new Response('Not found', {status: 404});
    }
    const upstream = new URL(RENDER_ORIGIN);
    upstream.pathname = incoming.pathname.slice(PREFIX.length) || '/';
    upstream.search = incoming.search;

    // Jangan bocorkan cookie website utama kepada aplikasi Render.
    const forwardedRequest = new Request(upstream.toString(), request);
    forwardedRequest.headers.delete('Cookie');
    forwardedRequest.headers.delete('Authorization');
    forwardedRequest.headers.delete('Host');
    forwardedRequest.headers.set('X-Forwarded-Prefix', PREFIX);
    const upstreamResponse = await fetch(forwardedRequest, {redirect: 'manual'});
    const responseHeaders = new Headers(upstreamResponse.headers);
    responseHeaders.delete('Set-Cookie');

    // Jika origin memberi redirect ke dirinya, arahkan kembali ke subpath publik.
    const loc = responseHeaders.get('Location');
    if (loc) {
      const target = new URL(loc, upstream);
      if (target.origin === upstream.origin) {
        responseHeaders.set('Location', `${incoming.origin}${PREFIX}${target.pathname}${target.search}${target.hash}`);
      }
    }
    // Respons dokumen pengguna tidak boleh tercache sebagai file publik.
    responseHeaders.set('Cache-Control', 'private, no-store');
    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      statusText: upstreamResponse.statusText,
      headers: responseHeaders
    });
  }
};
