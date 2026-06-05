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
import football_intel as fintel

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

REGIONS = "uk"             # UK region covers all Irish-accessible bookmakers

# Only show prices from bookmakers the user has accounts with
BOOKMAKER_WHITELIST = {
    "Paddy Power", "Betfair", "Betfair Exchange",
    "Bet365", "BoyleSports", "Ladbrokes", "William Hill",
}
EDGE_MIN   = 0.005         # flag singles with >0.5% edge
PARLAY_MIN = 0.005         # minimum combined EV to include a parlay
VALUE_THRESHOLD = 0.015    # 1.5% edge = "clear value"

# ---------------------------------------------------------------------------
# Cache — one shared fetch for all endpoints
# ---------------------------------------------------------------------------
_cache = {"raw": None, "fetched_at": 0}
_CACHE_TTL = 300
_lock = threading.Lock()

# Separate intel cache — populated by background thread
_intel_cache = {}          # {match_label: intel_dict}
_intel_lock  = threading.Lock()
_intel_busy  = False       # True while background fetch is running
_teams_busy  = False       # True while team snapshot fetches are running

# Pre-load cached intel from disk so restarts don't lose analysis
_disk_intel = fintel.load_intel_from_disk()
if _disk_intel:
    _intel_cache.update(_disk_intel)
    print(f"[startup] loaded {len(_disk_intel)} intel entries from disk")


# ---------------------------------------------------------------------------
# Bookmaker data helpers
# ---------------------------------------------------------------------------

