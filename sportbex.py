#!/usr/bin/env python3
"""
SportBex -> Betfair Exchange adapter for GAA (hurling + gaelic football).

The Odds API carries no GAA. SportBex's trial API exposes a Betfair Exchange
passthrough keyed by Betfair event-type id; GAA lives under **2152880
("Gaelic Games")**. Exchange back/lay prices are effectively vig-free, so this
is the SHARP / "fair line" anchor the edge-finder prices Paddy Power against.

Call chain (validated live):
    GET  /betfair/competitions/2152880                     -> competitions
    GET  /betfair/event/2152880/{competitionId}            -> events (fixtures)
    GET  /betfair/markets/2152880/{eventId}                -> markets + runners
    POST /betfair/listMarketBook/2152880 {"marketIds": ..} -> live back/lay ladders

Auth: header `sportbex-api-key: <SPORTBEX_API_KEY>` on every call.
"""
import os
import json
import time
import urllib.request
import urllib.error

GAELIC_GAMES = "2152880"          # Betfair event type — reused by Paddy Power too
BASE = "https://trial-api.sportbex.com/api/betfair"
CACHE_TTL = 120                   # seconds — exchange prices move; keep it short

_cache = {"at": 0.0, "data": None}


def _key():
    k = (os.environ.get("SPORTBEX_API_KEY") or "").strip()
    if not k:
        raise RuntimeError("SPORTBEX_API_KEY not set in .env")
    return k


def _req(path, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"sportbex-api-key": _key()}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode())


def _fair_from_book(runners, sel_names):
    """Normalise best back/lay midpoints into vig-free fair probabilities.
    Returns {runnerName: {"back": price, "lay": price, "fair_pct": float}}."""
    raw = {}
    for rn in runners:
        ex = rn.get("ex", {})
        back = ex.get("availableToBack") or []
        lay = ex.get("availableToLay") or []
        b = back[0]["price"] if back else None
        l = lay[0]["price"] if lay else None
        if b and l:
            mid = (1.0 / b + 1.0 / l) / 2.0
        elif b:
            mid = 1.0 / b
        elif l:
            mid = 1.0 / l
        else:
            continue
        raw[rn["selectionId"]] = {"back": b, "lay": l, "_mid": mid}
    total = sum(v["_mid"] for v in raw.values()) or 1.0
    out = {}
    for sel_id, v in raw.items():
        name = sel_names.get(sel_id, str(sel_id))
        out[name] = {"back": v["back"], "lay": v["lay"],
                     "fair_pct": round(v["_mid"] / total * 100, 2)}
    return out


def get_gaa_markets():
    """Return the sharp/fair line for every live GAA Match Odds market.

    Shape: [{"competition", "event", "event_id", "throw_in",
             "market_id", "fair": {runner: {back, lay, fair_pct}}}]
    Cached for CACHE_TTL. Raises on hard SportBex failure (caller degrades).
    """
    if _cache["data"] is not None and (time.time() - _cache["at"]) < CACHE_TTL:
        return _cache["data"]

    out = []
    comps = _req(f"/competitions/{GAELIC_GAMES}")
    for c in comps:
        comp = c.get("competition", {})
        comp_id = comp.get("id")
        comp_name = comp.get("name", "")
        if not comp_id:
            continue
        events = _req(f"/event/{GAELIC_GAMES}/{comp_id}")
        for ev in events:
            e = ev.get("event", {})
            eid = e.get("id")
            if not eid:
                continue
            markets = _req(f"/markets/{GAELIC_GAMES}/{eid}")
            mo = next((m for m in markets if m.get("marketName") == "Match Odds"), None)
            if not mo:
                continue
            sel_names = {r["selectionId"]: r["runnerName"] for r in mo.get("runners", [])}
            book = _req(f"/listMarketBook/{GAELIC_GAMES}",
                        {"marketIds": mo["marketId"]})
            rows = (book.get("data") or [])
            if not rows:
                continue
            fair = _fair_from_book(rows[0].get("runners", []), sel_names)
            if not fair:
                continue
            out.append({
                "competition": comp_name,
                "event": e.get("name", ""),
                "event_id": eid,
                "throw_in": e.get("openDate", ""),
                "market_id": mo["marketId"],
                "fair": fair,
            })

    _cache["data"] = out
    _cache["at"] = time.time()
    return out


if __name__ == "__main__":
    for m in get_gaa_markets():
        print(f"\n{m['competition']}: {m['event']}  ({m['throw_in']})")
        for runner, p in m["fair"].items():
            print(f"  {runner:<14} back {p['back']}  lay {p['lay']}  fair {p['fair_pct']}%")
