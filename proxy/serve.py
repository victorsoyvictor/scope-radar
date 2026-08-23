#!/usr/bin/env python3
"""
Scope proxy — serves the radar page and relays the ADS-B feeds.

Why this exists: adsb.fi and adsbdb don't send CORS headers, so a browser
refuses to read their responses from a page on another origin. Running this
puts the page and the data on the same origin, which makes the live feed work.

It also enforces the adsb.fi rate limit (1 request/second) on your behalf and
caches responses, so several open tabs still only produce one upstream call.

No third-party packages. Python 3.9+.

    python3 proxy/serve.py
    open http://localhost:8787

Endpoints:
    /                       the radar page
    /api/ac?lat=&lon=&nm=   aircraft within nm nautical miles (max 250)
    /api/route?callsign=    origin/destination for a callsign
    /health                 what this server has seen: upstreams, caches, counters
                            (also at /api/health)
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", 8787))
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "web")


def git_version() -> str:
    """`git describe`, e.g. v1.2.3-4-g7595dd4, or the short hash with no tags.
    "dev" if this isn't a git checkout (a plain download) or git isn't installed."""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--always", "--dirty"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=3,
        )
        v = out.stdout.strip()
        return v if out.returncode == 0 and v else "dev"
    except Exception:
        return "dev"


# Computed once at startup — accurate for the checkout the server is running
# from. Re-run the server after pulling to pick up a new version.
VERSION = git_version()
_VERSION_RE = re.compile(rb'const APP_VERSION="[^"]*"')
# The page only asks /api/ac when it knows the proxy is serving it. Its own
# hostname check recognises localhost and private LANs, which is no help once
# this runs on a public host — so say so outright, in the file, on the way out.
_PROXY_RE = re.compile(rb'const SERVED_BY_PROXY=false')

ADSB_FI = "https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{nm}"
ADSBDB = "https://api.adsbdb.com/v0/callsign/{cs}"
UA = "scope-radar/1.0 (personal, non-commercial; +https://adsb.fi)"

# adsb.fi asks for at most one request per second. One lock, one timestamp.
_throttle = threading.Lock()
_last_call = 0.0
MIN_INTERVAL = 1.05

_ac_cache = {"key": None, "body": None, "at": 0.0}
AC_TTL = 4.0                      # feed updates are ~1 Hz; 4 s is plenty
_route_cache = {}                 # callsign -> (body, expires_at)
ROUTE_TTL_HIT = 7200              # a flight's route rarely changes mid-flight
ROUTE_TTL_MISS = 1800

# What /health reports. Recorded from traffic that already flows through here —
# nothing below ever makes a request of its own, so asking for health costs the
# adsb.fi rate limit nothing. ThreadingHTTPServer means several threads touch
# these at once, hence the lock.
STARTED_AT = time.time()          # wall clock, for a human-readable start stamp
STARTED_MONO = time.monotonic()   # ... everything else measures age in monotonic
_stats_lock = threading.Lock()
_requests = {}                    # path -> count, plus a "404" bucket
_upstreams = {}                   # host -> counters, created on first call
_cache_stats = {"ac_hits": 0, "ac_misses": 0, "route_hits": 0, "route_misses": 0}


def _upstream(host: str) -> dict:
    """This host's counters, created on demand. Call under _stats_lock."""
    rec = _upstreams.get(host)
    if rec is None:
        rec = _upstreams[host] = {
            "calls": 0, "ok": 0, "errors": 0,
            "last_ok_at": None, "last_bytes": None, "last_latency_ms": None,
            "last_error": None, "last_error_at": None,
        }
    return rec


def fetch(url: str, timeout: float = 8.0, soft=()) -> bytes:
    """GET a URL, respecting the shared upstream rate limit.

    `soft` lists HTTP status codes that are a normal answer rather than a fault —
    adsbdb's 404 for a callsign it doesn't know, say. They still raise, so the
    caller handles them as before, but /health counts them as the upstream
    working, because it was: an unknown callsign is not a sick server.
    """
    global _last_call
    with _throttle:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    host = urllib.parse.urlparse(url).hostname or url
    # Timed from here, after the throttle sleep, so latency means how slow the
    # feed was and not how long we waited our turn.
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except Exception as e:
        expected = isinstance(e, urllib.error.HTTPError) and e.code in soft
        with _stats_lock:
            rec = _upstream(host)
            rec["calls"] += 1
            if expected:
                rec["ok"] += 1
                rec["last_ok_at"] = time.monotonic()
                rec["last_latency_ms"] = round((time.monotonic() - t0) * 1000)
            else:
                rec["errors"] += 1
                rec["last_error"] = f"{type(e).__name__}: {e}"
                rec["last_error_at"] = time.monotonic()
        raise                     # callers still see the original exception
    with _stats_lock:
        rec = _upstream(host)
        rec["calls"] += 1
        rec["ok"] += 1
        rec["last_ok_at"] = time.monotonic()
        rec["last_bytes"] = len(body)
        rec["last_latency_ms"] = round((time.monotonic() - t0) * 1000)
    return body


def _count(key: str) -> None:
    with _stats_lock:
        _cache_stats[key] += 1


def get_aircraft(lat: str, lon: str, nm: str) -> bytes:
    key = (lat, lon, nm)
    now = time.monotonic()
    if _ac_cache["key"] == key and now - _ac_cache["at"] < AC_TTL:
        _count("ac_hits")
        return _ac_cache["body"]
    _count("ac_misses")
    body = fetch(ADSB_FI.format(lat=lat, lon=lon, nm=nm))
    _ac_cache.update(key=key, body=body, at=now)
    return body


