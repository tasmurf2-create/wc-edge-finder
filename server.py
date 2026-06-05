#!/usr/bin/env python3
"""
FastAPI backend for the WC Edge Finder dashboard.

Endpoints:
  GET /api/divergence   -- full match list sorted by largest gap
  GET /api/refresh      -- force a fresh pull (same data, triggers re-fetch)

Run:
  python server.py
Then open http://localhost:8000
"""
import os
import time
import threading

# Load .env before anything else
def _load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
_load_env()

import wc_odds
import prediction_markets as pmkt

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# --- cache ------------------------------------------------------------------
_cache = {"data": None, "fetched_at": 0}
_CACHE_TTL = 300   # seconds — refresh at most every 5 min to save quota

_lock = threading.Lock()


def _build_data():
    # Bookmaker layer
    try:
        key = wc_odds.find_world_cup_key()
        events = wc_odds.get(f"/sports/{key}/odds",
                             regions=wc_odds.REGIONS, markets="h2h",
                             oddsFormat=wc_odds.ODDS_FORMAT)
    except Exception as e:
        return {"error": str(e), "matches": []}

    books = {}
    for ev in events:
        r = wc_odds.analyse(ev)
        if not r:
            continue
        home, away = ev["home_team"], ev["away_team"]
        mk = pmkt.match_key(home, away)
        probs = {}
        for outcome, p in r["fair"].items():
            k = "draw" if pmkt._is_draw(outcome) else pmkt.normalize_team(outcome)
            probs[k] = p
        books[mk] = {
            "label": f"{home} vs {away}",
            "commence": r["commence"],
            "margin": r["margin"],
            "best_price": {
                (pmkt.normalize_team(o) if not pmkt._is_draw(o) else "draw"): {
                    "price": p, "book": b
                }
                for o, (p, b) in r["best_price"].items()
            },
            "probs": probs,
        }

    # Prediction markets
    try:
        poly = pmkt.fetch_polymarket()
    except Exception:
        poly = {}
    try:
        kal = pmkt.fetch_kalshi()
    except Exception:
        kal = {}

    matches = []
    for mk, b in books.items():
        pm = poly.get(mk, {}).get("probs", {})
        kl = kal.get(mk, {}).get("probs", {})

        outcomes = []
        max_gap = 0.0
        for o, bp in b["probs"].items():
            pp = pm.get(o)
            kp = kl.get(o)
            pmvals = [x for x in (pp, kp) if x is not None]
            cons = sum(pmvals) / len(pmvals) if pmvals else None
            diff = round((bp - cons) * 100, 1) if cons is not None else None
            if diff is not None and abs(diff) > abs(max_gap):
                max_gap = diff
            bp_info = b["best_price"].get(o, {})
            outcomes.append({
                "outcome": o,
                "book_fair": round(bp * 100, 1),
                "poly": round(pp * 100, 1) if pp is not None else None,
                "kalshi": round(kp * 100, 1) if kp is not None else None,
                "diff": diff,
                "best_price": bp_info.get("price"),
                "best_book": bp_info.get("book"),
            })

        outcomes.sort(key=lambda x: -x["book_fair"])
        matches.append({
            "label": b["label"],
            "commence": b["commence"],
            "margin": round(b["margin"] * 100, 1),
            "max_gap": round(max_gap, 1),
            "has_pm_data": bool(pm or kl),
            "outcomes": outcomes,
        })

    # Sort by absolute gap size descending (matches with no PM data go to bottom)
    matches.sort(key=lambda m: (-abs(m["max_gap"]) if m["has_pm_data"] else 999,
                                m["commence"]))
    return {"fetched_at": int(time.time()), "matches": matches}


def get_data(force=False):
    with _lock:
        age = time.time() - _cache["fetched_at"]
        if force or _cache["data"] is None or age > _CACHE_TTL:
            _cache["data"] = _build_data()
            _cache["fetched_at"] = time.time()
        return _cache["data"]


# --- routes -----------------------------------------------------------------
@app.get("/api/divergence")
def divergence():
    return JSONResponse(get_data())


@app.get("/api/refresh")
def refresh():
    return JSONResponse(get_data(force=True))


@app.get("/")
def index():
    return FileResponse("static/index.html")


# Serve any other static assets
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
