#!/usr/bin/env python3
"""
FastAPI backend for the WC Edge Finder dashboard.

Endpoints:
  GET /api/divergence   -- match divergence report (book vs prediction markets)
  GET /api/bets         -- recommended singles + parlay suggestions
  GET /api/refresh      -- force re-fetch of all data

Run:  python server.py
Then open http://localhost:8000
"""
import os
import time
import itertools
import threading
from collections import defaultdict

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

REGIONS = "uk,eu,us"       # wider region set to catch Paddy Power + US books
EDGE_MIN   = 0.005         # flag singles with >0.5% edge
PARLAY_MIN = 0.005         # minimum combined EV to include a parlay
VALUE_THRESHOLD = 0.015    # 1.5% edge = "clear value"

# ---------------------------------------------------------------------------
# Cache — one shared fetch for all endpoints
# ---------------------------------------------------------------------------
_cache = {"raw": None, "fetched_at": 0}
_CACHE_TTL = 300
_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Bookmaker data helpers
# ---------------------------------------------------------------------------

def _fetch_events():
    """Pull h2h + totals in a single API call."""
    key = wc_odds.find_world_cup_key()
    return wc_odds.get(
        f"/sports/{key}/odds",
        regions=REGIONS,
        markets="h2h,totals",
        oddsFormat=wc_odds.ODDS_FORMAT,
    )


def _devig(raw):
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}, total - 1.0


def _analyse_h2h(event):
    """Returns h2h fair probs, best prices, margin — same as wc_odds.analyse."""
    return wc_odds.analyse(event)


def _analyse_totals(event):
    """
    De-vig over/under markets. Groups outcomes by line (e.g. 2.5).
    Returns { line: {outcome: (fair_prob, best_price, best_book)} }
    """
    # Collect all prices per line per book
    line_book_prices = defaultdict(dict)   # line -> {outcome -> [prices]}
    line_best = defaultdict(lambda: defaultdict(lambda: (None, None)))  # line -> outcome -> (price, book)

    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market["key"] != "totals":
                continue
            for o in market["outcomes"]:
                line = o.get("point")
                if line is None:
                    continue
                name  = o["name"]   # "Over" / "Under"
                price = o["price"]
                line_book_prices[line].setdefault(name, []).append((price, bm["title"]))
                cur_price, _ = line_best[line][name]
                if cur_price is None or price > cur_price:
                    line_best[line][name] = (price, bm["title"])

    result = {}
    for line, book_prices in line_book_prices.items():
        if len(book_prices) < 2:
            continue
        # Use average implied prob from all books to build fair
        avg_implied = {}
        for name, prices in book_prices.items():
            avg_implied[name] = sum(1.0/p for p, _ in prices) / len(prices)
        fair, margin = _devig(avg_implied)

        outcomes = {}
        for name, fp in fair.items():
            best_price, best_book = line_best[line][name]
            outcomes[name] = {
                "fair":       round(fp * 100, 1),
                "best_price": best_price,
                "best_book":  best_book,
                "edge":       round((fp - 1.0/best_price) * 100, 2) if best_price else None,
            }
        result[float(line)] = {"outcomes": outcomes, "margin": round(margin * 100, 1)}

    return result


def _all_h2h_prices(event):
    """Return {bookmaker_title: {outcome_name: price}} for h2h market."""
    result = {}
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market["key"] != "h2h":
                continue
            result[bm["title"]] = {o["name"]: o["price"] for o in market["outcomes"]}
    return result


# ---------------------------------------------------------------------------
# Core build
# ---------------------------------------------------------------------------

