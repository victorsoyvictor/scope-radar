"""CORS relay for the ADS-B feeds - an AWS Lambda behind an API Gateway HTTP API.

The Cloudflare Worker this replaces (proxy/worker.js) still works as code; what
stopped working is where it runs. The feeds refuse Workers' shared egress IPs -
adsb.lol with 429, adsb.fi with 403 - and no header or retry gets past that.
Lambda leaves from AWS addresses the feeds still answer, verified 200 on both.

Everything else is the Worker's design, kept deliberately: same host allowlist,
same memo window, same stale fallback, and the CORS headers emitted here rather
than by the gateway in front. API Gateway's own CORS config rejects "null" as an
origin, and a page opened straight off disk (file://) sends exactly that - so
letting it answer would have broken double-clicking radar.html, which the README
offers as the quickest way to run this. Setting them here covers every origin.
Nothing else may add them: two Access-Control-Allow-Origin headers make browsers
reject the response outright.

Deploy (no dependencies, stdlib only):

    zip fn.zip relay.py                       # handler is relay.handler
    aws iam create-role --role-name scope-relay-role \
      --assume-role-policy-document \
      '{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
        "Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
    aws iam attach-role-policy --role-name scope-relay-role \
      --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
    aws lambda create-function --function-name scope-relay \
      --runtime python3.12 --handler relay.handler --timeout 30 --memory-size 256 \
      --role arn:aws:iam::<account>:role/scope-relay-role --zip-file fileb://fn.zip
    aws apigatewayv2 create-api --name scope-relay-api --protocol-type HTTP \
      --target arn:aws:lambda:<region>:<account>:function:scope-relay
    aws lambda add-permission --function-name scope-relay \
      --statement-id apigw-invoke --action lambda:InvokeFunction \
      --principal apigateway.amazonaws.com \
      --source-arn 'arn:aws:execute-api:<region>:<account>:<api-id>/*/*'

Then put the resulting endpoint in RELAYS near the top of web/radar.html, or try
it without editing anything: ?relay=https://<api-id>.execute-api.<region>.amazonaws.com/?url=

Do NOT configure CORS on the API itself - see above. A Lambda Function URL looks
like the simpler option and is not: AWS blocks public access to functions by
default on accounts created since ~2024, and that block is only liftable from the
console, so the gateway is what makes this deployable from a script.

It is deliberately NOT an open proxy: only the hosts below can be fetched, so
nobody can point it at arbitrary URLs and use your account as a relay.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

ALLOWED = {
    "api.adsb.lol",
    "api.airplanes.live",
    "opendata.adsb.fi",
    "api.adsbdb.com",
}

UA = "scope-radar (personal, non-commercial)"

# A warm Lambda serves many requests in a row, so a plain dict collapses repeated
# polls - several tabs, several viewers - into one upstream call, and keeps the
# last good body to serve while a feed is angry. Cold starts lose it, which only
# costs one extra upstream call.
FRESH_S = 4.0             # answer from memory without asking upstream
STALE_S = 120.0           # ... and keep answering if upstream is failing
MAX_KEYS = 32
_memo = {}                # target url -> {"body", "type", "at"}


# Always "*", never the caller's Origin echoed back. The data is public and no
# credentials are ever sent, so there is nothing to scope - and echoing would need
# a Vary: Origin on every response or a cache could hand one origin's answer to a
# different site, which the browser then rejects. A constant header has no such
# failure mode, and it is the only form that works for the null origin of file://.
CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Access-Control-Allow-Headers": "Accept",
    "Access-Control-Max-Age": "86400",
}


def _reply(status, body, ctype="application/json", cache_state=None):
    headers = {"Content-Type": ctype, "Cache-Control": "no-store", **CORS}
    if cache_state:
        headers["X-Relay-Cache"] = cache_state
    return {"statusCode": status, "headers": headers, "body": body}


def _error(msg, status):
    return _reply(status, json.dumps({"error": msg}))


def handler(event, context):
    ctx = event.get("requestContext", {}).get("http", {})
    if ctx.get("method") == "OPTIONS":
        return {"statusCode": 204, "headers": dict(CORS)}
    if ctx.get("method") not in (None, "GET"):
        return _error("GET only", 405)

    target = (event.get("queryStringParameters") or {}).get("url")
    if not target:
        return _error("missing ?url=", 400)

    parsed = urllib.parse.urlparse(target)
    if parsed.scheme != "https":
        return _error("https only", 400)
    if parsed.hostname not in ALLOWED:
        return _error("host not allowed: %s" % parsed.hostname, 403)

    now = time.time()
    hit = _memo.get(target)
    if hit and now - hit["at"] < FRESH_S:
        return _reply(200, hit["body"], hit["type"], "hit")

    # Anything short of a good answer falls back to the last one we did get, so a
    # rate-limited feed degrades to slightly stale rather than to nothing.
    def fallback(why):
        if hit and now - hit["at"] < STALE_S:
            return _reply(200, hit["body"], hit["type"], "stale")
        return _error(why, 502)

    req = urllib.request.Request(
        target, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", "replace")
            ctype = r.headers.get("Content-Type") or "application/json"
    except urllib.error.HTTPError as e:
        return fallback("upstream %d" % e.code)
    except Exception as e:                       # DNS, TLS, timeout
        return fallback("upstream failed: %s" % e)

    _memo[target] = {"body": body, "type": ctype, "at": now}
    if len(_memo) > MAX_KEYS:
        _memo.pop(next(iter(_memo)))
    return _reply(200, body, ctype, "miss")
