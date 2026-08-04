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

```bash
python3 proxy/serve.py
# then open http://localhost:8787
```

No dependencies. Python 3.9 or newer.

You can also open `web/radar.html` directly, but the browser will almost
certainly block the data feeds (see *Why the proxy exists* below) and the page
will fall back to simulated traffic.

## What it does

- **Live traffic** from [adsb.fi](https://adsb.fi), polled every 5 seconds.
- **Dead reckoning** between polls. Each aircraft is projected along its last
  reported track at its last reported ground speed, so motion stays smooth on a
  slow poll. The projection is capped at 20 seconds — an aircraft that stops
  reporting drifts that far and then holds, rather than flying off forever.
- **Tap once** for a chip with callsign, altitude and speed. **Tap again** for
  registration, type, vertical rate, distance, bearing, squawk and route.
- **Routes** from [adsbdb](https://api.adsbdb.com), looked up only when you open
  a detail card, and cached for two hours.
- **Range** 5 / 10 / 25 / 50 / 100 / 250 km.
- **Emergency squawks** 7500, 7600 and 7700 raise a red banner.
- **Nearest 96** aircraft are kept, matching the memory budget of the ESP32
  build this is modelled on. Beyond that, the furthest is dropped.
- **Simulated mode** so the scope still shows something when the feed is
  unreachable or the sky is empty. The badge in the header always says which
  mode you're in: `LIVE`, `SIM`, or `NO FEED`.

## Why the proxy exists

adsb.fi and adsbdb don't send `Access-Control-Allow-Origin` headers, so a browser
will fetch their responses and then refuse to let the page read them. Serving the
page and the data from one origin removes the problem.

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

## Data sources and terms

- Aircraft positions: [adsb.fi](https://adsb.fi) — free, no key, **personal and
  non-commercial use only**, one request per second, and they ask that you credit
  them. If you find this useful, consider running a receiver and feeding back.
- Routes: [adsbdb](https://www.adsbdb.com).

Aircraft are only visible here because volunteers run receivers and share what
they pick up. This project is a viewer for their work.

## Licence

MIT. See [LICENSE](LICENSE).