def _build_raw():
    try:
        events = _fetch_events()
    except Exception as e:
        return {"error": str(e), "matches": [], "bets": {"singles": [], "parlays": []}}

    try:
        kal = pmkt.fetch_kalshi()
    except Exception:
        kal = {}
    try:
        poly = pmkt.fetch_polymarket()
    except Exception:
        poly = {}

    matches     = []
    singles     = []
    all_books   = set()

    for ev in events:
        h2h_r = _analyse_h2h(ev)
        if not h2h_r:
            continue

        home, away = ev["home_team"], ev["away_team"]
        mk    = pmkt.match_key(home, away)
        label = f"{home} vs {away}"
        comm  = h2h_r["commence"]

        kl_probs   = kal.get(mk, {}).get("probs", {})
        pm_probs   = poly.get(mk, {}).get("probs", {})
        book_table = _all_h2h_prices(ev)   # {bookname: {outcome: price}}
        all_books.update(book_table.keys())

        # ---- h2h outcomes ---------------------------------------------------
        h2h_outcomes = []
        max_gap = 0.0

        for raw_name, fair_p in h2h_r["fair"].items():
            norm = "draw" if pmkt._is_draw(raw_name) else pmkt.normalize_team(raw_name)
            bp_price, bp_book = h2h_r["best_price"].get(raw_name, (None, None))
            # Per-bookmaker prices for this outcome
            per_book = {bk: prices[raw_name] for bk, prices in book_table.items() if raw_name in prices}
            paddy = per_book.get("Paddy Power")

            kp = kl_probs.get(norm)
            pp = pm_probs.get(norm)
            pmvals = [x for x in (kp, pp) if x is not None]
            pm_cons = sum(pmvals) / len(pmvals) if pmvals else None

            diff = round((fair_p - pm_cons) * 100, 1) if pm_cons is not None else None
            if diff is not None and abs(diff) > abs(max_gap):
                max_gap = diff

            edge = round((fair_p - 1.0/bp_price) * 100, 2) if bp_price else None

            # Confidence: edge on price line + PM confirmation
            pm_gap = round((pm_cons - fair_p) * 100, 1) if pm_cons is not None else None
            pm_confirms = pm_gap is not None and pm_gap > 0  # PM thinks it's more likely than books

            if edge is not None and edge > VALUE_THRESHOLD * 100:
                confidence = "high" if pm_confirms else "medium"
            elif edge is not None and edge > EDGE_MIN * 100:
                confidence = "medium" if pm_confirms else "low"
            elif pm_gap is not None and pm_gap < -4:
                # Books SHORT by >4% vs PM with no direct book edge
                confidence = "medium"
                edge = edge or 0
            else:
                confidence = None

            outcome_obj = {
                "outcome":    norm,
                "market":     "h2h",
                "book_fair":  round(fair_p * 100, 1),
                "poly":       round(pp * 100, 1) if pp is not None else None,
                "kalshi":     round(kp * 100, 1) if kp is not None else None,
                "diff":       diff,
                "best_price": bp_price,
                "best_book":  bp_book,
                "paddy":      paddy,
                "edge":       edge,
                "pm_gap":     pm_gap,
                "confidence": confidence,
            }
            h2h_outcomes.append(outcome_obj)

            # Collect as value single if it has any edge
            if edge is not None and edge > EDGE_MIN * 100:
                singles.append({
                    "match":       label,
                    "commence":    comm,
                    "market":      "h2h",
                    "outcome":     norm,
                    "raw_outcome": raw_name,
                    "fair_prob":   fair_p,
                    "best_price":  bp_price,
                    "best_book":   bp_book,
                    "per_book":    per_book,   # {bookname: price}
                    "paddy":       paddy,
                    "edge":        edge,
                    "pm_gap":      pm_gap,
                    "confidence":  confidence or "low",
                    "kalshi":      round(kp * 100, 1) if kp is not None else None,
                    "poly":        round(pp * 100, 1) if pp is not None else None,
                })

        h2h_outcomes.sort(key=lambda x: -x["book_fair"])

        # ---- totals ---------------------------------------------------------
        totals_data = _analyse_totals(ev)
        totals_list = []
        for line, td in sorted(totals_data.items()):
            for name, od in td["outcomes"].items():
                edge = od["edge"]
                if edge is not None and edge > EDGE_MIN * 100:
                    singles.append({
                        "match":      label,
                        "commence":   comm,
                        "market":     "totals",
                        "outcome":    f"{name} {line}",
                        "fair_prob":  od["fair"] / 100,
                        "best_price": od["best_price"],
                        "best_book":  od["best_book"],
                        "paddy":      None,
                        "edge":       edge,
                        "pm_gap":     None,
                        "confidence": "medium" if edge > VALUE_THRESHOLD * 100 else "low",
                        "kalshi":     None,
                        "poly":       None,
                    })
            totals_list.append({"line": line, **td})

        matches.append({
            "label":      label,
            "commence":   comm,
            "margin":     round(h2h_r["margin"] * 100, 1),
            "max_gap":    round(max_gap, 1),
            "has_pm_data": bool(kl_probs or pm_probs),
            "outcomes":   h2h_outcomes,
            "totals":     totals_list,
        })

    matches.sort(key=lambda m: (-abs(m["max_gap"]) if m["has_pm_data"] else 999, m["commence"]))
    singles.sort(key=lambda s: -s["edge"])

    parlays = _build_parlays(singles)

    # Sorted bookmaker list for the frontend dropdown
    # Put Paddy Power first if present, then alphabetical
    book_list = sorted(all_books)
    if "Paddy Power" in book_list:
        book_list.remove("Paddy Power")
        book_list.insert(0, "Paddy Power")

    return {
        "fetched_at": int(time.time()),
        "matches":    matches,
        "bookmakers": book_list,
        "bets": {
            "singles": singles,
            "parlays": parlays,
        },
    }


