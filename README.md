# Scope

A live plane radar you can run in a browser. It polls a community ADS-B network,
draws every aircraft near a point you choose on a PPI scope, and lets you tap one
to see what it is and where it's going.

Inspired by [Adam Conway's ESP32 plane radar](https://www.xda-developers.com/)
and [MatixYo's Plane Radar](https://github.com/MatixYo/plane-radar). This is the
software half of that idea — the same data sources and the same interaction
model, without the hardware. See [docs/HARDWARE.md](docs/HARDWARE.md) if you want
to build the physical version.

## Run it

The quickest way — just open the page. No server, no dependencies:

```bash
open web/radar.html      # or double-click it
```

Opened directly, the page pulls live traffic from
[adsb.lol](https://adsb.lol), with [adsb.fi](https://adsb.fi) behind it — through
a CORS relay, because no feed lets a browser read it directly any more. See
[Feeds, CORS and the relay](#feeds-cors-and-the-relay); it works out of the box,
but the relay is worth pointing at your own once you care.

Or run the bundled proxy to use [adsb.fi](https://adsb.fi) instead, with shared
rate-limiting and caching across tabs — and no relay in the picture at all:

```bash
python3 proxy/serve.py
# then open http://localhost:8787
```

No dependencies. Python 3.9 or newer. Served this way the page prefers the proxy
and only falls back to the public feeds if it's unreachable.

## What it does

- **Map underlay** — a [CARTO](https://carto.com/attributions) dark basemap
  (OpenStreetMap data) is drawn behind the scope and aircraft sit on their true
  geographic positions. Free, no API key, and it sends CORS headers so it loads
  straight from the browser.
- **Live traffic** polled every 5 seconds, from the first feed that answers:
  [adsb.lol](https://adsb.lol), then [adsb.fi](https://adsb.fi) through the relay
  or the proxy. DIAG names the feed in use, and lists the per-feed reason when
  none of them answer.
- **Dead reckoning** between polls. Each aircraft is projected along its last
  reported track at its last reported ground speed, so motion stays smooth on a
  slow poll. The projection is capped at 20 seconds — an aircraft that stops
  reporting drifts that far and then holds, rather than flying off forever.
- **Tap once** for a chip with callsign, altitude and speed. **Tap again** for
  registration, type, vertical rate, distance, bearing, squawk and route.
- **Routes** from [adsbdb](https://api.adsbdb.com), looked up only when you open
  a detail card, and cached for two hours.
- **Skins** — Night, Phosphor (green CRT), Red (monochrome red, preserves night
  vision like a stargazing app), Day, and Synthwave (neon magenta/cyan), each
  swapping the basemap, scope colours and UI together. Pick one under
  **SETTINGS**; the choice is remembered, and `?skin=synth` in the URL presets it.
- **Size-scaled icons** — aircraft draw bigger or smaller by their real size
  class (from the ADS-B wake category / type), so an A380 stands out from a
  regional jet at a glance.
- **Tap the plane or its info card** for the full detail page (type,
  registration, vertical rate, distance, bearing, squawk, route, and the
  **airline logo + name** where known).
- **Local weather** for the centre point in the header, from
  [Open-Meteo](https://open-meteo.com) (free, no key).
- **Ambient music** — an optional speaker button plays a YouTube track (loaded
  only on tap; browsers block auto-play with sound). Set `MUSIC_ID` / `MUSIC_START`
  near the top of the script, or `MUSIC_ID=""` to hide it.
- **Grounded aircraft** (taxiing / on the runway) are hidden by default to cut
  clutter near airports — flip them on under **SETTINGS**.
- **Range** 5 / 10 / 25 / 50 / 100 / 250 km.
- **Emergency squawks** 7500, 7600 and 7700 raise a red banner.
- **Nearest 96** aircraft are kept, matching the memory budget of the ESP32
  build this is modelled on. Beyond that, the furthest is dropped.
- **Simulated mode** so the scope still shows something when the feed is
  unreachable or the sky is empty. The badge in the header always says which
  mode you're in: `LIVE`, `SIM`, or `NO FEED`.

## Feeds, CORS and the relay

As of August 2026 none of the public ADS-B feeds send an
`Access-Control-Allow-Origin` header. They answer a browser perfectly well — the
bytes arrive — but without that header the browser refuses to hand the response
to the page, and DevTools shows `CORS Missing Allow Origin`. That check exists to
stop any page you visit from quietly reading other origins using your cookies and
your network position; the feed has to opt in, and none of them do.

That leaves a page with no server of its own two ways to read a feed:

- **The bundled proxy** — `python3 proxy/serve.py` serves the page *and* the feed
  from one origin, so there is no cross-origin read to block. Best option when
  you're running it locally anyway.
- **A CORS relay** — something that fetches the feed server-side and re-serves it
  with the header attached. This is what makes a static deploy (GitHub Pages, a
  `file://` copy) work. `RELAYS` near the top of `web/radar.html` lists them.

`proxy/relay.py` is that relay: an AWS Lambda behind an API Gateway HTTP API,
relaying only an allowlist of feed hosts so it can't be abused as an open proxy.
It caches for a few seconds and keeps serving the last good answer for up to two
minutes when a feed starts refusing, which is what stops a rate-limited feed from
dropping the scope into simulation. Deploy instructions are in the file header.

`proxy/worker.js` is the same relay as a Cloudflare Worker, and it is kept only
for reference. **Do not deploy it.** The code is fine; where it runs is not. In
August 2026 both feeds began refusing Workers' shared free-tier egress addresses
— adsb.lol with `429`, adsb.fi with `403` — persistently, and regardless of
User-Agent, because that address pool is shared with every free Worker on the
platform. The same requests answer `200` from AWS, which is why the relay moved.
A residential address answers `200` too, so this is not a datacenter block.

> **Running your own copy?** `RELAYS` ships pointing at *this* project's relay.
> It will work, but it spends someone else's AWS quota and sends them every
> query — deploy `proxy/relay.py` on your own account and put your endpoint
> there instead. `?relay=<url>` overrides it without editing anything, and
> `?relay=` on its own turns relaying off and goes direct.

Public "CORS proxy" services are a tempting shortcut and mostly a trap. Two were
shipped here and both were removed: codetabs sends no `Access-Control-Allow-Origin`
of its own, so it could never work from a browser, and allorigins spent most of
its time returning a rate-limit error. Anything added to `RELAYS` should be
checked against a real browser first — a relay answering `200` is not the same as
a relay working, and they will happily return their own `{"error": …}` as valid
JSON. Every reply has to carry an `ac` array or it counts as a failure, with the
first 40 characters of what came back shown in DIAG.

The feeds are still probed directly every ten minutes, so the day one starts
sending the header the relay quietly stops being used — but not on every poll,
because each doomed attempt logs a CORS error and buries real ones. Whichever
candidate last worked is remembered in `localStorage` and tried first, so a
return visit is a single request. DIAG's **Mode** row names the path that
actually served the data, e.g. `LIVE · adsb.lol via lambda`.

`proxy/serve.py` also does two things worth having on their own:

- **Rate limiting.** adsb.fi allows one request per second. The proxy holds a
  single lock across all clients, so ten open tabs still produce one upstream
  call per second rather than ten.
- **Caching.** Aircraft responses are cached for 4 seconds, found routes for
  2 hours, and unknown callsigns for 30 minutes.
- **A health endpoint.** `curl localhost:8787/health` (also `/api/health`) is the
  server-side counterpart of the DIAG tab: which upstream answered last and how
  fast, what the caches hold, how many requests came in. `ok` is false when an
  upstream's most recent attempt failed, so `curl -s localhost:8787/health | jq
  .upstreams` is the quickest way to tell a dead feed from a dead proxy. It only
  reports what past traffic recorded and never calls a feed itself, so polling it
  costs nothing against the rate limit.

## Layout

```
web/radar.html      the entire front end — one file, no build step
proxy/serve.py      static server + CORS relay + rate limiter (run it locally)
proxy/relay.py      the CORS relay as an AWS Lambda (what static hosts use)
proxy/worker.js     the same relay as a Cloudflare Worker — reference only, see above
scripts/version.py  stamps `git describe` into radar.html for a static deploy
docs/ARCHITECTURE.md why the data plumbing looks like this, and how to debug it
docs/HARDWARE.md    the display board, what to buy, what to avoid
```

## Version

DIAG shows a build version from `git describe` — a tag if you've made one,
otherwise the short commit hash (`+"-dirty"` for an uncommitted change). Two
ways it gets there:

- **Served by the proxy** (`python3 proxy/serve.py`) — stamped live from your
  git checkout on every request. Always current; nothing to run.
- **Served statically** (opened directly, GitHub Pages, a USB stick) — run
  `python3 scripts/version.py` before you deploy and commit the result, or
  DIAG just shows `dev`.

## Configuration

The centre point defaults to Melbourne Airport. Change it under **SETTINGS** —
type coordinates, or press **USE MY LOCATION**. `PORT` sets the proxy port:

```bash
PORT=9000 python3 proxy/serve.py
```

### URL parameters

A single bookmark can fully define a display — handy for a wall screen with no
keyboard. All are optional and combine with `&`:

| Parameter | Values | Meaning |
|-----------|--------|---------|
| `skin`    | `night` · `phosphor` · `red` · `day` · `synth` | colour theme |
| `cycle`   | seconds (e.g. `10`; `0` = off) | auto-cycle through aircraft |
| `lat`     | −90…90    | centre latitude |
| `lon`     | −180…180  | centre longitude |
| `range`   | km (snaps to 5/10/25/50/100/250) | initial range |
| `src`     | `live` · `sim` | data source |
| `relay`   | a CORS relay URL ending in `?url=`; empty = go direct | replaces `RELAYS` |

A URL value overrides the remembered setting and is then saved. Example — a
London-Heathrow wall in the neon skin, cycling every 10 s:

```
?lat=51.47&lon=-0.4551&range=25&skin=synth&cycle=10
```

## Data sources and terms

- Aircraft positions, free and keyless, **personal and non-commercial use only**:
  [adsb.lol](https://adsb.lol) and [adsb.fi](https://adsb.fi) (one request per
  second, and they ask that you credit them). Both are community-run.
  [airplanes.live](https://airplanes.live) was a third until 2026, when it closed
  its API to non-feeders — a reminder that this data exists only because people
  run receivers. If you find this useful, consider becoming one of them;
  [docs/HARDWARE.md](docs/HARDWARE.md) is a place to start.
- Routes: [adsbdb](https://www.adsbdb.com).

Aircraft are only visible here because volunteers run receivers and share what
they pick up. This project is a viewer for their work.

## Licence

MIT. See [LICENSE](LICENSE).
