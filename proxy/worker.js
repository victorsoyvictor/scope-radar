// CORS relay for the ADS-B feeds — a Cloudflare Worker (free tier is plenty).
//
// Why this exists: the public feeds answer a browser fine, but send no
// Access-Control-Allow-Origin header, so the browser fetches the bytes and then
// refuses to hand them to the page — DevTools shows "CORS Missing Allow Origin".
// A static site (GitHub Pages) has no server of its own to get around that.
// This Worker fetches the feed server-side, where the same-origin policy does
// not apply, and echoes the response back with the header attached.
//
// Deploy (about two minutes, no card needed):
//   1. dash.cloudflare.com -> Workers & Pages -> Create -> Worker
//   2. paste this file, Deploy
//   3. put the resulting URL in RELAY near the top of web/radar.html, e.g.
//      const RELAY="https://scope-relay.<you>.workers.dev/?url=";
//
// Or with wrangler:  npx wrangler deploy proxy/worker.js --name scope-relay
//
// It is deliberately NOT an open proxy: only the hosts below can be fetched, so
// nobody can point it at arbitrary URLs and use your account as a relay.

const ALLOWED = new Set([
  "api.adsb.lol",
  "api.airplanes.live",
  "opendata.adsb.fi",
  "api.adsbdb.com",
]);

const UA = "scope-radar (personal, non-commercial)";
const CACHE_SECONDS = 4;          // feeds update ~1 Hz; this shields them from bursts

function cors(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Access-Control-Allow-Headers": "Accept",
    "Access-Control-Max-Age": "86400",
  };
}

function json(body, status, origin) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...cors(origin) },
  });
}

export default {
  async fetch(request) {
    const origin = request.headers.get("Origin") || "*";

    if (request.method === "OPTIONS") return new Response(null, { headers: cors(origin) });
    if (request.method !== "GET") return json({ error: "GET only" }, 405, origin);

    const target = new URL(request.url).searchParams.get("url");
    if (!target) return json({ error: "missing ?url=" }, 400, origin);

    let t;
    try { t = new URL(target); } catch { return json({ error: "malformed url" }, 400, origin); }
    if (t.protocol !== "https:") return json({ error: "https only" }, 400, origin);
    if (!ALLOWED.has(t.hostname)) return json({ error: "host not allowed: " + t.hostname }, 403, origin);

    let upstream;
    try {
      upstream = await fetch(t.toString(), {
        headers: { Accept: "application/json", "User-Agent": UA },
        cf: { cacheTtl: CACHE_SECONDS, cacheEverything: true },
      });
    } catch (e) {
      return json({ error: "upstream failed: " + e }, 502, origin);
    }

    // Pass the body straight through; only the CORS headers are ours.
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") || "application/json",
        "Cache-Control": "no-store",
        ...cors(origin),
      },
    });
  },
};
