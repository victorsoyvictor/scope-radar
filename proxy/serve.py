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


def fetch(url: str, timeout: float = 8.0) -> bytes:
    """GET a URL, respecting the shared upstream rate limit."""
    global _last_call
    with _throttle:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def get_aircraft(lat: str, lon: str, nm: str) -> bytes:
    key = (lat, lon, nm)
    now = time.monotonic()
    if _ac_cache["key"] == key and now - _ac_cache["at"] < AC_TTL:
        return _ac_cache["body"]
    body = fetch(ADSB_FI.format(lat=lat, lon=lon, nm=nm))
    _ac_cache.update(key=key, body=body, at=now)
    return body


def get_route(callsign: str) -> bytes:
    now = time.monotonic()
    hit = _route_cache.get(callsign)
    if hit and hit[1] > now:
        return hit[0]
    try:
        body = fetch(ADSBDB.format(cs=urllib.parse.quote(callsign)))
        ttl = ROUTE_TTL_HIT
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        body = b'{"response":"unknown callsign"}'
        ttl = ROUTE_TTL_MISS
    _route_cache[callsign] = (body, now + ttl)
    return body


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

        if u.path in ("/", "/index.html", "/radar.html"):
            path = os.path.join(WEB_DIR, "radar.html")
            try:
                with open(path, "rb") as f:
                    body = f.read()
                body = _VERSION_RE.sub(
                    b'const APP_VERSION="' + VERSION.encode() + b'"', body)
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

        if u.path == "/api/health":
            return self._send(200, json.dumps({
                "ok": True,
                "cached_routes": len(_route_cache),
                "aircraft_cache_age": round(time.monotonic() - _ac_cache["at"], 1)
                if _ac_cache["body"] else None,
            }).encode())

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
