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
[airplanes.live](https://airplanes.live), which sends CORS headers so the browser
lets it through.

Or run the bundled proxy to use [adsb.fi](https://adsb.fi) instead, with shared
rate-limiting and caching across tabs:

```bash
python3 proxy/serve.py
# then open http://localhost:8787
```

No dependencies. Python 3.9 or newer. Served this way the page prefers the proxy
and falls back to airplanes.live if it's unreachable.

## What it does

- **Map underlay** — a [CARTO](https://carto.com/attributions) dark basemap
  (OpenStreetMap data) is drawn behind the scope and aircraft sit on their true
  geographic positions. Free, no API key, and it sends CORS headers so it loads
  straight from the browser.
- **Live traffic** from [airplanes.live](https://airplanes.live) (or [adsb.fi](https://adsb.fi)
  through the proxy), polled every 5 seconds.
- **Dead reckoning** between polls. Each aircraft is projected along its last
  reported track at its last reported ground speed, so motion stays smooth on a
  slow poll. The projection is capped at 20 seconds — an aircraft that stops
  reporting drifts that far and then holds, rather than flying off forever.
- **Tap once** for a chip with callsign, altitude and speed. **Tap again** for
  registration, type, vertical rate, distance, bearing, squawk and route.
- **Routes** from [adsbdb](https://api.adsbdb.com), looked up only when you open
  a detail card, and cached for two hours.
- **Skins** — Night, Phosphor (green CRT), Amber, Day, and Synthwave (neon
  magenta/cyan), each swapping the basemap, scope colours and UI together. Pick
  one under **SETTINGS**; the choice is remembered, and `?skin=synth` in the URL
  presets it.
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
- **Range** 5 / 10 / 25 / 50 / 100 / 250 km.
- **Emergency squawks** 7500, 7600 and 7700 raise a red banner.
- **Nearest 96** aircraft are kept, matching the memory budget of the ESP32
  build this is modelled on. Beyond that, the furthest is dropped.
- **Simulated mode** so the scope still shows something when the feed is
  unreachable or the sky is empty. The badge in the header always says which
  mode you're in: `LIVE`, `SIM`, or `NO FEED`.

## Why the proxy exists

It's optional now — airplanes.live sends `Access-Control-Allow-Origin`, so the
page reads it straight from the browser. adsb.fi does **not** send that header, so
a browser fetches its response and then refuses to let the page read it; the proxy
puts the page and adsb.fi on one origin to get around that.

`proxy/serve.py` also does two things worth having on their own:

- **Rate limiting.** adsb.fi allows one request per second. The proxy holds a
  single lock across all clients, so ten open tabs still produce one upstream
  call per second rather than ten.
- **Caching.** Aircraft responses are cached for 4 seconds, found routes for
  2 hours, and unknown callsigns for 30 minutes.

## Layout

```
web/radar.html      the entire front end — one file, no build step
proxy/serve.py      static server + CORS relay + rate limiter
docs/HARDWARE.md    the display board, what to buy, what to avoid
```

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
| `skin`    | `night` · `phosphor` · `amber` · `day` · `synth` | colour theme |
| `cycle`   | seconds (e.g. `10`; `0` = off) | auto-cycle through aircraft |
| `lat`     | −90…90    | centre latitude |
| `lon`     | −180…180  | centre longitude |
| `range`   | km (snaps to 5/10/25/50/100/250) | initial range |
| `src`     | `live` · `sim` | data source |

A URL value overrides the remembered setting and is then saved. Example — a
London-Heathrow wall in the neon skin, cycling every 10 s:

```
?lat=51.47&lon=-0.4551&range=25&skin=synth&cycle=10
```

## Data sources and terms

- Aircraft positions: [adsb.fi](https://adsb.fi) — free, no key, **personal and
  non-commercial use only**, one request per second, and they ask that you credit
  them. If you find this useful, consider running a receiver and feeding back.
- Routes: [adsbdb](https://www.adsbdb.com).

Aircraft are only visible here because volunteers run receivers and share what
they pick up. This project is a viewer for their work.

## Licence

MIT. See [LICENSE](LICENSE).
