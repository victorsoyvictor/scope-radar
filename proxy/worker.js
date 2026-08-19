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
//   3. add the resulting URL to RELAYS near the top of web/radar.html, first in
//      the list so it is preferred over the public relays behind it:
//        {name:"worker", wrap:u=>"https://<you>.workers.dev/?url="+encodeURIComponent(u)},
//      Or try it without editing anything: ?relay=https://<you>.workers.dev/?url=
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

// The shield against hammering the feed lives here, in the isolate. A *.workers.dev
// subdomain ignores cf.cacheTtl and the Cache API — those only apply on a zone you
// own — so relying on them silently did nothing, every poll reached the feed, and
// adsb.lol started answering 429. An isolate serves many requests in a row, so a
// plain Map collapses repeated polls (several tabs, several viewers) into one
// upstream call, and keeps the last good body to serve while the feed is angry.
const FRESH_MS = 4000;            // answer from memory without asking upstream
const STALE_MS = 120000;          // ... and keep answering if upstream is failing
const MAX_KEYS = 32;
const memo = new Map();           // target URL -> {body, type, at}

// Always "*", never the caller's Origin echoed back. The data is public and no
// credentials are ever sent, so there is nothing to scope — and echoing would
// need a Vary: Origin on every response or a cache could hand one origin's
// answer ("allowed for dash.cloudflare.com") to a different site, which the
// browser then rejects. A constant header has no such failure mode.
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,OPTIONS",
  "Access-Control-Allow-Headers": "Accept",
  "Access-Control-Max-Age": "86400",
};

// `state` lands in a response header so DevTools shows whether a reply came from
// the feed (miss), from memory (hit), or is a cached copy served because the feed
// is failing (stale).
function relayed(rec, state) {
  return new Response(rec.body, {
    headers: {
      "Content-Type": rec.type,
      "Cache-Control": "no-store",
      "X-Relay-Cache": state,
      ...CORS,
    },
  });
}

function json(body, status) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

export default {
  async fetch(request) {
    if (request.method === "OPTIONS") return new Response(null, { headers: CORS });
    if (request.method !== "GET") return json({ error: "GET only" }, 405);

    const target = new URL(request.url).searchParams.get("url");
    if (!target) return json({ error: "missing ?url=" }, 400);

    let t;
    try { t = new URL(target); } catch { return json({ error: "malformed url" }, 400); }
    if (t.protocol !== "https:") return json({ error: "https only" }, 400);
    if (!ALLOWED.has(t.hostname)) return json({ error: "host not allowed: " + t.hostname }, 403);

    const key = t.toString();
    const now = Date.now();
    const hit = memo.get(key);
    if (hit && now - hit.at < FRESH_MS) return relayed(hit, "hit");

    // Anything short of a good answer falls back to the last one we did get,
    // so a rate-limited feed degrades to slightly stale rather than to nothing.
    const fallback = (why) =>
      hit && now - hit.at < STALE_MS ? relayed(hit, "stale") : json({ error: why }, 502);

    let upstream;
    try {
      upstream = await fetch(t.toString(), {
        headers: { Accept: "application/json", "User-Agent": UA },
      });
    } catch (e) {
      return fallback("upstream failed: " + e);
    }
    if (!upstream.ok) return fallback("upstream " + upstream.status);

    const rec = {
      body: await upstream.text(),
      type: upstream.headers.get("Content-Type") || "application/json",
      at: now,
    };
    memo.set(key, rec);
    if (memo.size > MAX_KEYS) memo.delete(memo.keys().next().value);
    return relayed(rec, "miss");
  },
};