def get_route(callsign: str) -> bytes:
    now = time.monotonic()
    hit = _route_cache.get(callsign)
    if hit and hit[1] > now:
        _count("route_hits")
        return hit[0]
    _count("route_misses")
    try:
        body = fetch(ADSBDB.format(cs=urllib.parse.quote(callsign)), soft=(404,))
        ttl = ROUTE_TTL_HIT
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        body = b'{"response":"unknown callsign"}'
        ttl = ROUTE_TTL_MISS
    _route_cache[callsign] = (body, now + ttl)
    return body


def _age(mono, now):
    """Seconds since a monotonic stamp, or None if it never happened."""
    return None if mono is None else round(now - mono, 1)


def health_payload() -> dict:
    """Everything this server knows about its own state, for /health.

    The server-side counterpart of the page's DIAG tab: which upstream answered
    last and how fast, what the caches are holding, how many requests came in.
    Read-only — it reports what past traffic recorded and never calls a feed, so
    polling it does not eat into the adsb.fi rate limit.
    """
    now = time.monotonic()
    with _stats_lock:
        upstreams = {}
        ok = True
        for host, r in _upstreams.items():
            # Healthy means the most recent attempt worked. A host that failed an
            # hour ago and has answered since is not a problem worth flagging.
            failing = r["last_error_at"] is not None and (
                r["last_ok_at"] is None or r["last_error_at"] > r["last_ok_at"])
            if failing:
                ok = False
            upstreams[host] = {
                "calls": r["calls"], "ok": r["ok"], "errors": r["errors"],
                "failing": failing,
                "last_ok_age_s": _age(r["last_ok_at"], now),
                "last_bytes": r["last_bytes"],
                "last_latency_ms": r["last_latency_ms"],
                "last_error": r["last_error"],
                "last_error_age_s": _age(r["last_error_at"], now),
            }
        requests = dict(_requests)
        cache = dict(_cache_stats)

    return {
        "ok": ok,
        "version": VERSION,
        "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(STARTED_AT)),
        "uptime_s": round(now - STARTED_MONO, 1),
        "port": PORT,
        "requests": requests,
        "upstreams": upstreams,
        "cache": {
            "aircraft": {
                "age_s": round(now - _ac_cache["at"], 1) if _ac_cache["body"] else None,
                "ttl_s": AC_TTL,
                "bytes": len(_ac_cache["body"]) if _ac_cache["body"] else None,
                "hits": cache["ac_hits"], "misses": cache["ac_misses"],
            },
            "routes": {
                "entries": len(_route_cache),
                "hits": cache["route_hits"], "misses": cache["route_misses"],
                "ttl_hit_s": ROUTE_TTL_HIT, "ttl_miss_s": ROUTE_TTL_MISS,
            },
        },
        "throttle": {
            "min_interval_s": MIN_INTERVAL,
            "since_last_call_s": round(now - _last_call, 1) if _last_call else None,
        },
    }


# Paths do_GET answers. Only used to keep the /health request counter from
# growing a bucket per bogus URL — the dispatch below is still the authority.
ROUTES = ("/", "/index.html", "/radar.html", "/api/ac", "/api/route",
          "/health", "/api/health")


class Handler(BaseHTTPRequestHandler):
    server_version = "scope-proxy"

    def log_message(self, fmt, *args):          # quieter than the default
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, code, msg):
        self._send(code, json.dumps({"error": msg}).encode())

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        # Counted before dispatch so /health can show what is being asked for,
        # 404s included. Unknown paths share one bucket rather than letting a
        # scanner grow the dict without bound.
        known = u.path in ROUTES
        with _stats_lock:
            key = u.path if known else "404"
            _requests[key] = _requests.get(key, 0) + 1

        if u.path in ("/", "/index.html", "/radar.html"):
            path = os.path.join(WEB_DIR, "radar.html")
            try:
                with open(path, "rb") as f:
                    body = f.read()
                body = _VERSION_RE.sub(
                    b'const APP_VERSION="' + VERSION.encode() + b'"', body)
                body = _PROXY_RE.sub(b'const SERVED_BY_PROXY=true', body)
                self._send(200, body, "text/html; charset=utf-8")
            except FileNotFoundError:
                self._error(404, "radar.html not found in web/")
            return

        if u.path == "/api/ac":
            try:
                lat = float(q.get("lat", ["0"])[0])
                lon = float(q.get("lon", ["0"])[0])
                nm = int(float(q.get("nm", ["25"])[0]))
            except ValueError:
                return self._error(400, "lat, lon and nm must be numbers")
            if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                return self._error(400, "coordinates out of range")
            nm = max(1, min(250, nm))
            try:
                return self._send(200, get_aircraft(f"{lat:.4f}", f"{lon:.4f}", str(nm)))
            except Exception as e:
                return self._error(502, f"upstream failed: {e}")

        if u.path == "/api/route":
            cs = (q.get("callsign", [""])[0] or "").strip().upper()
            if not cs.isalnum() or not (3 <= len(cs) <= 8):
                return self._error(400, "callsign must be 3-8 alphanumeric characters")
            try:
                return self._send(200, get_route(cs))
            except Exception as e:
                return self._error(502, f"upstream failed: {e}")

        if u.path in ("/health", "/api/health"):
            return self._send(200, json.dumps(health_payload()).encode())

        self._error(404, "no such endpoint")


def main():
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Scope proxy listening on http://localhost:{PORT}  (version {VERSION})")
    print("Data from adsb.fi and adsbdb. Personal, non-commercial use.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        srv.server_close()


if __name__ == "__main__":
    main()
