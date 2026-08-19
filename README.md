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
[adsb.lol](https://adsb.lol), falling back to
[airplanes.live](https://airplanes.live) — through a CORS relay, because neither
feed lets a browser read it directly any more. See
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
  [adsb.lol](https://adsb.lol), then [airplanes.live](https://airplanes.live) —
  or [adsb.fi](https://adsb.fi) through the proxy. DIAG names the feed in use,
  and lists the per-feed error when none of them answer.
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

`RELAYS` ships with a couple of public relays so the page works unconfigured, but
those are shared third parties: they rate-limit, they go down, and every query
passes through someone else's server. Treat them as a stopgap.
`proxy/worker.js` is a ~40-line Cloudflare Worker that does the same job on your
own account — free tier, about two minutes to deploy, and it only relays an
allowlist of feed hosts so it can't be abused as an open proxy. Put it at the
front of `RELAYS`, or pass `?relay=<url>`; `?relay=` on its own turns relaying
off and goes direct.

A relay answering `200` is not the same as a relay working: they will happily
return their own `{"error": …}` as valid JSON. Every reply has to carry an `ac`
array or it counts as a failure and the next candidate is tried, with the first
40 characters of what came back shown in DIAG.

Direct requests are still tried first on every poll, so the day a feed starts
sending the header again the relay quietly stops being used. DIAG's **Mode** row
names whichever path actually served the data, e.g. `LIVE · adsb.lol via relay`.

`proxy/serve.py` also does two things worth having on their own:

- **Rate limiting.** adsb.fi allows one request per second. The proxy holds a
  single lock across all clients, so ten open tabs still produce one upstream
  call per second rather than ten.
- **Caching.** Aircraft responses are cached for 4 seconds, found routes for
  2 hours, and unknown callsigns for 30 minutes.

## Layout

```
web/radar.html      the entire front end — one file, no build step
proxy/serve.py      static server + CORS relay + rate limiter (run it locally)
proxy/worker.js     the same CORS relay as a Cloudflare Worker (for static hosts)
scripts/version.py  stamps `git describe` into radar.html for a static deploy
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

- Aircraft positions, all free and keyless, all **personal and non-commercial use
  only**: [adsb.lol](https://adsb.lol) and [airplanes.live](https://airplanes.live)
  straight from the browser, [adsb.fi](https://adsb.fi) through the proxy (one
  request per second, and they ask that you credit them). All three are
  community-run; if you find this useful, consider running a receiver and feeding
  back.
- Routes: [adsbdb](https://www.adsbdb.com).

Aircraft are only visible here because volunteers run receivers and share what
they pick up. This project is a viewer for their work.

## Licence

MIT. See [LICENSE](LICENSE).
