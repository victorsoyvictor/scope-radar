# How Scope gets its data

Why the plumbing looks the way it does. Written August 2026, after the relay
broke and had to move. If something is failing, skip to
[When it breaks](#when-it-breaks).

## The problem, in one table

Getting live aircraft into a browser page runs into **two independent
constraints**. Every possible path trips at least one of them, and that is the
single fact this whole design exists to work around.

| Path | IP allowed? | CORS header? | Result |
|---|---|---|---|
| Browser → feed, directly | ✅ any residential IP gets `200` | ❌ none sent | Browser downloads the bytes and **throws them away** |
| Browser → relay → feed | depends where the relay runs | ✅ relay adds it | Works, *if* the relay's address isn't refused |
| Browser → local proxy → feed | ✅ your own IP | n/a, same origin | Works, but only for whoever runs it |

The trap: fixing one constraint does nothing for the other. "My IP works fine"
is true and irrelevant — the browser is what discards the response. "The relay
adds CORS" is also true and irrelevant if the feed refuses the relay's address.

The feeds are `api.adsb.lol` and `opendata.adsb.fi`. Neither sends
`Access-Control-Allow-Origin`, so neither can ever be read directly by a page.
**A relay is not optional.**

## The three paths, in precedence order

All in `poll()` in `web/radar.html`. First candidate that answers wins; whichever
worked last time is remembered in `localStorage` and retried first.

1. **`proxy`** — the bundled `proxy/serve.py`, when it is the one serving the
   page. Same origin, so CORS never enters into it, and one rate-limited upstream
   call is shared across every open tab.
2. **`direct`** — straight at the feeds. Always fails on CORS today, and is
   probed only every 10 minutes (`DIRECT_RETRY_MS`) so the console isn't buried
   in errors. It exists so that the day a feed adds the header, this starts
   working on its own with no code change.
3. **`relay`** — the feeds through `proxy/relay.py`. This is what makes a static
   deploy (GitHub Pages, a `file://` copy) work, and it is always last.

DIAG's **Mode** row names which one actually served the data.

## Decisions that are not obvious

Each of these looks wrong until you know what it's avoiding. That's why they're
written down.

### The relay is an AWS Lambda, not a Cloudflare Worker

`proxy/worker.js` still exists and its code is fine. **What broke is where it
ran.** In August 2026 both feeds started refusing Cloudflare Workers' shared
free-tier egress addresses — adsb.lol with `429`, adsb.fi with `403` —
persistently, and regardless of User-Agent.

Verified, so nobody has to guess again:

| Request origin | adsb.fi | adsb.lol |
|---|---|---|
| Residential IP | `200` | `200` |
| Residential IP, using the Worker's exact User-Agent | `200` | `200` |
| Cloudflare Worker | `403` | `429` |
| AWS (Lambda, us-west-2) | `200` | `200` |

So it is **not** a datacenter block, and **not** a User-Agent problem. It is that
one shared address pool being burnt by everyone else on Cloudflare's free tier.
No amount of editing `worker.js` fixes it. Don't deploy it.

### API Gateway in front, not a Lambda Function URL

A Function URL is the obvious choice and it does not work: **AWS blocks public
access to Lambda functions by default** on accounts created since roughly 2024.
`AuthType: NONE` plus a resource policy granting `Principal: "*"` both look
correct and still return `403`. The block is only liftable from the console — not
from the CLI or any SDK — so a Function URL cannot be deployed from a script.

API Gateway is designed to be public, so it sidesteps the block entirely and
disables no security control. That is the only reason it's there.

### CORS headers come from the Lambda, not from API Gateway

API Gateway's own CORS config **rejects `null` as an origin**, and `null` is
exactly what a page opened straight off disk (`file://`) sends. Letting the
gateway answer would have broken double-clicking `radar.html`, which the README
offers as the quickest way to run this.

So the gateway has no CORS config at all and `relay.py` sets the headers itself,
unconditionally. **Nothing else may add them**: two `Access-Control-Allow-Origin`
headers make browsers reject the response outright.

### `SERVED_BY_PROXY` is stamped into the HTML

The page used to decide "am I behind the proxy?" purely by hostname — localhost
or a private LAN range. That silently breaks the moment `serve.py` runs anywhere
public: it would serve `/api/ac` and then watch the page ignore it, falling
through to the relay and reporting `SIM (feed offline)` with a working proxy
three inches away.

`serve.py` now rewrites `const SERVED_BY_PROXY=false` → `true` as it serves the
file, the same way it stamps `APP_VERSION`. Deterministic, no extra request. The
hostname check remains as the fallback. The file on disk always says `false`, so
a static deploy is unaffected.

### The payload format is not ours

`{"ac": [{hex, flight, lat, lon, alt_baro, gs, track, squawk, category, …}]}` is
**`aircraft.json` from dump1090/readsb** — what every ADS-B receiver writes and
what tar1090 renders. adsb.lol, adsb.fi and airplanes.live all just re-serve it,
which is why they're interchangeable in the feed list.

It's a de facto standard, owned by nobody. The practical consequence: **any
receiver-derived feed is close to a drop-in; nothing else is.** Commercial flight
APIs (FlightAware, FlightLabs, OAG) use their own schemas and are priced per
flight lookup, not per area sweep — see [What we ruled out](#what-we-ruled-out).

## What is deployed

**AWS, region `us-west-2`** (a company account — check before adding cost):

| Resource | Name |
|---|---|
| Lambda | `scope-relay`, handler `relay.handler`, python3.12 |
| IAM role | `scope-relay-role` (logs only) |
| HTTP API | `scope-relay-api` → `https://kbuy94xds7.execute-api.us-west-2.amazonaws.com` |

That endpoint is in `RELAYS` at the top of `web/radar.html`. There is no Function
URL and no public `*` permission on the function — both were removed once API
Gateway took over.

**Limits.** Lambda: 1M requests/month, permanent. API Gateway: 1M/month for 12
months, then ~$1/million. One continuous viewer polling every 5 s is ~518k/month,
so a few friends looking for a while is comfortable; a wall display left on
around the clock is not. Add a budget alarm before opening it to many people.

## When it breaks

Work outwards. Each step tells you which of the two constraints failed.

**1. What does DIAG say?** Open the page, DIAG tab. The **Mode** row names the
path that served the data; **Last fetch** carries the per-candidate reasons on
failure. `SIM (feed offline)` with `NO FEED` means every candidate failed.

**2. Are the feeds alive at all?** From your own machine:

```bash
curl -s -o /dev/null -w "adsb.fi  %{http_code}\n" \
  "https://opendata.adsb.fi/api/v3/lat/-37.6733/lon/144.8433/dist/32"
curl -s -o /dev/null -w "adsb.lol %{http_code}\n" \
  "https://api.adsb.lol/v2/point/-37.6733/144.8433/32"
```

Two `200` means the feeds are fine and the problem is the relay or CORS.

**3. Is the relay alive?** This is the usual culprit — it's the piece that
depends on somebody else's opinion of our IP address:

```bash
curl -s -D- -o /dev/null \
  "https://kbuy94xds7.execute-api.us-west-2.amazonaws.com/?url=https%3A%2F%2Fapi.adsb.lol%2Fv2%2Fpoint%2F-37.6733%2F144.8433%2F32" \
  | grep -iE "^HTTP|access-control-allow-origin"
```

Want: `200` and exactly **one** `access-control-allow-origin: *`. A `502` with
`{"error":"upstream 429"}` or `403` means the feeds have started refusing AWS
too, and the relay has to move again — the table above is how to test a candidate
host before committing to it.

**4. Is the local proxy healthy?** `curl localhost:8787/health` reports which
upstream answered last and how fast, cache ages and hit rates, and request
counts. `ok` is `false` when any upstream's *most recent* attempt failed. It
never calls a feed itself, so polling it is free.

**5. Is it just this browser?** A page served over plain `http://` on a public
address loses **USE MY LOCATION** — geolocation requires a secure context. That's
a symptom of how it's served, not of the feed.

## What we ruled out

Don't spend an afternoon re-testing these.

- **Changing the Worker's User-Agent.** Not a UA problem; verified `200` from a
  residential IP using the Worker's exact UA.
- **A different datacenter.** Also not a datacenter block — AWS answers `200`.
  Cloudflare's free-tier pool specifically is what's burnt.
- **Finding a feed that sends CORS.** None do. OpenSky sends
  `access-control-allow-origin: https://opensky-network.org` — its own site only,
  useless to us — and its state-vector format would need a mapping layer anyway.
- **Commercial flight APIs.** FlightAware AeroAPI, FlightLabs, OAG. All priced
  per flight lookup: a 5-second area sweep is ~518k calls/month, which lands
  around $1,000/month at AeroAPI rates versus free for receiver data. They also
  answer a different question (gates, terminals, schedules) than a positional
  radar asks. FlightStats does still embed gate/terminal in a `__NEXT_DATA__`
  blob, which would suit the **detail card** — on-demand, one flight, already
  cached 2 h — but it's a scrape, so it breaks on their next deploy, and it has
  no CORS, so it would be proxy-only.
- **Running the relay from home behind a tunnel.** Works, but needs a machine
  powered on permanently. Only worth revisiting if cloud addresses get refused
  too.
- **Becoming a feeder.** Feeding data to adsb.fi or airplanes.live unblocks their
  APIs properly and would restore airplanes.live, which was dropped in 2026 when
  it closed to non-feeders. Real fix, needs hardware. See `HARDWARE.md`.
