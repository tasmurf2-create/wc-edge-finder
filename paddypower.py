#!/usr/bin/env python3
"""
Paddy Power soft-odds adapter for GAA (hurling + gaelic football).

Paddy Power publishes no public API. Its web app loads odds from an internal
"Arcadia" feed at apisms.paddypower.com/smspp/competition-page/v3, sat behind
Cloudflare bot-management (the __cf_bm cookie is bound to the browser's TLS/JA3
fingerprint). Plain urllib/requests get a 403; `curl_cffi` impersonating Chrome
clears it — we warm up on the /gaa page to earn a fresh __cf_bm, then hit the
feed on the same session.

GAA is Betfair event type 2152880 ("Gaelic Games"), reused here as eventTypeId.
This is the SOFT book the edge-finder compares against the Betfair fair line.

NB: this is the single point of PP-specific fragility. If PP redeploys and the
params/shape change, fix them HERE only. For personal analysis; do not redistribute.
"""
import time

try:
    from curl_cffi import requests as _creq
except ImportError:  # surfaced by the caller as "odds unavailable"
    _creq = None

GAELIC_GAMES = "2152880"
APP_KEY = "vsd0Rm5ph2sS2uaK"     # public front-end key baked into paddypower.com
GAA_PAGE = "https://www.paddypower.com/gaa"
FEED = "https://apisms.paddypower.com/smspp/competition-page/v3"
CACHE_TTL = 120

# All-Ireland Hurling / Football competition ids (stable Betfair comp ids).
# Discovered live; a redeploy won't churn these, but they're easy to refresh
# from sportbex.get_gaa_markets() competition ids if ever needed.
COMPETITIONS = {
    "11971696": "All Ireland Hurling",
    "11964186": "All Ireland Football",
}

_COMMON = {
    "_ak": APP_KEY, "betexRegion": "IRL", "capiJurisdiction": "intl",
    "countryCode": "IE", "currencyCode": "EUR", "eventTypeId": GAELIC_GAMES,
    "exchangeLocale": "en_GB", "includeMarketBlurbs": "true", "includePrices": "true",
    "language": "en", "loggedIn": "false", "page": "COMPETITION", "priceHistory": "3",
    "regionCode": "IRE", "requestCountryCode": "IE", "timezone": "Europe/Dublin",
}
_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "origin": "https://www.paddypower.com",
    "referer": "https://www.paddypower.com/",
}

_cache = {"at": 0.0, "data": None}


def _decimal(runner):
    try:
        return runner["winRunnerOdds"]["trueOdds"]["decimalOdds"]["decimalOdds"]
    except (KeyError, TypeError):
        return None


def _session():
    s = _creq.Session(impersonate="chrome")
    s.get(GAA_PAGE, timeout=25)          # warm up -> earns Cloudflare __cf_bm
    return s


def get_gaa_odds():
    """Return Paddy Power soft odds keyed by event name.

    Shape: {eventName: {"throw_in": iso, "competition": name,
                        "match_odds": {runner: decimal},
                        "handicap": {runner: decimal}}}
    Returns {} (never raises) if curl_cffi is missing or Cloudflare blocks.
    """
    if _creq is None:
        return {}
    if _cache["data"] is not None and (time.time() - _cache["at"]) < CACHE_TTL:
        return _cache["data"]

    out = {}
    try:
        s = _session()
        for comp_id in COMPETITIONS:
            r = s.get(FEED, params={**_COMMON, "competitionId": comp_id},
                      headers=_HEADERS, timeout=25)
            if r.status_code != 200:
                continue
            att = r.json().get("attachments", {})
            events = att.get("events", {})
            names = {e["eventId"]: e.get("name", "") for e in events.values()}
            throw = {e["eventId"]: e.get("openDate", "") for e in events.values()}
            comps = att.get("competitions", {})
            comp_name = next((c.get("name", "") for c in comps.values()), "")
            for m in att.get("markets", {}).values():
                name = names.get(m.get("eventId"))
                if not name:
                    continue
                entry = out.setdefault(name, {
                    "throw_in": throw.get(m["eventId"], ""),
                    "competition": comp_name, "match_odds": {}, "handicap": {},
                })
                mtype = m.get("marketType")
                bucket = "match_odds" if mtype == "MATCH_ODDS" else \
                         "handicap" if mtype == "HANDICAP_BETTING" else None
                if not bucket:
                    continue
                for run in m.get("runners", []):
                    price = _decimal(run)
                    if price is not None:
                        entry[bucket][run["runnerName"]] = price
    except Exception as e:
        print(f"[paddypower] fetch failed: {e}")
        return _cache["data"] or {}

    _cache["data"] = out
    _cache["at"] = time.time()
    return out


if __name__ == "__main__":
    for name, d in get_gaa_odds().items():
        print(f"\n{name}  ({d['competition']}, {d['throw_in']})")
        for runner, price in d["match_odds"].items():
            print(f"  {runner:<14} {price}")