def _fetch_events():
    """Pull h2h + totals + spreads (Asian handicap) in a single API call."""
    key = wc_odds.find_world_cup_key()
    return wc_odds.get(
        f"/sports/{key}/odds",
        regions=REGIONS,
        markets="h2h,totals,spreads",
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


def _analyse_spreads(event):
    """
    De-vig Asian handicap (spreads) market.
    Returns { (team_name, point): {fair_prob, best_price, best_book, edge} }
    Only includes lines where at least 3 books agree (avoids one-off lines).
    """
    line_prices = defaultdict(list)   # (team_name, point) -> [(price, bookmaker)]
    line_best   = {}                   # (team_name, point) -> (best_price, best_book)
    line_book_count = defaultdict(set) # point -> set of bookmakers

    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market["key"] != "spreads":
                continue
            for o in market["outcomes"]:
                point = o.get("point")
                if point is None:
                    continue
                key = (o["name"], point)
                price = o["price"]
                line_prices[key].append((price, bm["title"]))
                line_book_count[point].add(bm["title"])
                if key not in line_best or price > line_best[key][0]:
                    line_best[key] = (price, bm["title"])

    # Group by point, only process lines with at least 3 books
    by_point = defaultdict(dict)
    for (team_name, point), prices in line_prices.items():
        if len(line_book_count[point]) >= 3:
            by_point[point][team_name] = prices

    result = {}
    for point, sides in by_point.items():
        if len(sides) != 2:
            continue
        avg_implied = {
            team: sum(1.0/p for p, _ in prices) / len(prices)
            for team, prices in sides.items()
        }
        fair, _ = _devig(avg_implied)
        for team, fp in fair.items():
            bp_price, bp_book = line_best.get((team, point), (None, None))
            if not bp_price:
                continue
            edge = round((fp - 1.0/bp_price) * 100, 2)
            result[(team, point)] = {
                "fair_prob": fp,
                "best_price": bp_price,
                "best_book": bp_book,
                "edge": edge,
            }
    return result


def _all_spread_prices(event, team_name, point):
    """Return {bookmaker: price} for a specific team + handicap line."""
    result = {}
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market["key"] != "spreads":
                continue
            for o in market["outcomes"]:
                if o.get("name") == team_name and o.get("point") == point:
                    result[bm["title"]] = o["price"]
    return result


# ---------------------------------------------------------------------------
# Background intel fetch
# ---------------------------------------------------------------------------

def _build_intel_requests(singles):
    """Build intel request list from singles, one entry per unique match."""
    intel_requests = []
    seen_matches   = set()
    for s in singles:
        match_label = s["match"]
        if match_label in seen_matches:
            continue
        seen_matches.add(match_label)
        parts = match_label.split(" vs ", 1)
        if len(parts) != 2:
            continue
        home_raw, away_raw = parts
        match_singles = [x for x in singles if x["match"] == match_label]
        price_notes   = "\n".join(
            f"- {x['outcome'].upper()}: book fair {x['fair_prob']*100:.1f}% "
            f"vs best price {x['best_price']} ({x['best_book']}) "
            f"= +{x['edge']:.1f}% edge"
            + (f", Kalshi {x['kalshi']}%" if x['kalshi'] else "")
            + (f", PM gap {x['pm_gap']:+.1f}%" if x['pm_gap'] else "")
            for x in match_singles
        )
        intel_requests.append({
            "home":        home_raw,
            "away":        away_raw,
            "commence":    s["commence"],
            "price_notes": price_notes,
        })
    return intel_requests


def _run_intel_bg(intel_requests):
    global _intel_busy
    print(f"[intel] background fetch starting for {len(intel_requests)} match(es)...")
    try:
        raw_map = fintel.get_intel_batch(intel_requests, max_calls=MAX_INTEL_MATCHES)
        with _intel_lock:
            for req in intel_requests:
                ck = fintel._cache_key(req["home"], req["away"])
                if ck in raw_map:
                    label = req["home"] + " vs " + req["away"]
                    _intel_cache[label] = raw_map[ck]
        print(f"[intel] background fetch done — {len(_intel_cache)} match(es) cached")
    except Exception as e:
        print(f"[intel] background fetch failed: {e}")
    finally:
        _intel_busy = False


MAX_INTEL_MATCHES = 3   # top N matches analysed sequentially — ~30-45s each with web search

def _team_key(t):
    return t.lower().strip()


def _trigger_intel_bg(singles):
    """Start background intel fetch only for matches missing from cache."""
    global _intel_busy
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return
    if _intel_busy:
        return

    with _intel_lock:
        cached_labels = set(_intel_cache.keys())

    all_requests = _build_intel_requests(singles)   # already sorted by edge (singles are sorted)
    missing = [r for r in all_requests
               if (r["home"] + " vs " + r["away"]) not in cached_labels]
    missing = missing[:MAX_INTEL_MATCHES]           # cap to top N

    if not missing:
        return

    _intel_busy = True
    t = threading.Thread(target=_run_intel_bg, args=(missing,), daemon=True)
    t.start()


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
        book_table = {k: v for k, v in book_table.items() if k in BOOKMAKER_WHITELIST}
        all_books.update(book_table.keys())

        # ---- h2h outcomes ---------------------------------------------------
        h2h_outcomes = []
        max_gap = 0.0

        for raw_name, fair_p in h2h_r["fair"].items():
            norm = "draw" if pmkt._is_draw(raw_name) else pmkt.normalize_team(raw_name)
            # Per-bookmaker prices for this outcome (whitelisted books only)
            per_book = {bk: prices[raw_name] for bk, prices in book_table.items() if raw_name in prices}
            paddy = per_book.get("Paddy Power")
            # Best price from whitelisted books only
            if per_book:
                bp_book  = max(per_book, key=per_book.get)
                bp_price = per_book[bp_book]
            else:
                bp_price, bp_book = h2h_r["best_price"].get(raw_name, (None, None))

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
                        "per_book":   {},
                        "paddy":      None,
                        "edge":       edge,
                        "pm_gap":     None,
                        "confidence": "medium" if edge > VALUE_THRESHOLD * 100 else "low",
                        "kalshi":     None,
                        "poly":       None,
                    })
            totals_list.append({"line": line, **td})

        # ---- spreads (Asian handicap) ---------------------------------------
        spreads_data = _analyse_spreads(ev)
        for (team_name, point), sd in spreads_data.items():
            if sd["edge"] is None or sd["edge"] <= EDGE_MIN * 100:
                continue
            per_book = _all_spread_prices(ev, team_name, point)
            per_book = {k: v for k, v in per_book.items() if k in BOOKMAKER_WHITELIST}
            paddy = per_book.get("Paddy Power")
            if per_book:
                bp_book  = max(per_book, key=per_book.get)
                bp_price = per_book[bp_book]
            else:
                bp_price = sd["best_price"]
                bp_book  = sd["best_book"]
            edge = round((sd["fair_prob"] - 1.0/bp_price) * 100, 2) if bp_price else None
            if edge is None or edge <= EDGE_MIN * 100:
                continue
            # Human-readable: "Germany (-1.5)" = Germany wins by 2+
            sign = "+" if point > 0 else ""
            outcome_label = f"{team_name} ({sign}{point:g})"
            singles.append({
                "match":      label,
                "commence":   comm,
                "market":     "spreads",
                "outcome":    outcome_label,
                "fair_prob":  sd["fair_prob"],
                "best_price": bp_price,
                "best_book":  bp_book,
                "per_book":   per_book,
                "paddy":      paddy,
                "edge":       edge,
                "pm_gap":     None,
                "confidence": "medium" if edge > VALUE_THRESHOLD * 100 else "low",
                "kalshi":     None,
                "poly":       None,
                # Keep raw handicap info for analyst matching
                "spread_team":  team_name,
                "spread_point": point,
            })

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

    # Attach any already-cached intel (from disk or previous background run)
    with _intel_lock:
        cached_intel = dict(_intel_cache)
    for s in singles:
        s["intel"] = cached_intel.get(s["match"])
        s["analyst_confirms"] = _analyst_confirms(s) if s["intel"] else None
    for p in parlays:
        for leg in p["legs"]:
            leg["intel"] = cached_intel.get(leg["match"])

    # Kick off background intel fetch (pre-fetches team snapshots then runs analysis)
    _trigger_intel_bg(singles)

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
# ---------------------------------------------------------------------------
# Analyst confirmation helper
# ---------------------------------------------------------------------------