# ---------------------------------------------------------------------------
# Parlay builder
# ---------------------------------------------------------------------------

def _build_parlays(singles, max_legs=3, top_n=10):
    """
    Generate 2- and 3-leg parlays from value singles.
    Rules:
    - No two legs from the same match
    - Combined EV = prod(fair_prob) * prod(best_price) - 1 must be > PARLAY_MIN
    - Sort by combined EV descending
    """
    parlays = []

    # Only use positively-edged singles, capped at top 20 to avoid explosion
    candidates = [s for s in singles if s["edge"] > 0][:20]

    for n_legs in (2, 3):
        for combo in itertools.combinations(candidates, n_legs):
            # Reject if any two legs share the same match
            matches_used = [c["match"] for c in combo]
            if len(set(matches_used)) < n_legs:
                continue

            combined_fair  = 1.0
            combined_price = 1.0
            for leg in combo:
                combined_fair  *= leg["fair_prob"]
                combined_price *= leg["best_price"]

            ev = combined_fair * combined_price - 1.0
            if ev < PARLAY_MIN:
                continue

            confidence_scores = {"high": 3, "medium": 2, "low": 1}
            min_conf = min(combo, key=lambda c: confidence_scores.get(c["confidence"], 0))["confidence"]

            parlays.append({
                "legs":           [_leg_summary(c) for c in combo],
                "combined_price": round(combined_price, 2),
                "combined_fair":  round(combined_fair * 100, 1),
                "ev_pct":         round(ev * 100, 1),
                "confidence":     min_conf,
            })

    parlays.sort(key=lambda p: -p["ev_pct"])
    return parlays[:top_n]


def _leg_summary(s):
    return {
        "match":      s["match"],
        "commence":   s["commence"],
        "market":     s["market"],
        "outcome":    s["outcome"],
        "best_price": s["best_price"],
        "best_book":  s["best_book"],
        "per_book":   s.get("per_book", {}),
        "paddy":      s.get("paddy"),
        "edge":       s["edge"],
        "confidence": s["confidence"],
    }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def get_raw(force=False):
    with _lock:
        age = time.time() - _cache["fetched_at"]
        if force or _cache["raw"] is None or age > _CACHE_TTL:
            _cache["raw"] = _build_raw()
            _cache["fetched_at"] = time.time()
        return _cache["raw"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/divergence")
def divergence():
    d = get_raw()
    return JSONResponse({"fetched_at": d["fetched_at"], "matches": d["matches"]})


@app.get("/api/bets")
def bets():
    d = get_raw()
    return JSONResponse({"fetched_at": d["fetched_at"], "bets": d["bets"], "bookmakers": d.get("bookmakers", [])})


@app.get("/api/refresh")
def refresh():
    d = get_raw(force=True)
    return JSONResponse({"fetched_at": d["fetched_at"], "matches": d["matches"], "bets": d["bets"]})


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=False)