def _analyst_confirms(single):
    """
    Check whether the intel's recommended_bets includes this single's outcome.
    Returns True (confirmed), False (contradicted), or None (no intel / old schema).
    """
    intel = single.get("intel")
    if not intel:
        return None

    rec_bets = intel.get("recommended_bets")
    if not rec_bets:
        # Old-schema intel — fall back to checking the legacy single recommendation field
        rec = intel.get("recommendation", {})
        old_outcome = rec.get("outcome", "")
        return _outcome_matches(single, old_outcome)

    for rb in rec_bets:
        if _outcome_matches(single, rb.get("outcome", ""), rb.get("market", "")):
            return True
    return False


def _outcome_matches(single, analyst_outcome, analyst_market=""):
    """Map analyst outcome string to a single bet's outcome + market."""
    s_market  = single.get("market", "")
    s_outcome = single.get("outcome", "").lower()
    # Extract home/away team names from match label "Home vs Away"
    match_label = single.get("match", "")
    parts       = match_label.split(" vs ", 1)
    home_name   = parts[0].lower() if len(parts) == 2 else ""
    away_name   = parts[1].lower() if len(parts) == 2 else ""

    ao = analyst_outcome.lower().replace(" ", "_")

    if s_market == "h2h":
        if ao == "home_win":   return s_outcome == home_name
        if ao == "away_win":   return s_outcome not in (home_name, "draw") and s_outcome != ""
        if ao == "draw":       return s_outcome == "draw"

    elif s_market == "totals":
        if ao.startswith("over"):   return "over" in s_outcome
        if ao.startswith("under"):  return "under" in s_outcome

    elif s_market == "spreads":
        # analyst_outcome format: "home_-1.5" or "away_+1" etc.
        spread_team  = single.get("spread_team", "").lower()
        spread_point = single.get("spread_point")
        if ao.startswith("home_"):
            try:
                target_pt = float(ao.split("home_")[1])
                return spread_team == home_name and spread_point == target_pt
            except ValueError:
                return spread_team == home_name
        if ao.startswith("away_"):
            try:
                target_pt = float(ao.split("away_")[1])
                return spread_team == away_name and spread_point == target_pt
            except ValueError:
                return spread_team == away_name
    return False


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

    # Only use positively-edged singles where fair_prob >= 12%
    # This prevents combining low-probability draws/upsets that produce
    # misleadingly huge combined prices but near-zero real chance of winning
    candidates = [s for s in singles if s["edge"] > 0 and s["fair_prob"] >= 0.12][:20]

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
                "combined_fair":  round(combined_fair * 100, 3),
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
    # Attach latest intel from background cache before responding
    with _intel_lock:
        cached_intel = dict(_intel_cache)
    bets_data = d["bets"]
    for s in bets_data["singles"]:
        s["intel"] = cached_intel.get(s["match"])
    for p in bets_data["parlays"]:
        for leg in p["legs"]:
            leg["intel"] = cached_intel.get(leg["match"])
    return JSONResponse({
        "fetched_at":   d["fetched_at"],
        "bets":         bets_data,
        "bookmakers":   d.get("bookmakers", []),
        "intel_ready":  len(cached_intel),
        "intel_loading": _intel_busy,
    })


@app.get("/api/intel")
def intel():
    """Returns current intel map — call this to refresh analyst cards without re-fetching odds."""
    with _intel_lock:
        cached_intel = dict(_intel_cache)
    return JSONResponse({
        "intel":         cached_intel,
        "intel_ready":   len(cached_intel),
        "intel_loading": _intel_busy,
    })


@app.get("/api/refresh-injuries")
def refresh_injuries():
    """Force re-fetch of injury/suspension data for all teams with value bets."""
    d = get_raw()
    teams = set()
    for s in d["bets"]["singles"]:
        parts = s["match"].split(" vs ", 1)
        if len(parts) == 2:
            teams.add(parts[0]); teams.add(parts[1])

    def _do_refresh():
        fintel.refresh_injuries_for_teams(sorted(teams), force=True)
        # Clear intel cache so next load re-analyses with fresh injury data
        with _intel_lock:
            _intel_cache.clear()
        import pathlib
        pathlib.Path("intel_cache.json").unlink(missing_ok=True)
        print(f"[injuries] refresh done for {len(teams)} teams")

    threading.Thread(target=_do_refresh, daemon=True).start()
    return JSONResponse({"status": "refreshing", "teams": len(teams)})


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
