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
import sys
import time
import pathlib
import secrets
import itertools
import threading
from datetime import datetime, timezone
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
import static_data

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# ---------------------------------------------------------------------------
# Lightweight visitor tracking (real client IP via X-Forwarded-For, since the
# app sits behind Render's proxy). In-memory only — resets on restart/redeploy.
# View at /admin/stats?key=<ADMIN_KEY>. The key is read from the ADMIN_KEY env
# var, or a random one is generated and printed to the logs at startup.
# ---------------------------------------------------------------------------
_ADMIN_KEY    = os.environ.get("ADMIN_KEY") or secrets.token_urlsafe(8)
_access_lock  = threading.Lock()
_visitors     = {}   # ip -> {hits, first, last, last_path}
print(f"[admin] visitor stats at /admin/stats?key={_ADMIN_KEY}")


def _client_ip(request):
    """Real visitor IP: first hop in X-Forwarded-For, else the socket peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "?"


@app.middleware("http")
async def _track_visitors(request, call_next):
    path = request.url.path
    if not path.startswith(("/admin", "/static")):
        ip  = _client_ip(request)
        now = int(time.time())
        with _access_lock:
            v = _visitors.get(ip)
            if v is None:
                _visitors[ip] = {"hits": 1, "first": now, "last": now, "last_path": path}
                print(f"[access] NEW visitor {ip} (unique so far: {len(_visitors)})")
            else:
                v["hits"] += 1; v["last"] = now; v["last_path"] = path
        if path == "/":
            print(f"[access] {ip} opened the app")
    return await call_next(request)


REGIONS = "uk"             # UK region covers all Irish-accessible bookmakers

# Only show prices from bookmakers the user has accounts with
BOOKMAKER_WHITELIST = {
    "Paddy Power", "Betfair", "Betfair Exchange",
    "Bet365", "BoyleSports", "Ladbrokes", "William Hill",
}
# Exchanges: better prices on singles, but you CANNOT place accumulators on them.
# So they're used for singles but excluded from accumulator leg pricing.
EXCHANGE_BOOKS = {"Betfair", "Betfair Exchange", "Matchbook", "Smarkets"}
EDGE_MIN   = 0.005         # flag singles with >0.5% edge
PARLAY_MIN = 0.005         # minimum combined EV to include a parlay
VALUE_THRESHOLD = 0.015    # 1.5% edge = "clear value"

# Accumulator risk presets — drive _build_parlays().
#   min_leg_prob      : reject any leg below this fair (de-vigged) probability
#   legs              : which leg-counts to generate
#   min_combined_prob : the WHOLE slip must have at least this chance of landing
# The point: an acca of strong favourites still multiplies your odds up, but the
# win-probability multiplies *down* fast — so we floor the combined chance, not
# just the per-leg chance, and rank by chance-of-landing rather than payout.
ACCA_PRESETS = {
    "banker":   {"min_leg_prob": 0.62, "legs": (2, 3, 4),    "min_combined_prob": 0.30},
    "balanced": {"min_leg_prob": 0.55, "legs": (4, 5, 6),    "min_combined_prob": 0.12},
    "punchy":   {"min_leg_prob": 0.45, "legs": (6, 7, 8),    "min_combined_prob": 0.04},
}
# Value guard: with it on, drop any leg whose best price is more than this far
# (in edge %) below fair. Keeps only well-priced legs. -4% lets strong favourites
# survive on sportsbook prices (they shade favourites harder than the exchange).
ACCA_GUARD_TOL_PCT = -4.0

# ---------------------------------------------------------------------------
# Cache — one shared fetch for all endpoints
# ---------------------------------------------------------------------------
_cache = {"raw": None, "fetched_at": 0}
_CACHE_TTL = 7200  # 2 hours — WC odds move slowly, no need to hammer the API
_ODDS_CACHE_FILE = pathlib.Path("odds_cache.json")
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
            # Per-bookmaker prices for this outcome (best price per book), so an
            # acca can be priced at a single book rather than line-shopped.
            pb = {}
            for price, bk in book_prices.get(name, []):
                if bk not in pb or price > pb[bk]:
                    pb[bk] = price
            outcomes[name] = {
                "fair":       round(fp * 100, 1),
                "best_price": best_price,
                "best_book":  best_book,
                "per_book":   pb,
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


MAX_INTEL_MATCHES = 6   # top N matches analysed; sized to fit Tier-1 rate limits
                        # (30k input tokens/min). Raise once on a higher API tier.

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

def _analyst_token(c):
    """
    Map a priced acca_pool outcome to the analyst's outcome vocabulary
    (home_win|away_win|draw|over_2.5|under_1.5|home_-1.5|away_+1 ...), so the
    Bettor's Analysis tab can look up real odds for each recommended bet.
    Returns the token string, or None if it can't be mapped.
    """
    m = c.get("market")
    if m == "totals":
        # "Over 2.5" -> "over_2.5"
        return c["outcome"].lower().replace(" ", "_")

    parts = c["match"].split(" vs ", 1)
    if len(parts) != 2:
        return None
    home, away = parts

    if m == "h2h":
        o = c["outcome"]
        if o == "draw":                       return "draw"
        if o == pmkt.normalize_team(home):    return "home_win"
        if o == pmkt.normalize_team(away):    return "away_win"
        return None

    if m == "spreads":
        team, pt = c.get("spread_team"), c.get("spread_point")
        if team is None or pt is None:
            return None
        side = "home" if team == home else "away" if team == away else None
        if side is None:
            return None
        # home_-1.5  /  away_+1  (negative carries its own sign)
        return f"{side}_{pt:g}" if pt < 0 else f"{side}_+{pt:g}"

    return None


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
    acca_pool   = []   # ALL outcomes (incl. favourites) — candidate legs for accas
    all_books   = set()
    weather_by_label = {}   # match label -> weather signal (or None)
    round_by_label   = {}   # match label -> {label, order} round (or None)

    # Warm the forecast cache concurrently so per-match weather lookups are instant
    try:
        fintel.prewarm_weather(
            (ev["home_team"], ev["away_team"], ev.get("commence_time", "")) for ev in events
        )
    except Exception as e:
        print(f"[weather] prewarm failed: {e}")

    for ev in events:
        h2h_r = _analyse_h2h(ev)
        if not h2h_r:
            continue

        home, away = ev["home_team"], ev["away_team"]
        mk    = pmkt.match_key(home, away)
        label = f"{home} vs {away}"
        comm  = h2h_r["commence"]
        weather_by_label[label] = fintel.weather_signal(home, away, comm)
        _r = static_data.match_round(home, away)
        round_by_label[label] = {"label": _r[0], "order": _r[1]} if _r else None

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

            # Collect EVERY priced outcome as an acca candidate (favourites
            # included — these never reach the value-singles list below).
            if bp_price:
                acca_pool.append({
                    "match":       label,
                    "commence":    comm,
                    "market":      "h2h",
                    "outcome":     norm,
                    "fair_prob":   fair_p,
                    "best_price":  bp_price,
                    "best_book":   bp_book,
                    "per_book":    per_book,
                    "paddy":       paddy,
                    "edge":        edge if edge is not None else 0.0,
                    "confidence":  confidence or "low",
                })

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
                if od.get("best_price") and od.get("fair") is not None:
                    acca_pool.append({
                        "match":      label,
                        "commence":   comm,
                        "market":     "totals",
                        "outcome":    f"{name} {line}",
                        "fair_prob":  od["fair"] / 100,
                        "best_price": od["best_price"],
                        "best_book":  od["best_book"],
                        "per_book":   od.get("per_book", {}),
                        "paddy":      None,
                        "edge":       edge if edge is not None else 0.0,
                        "confidence": "low",
                    })
                if edge is not None and edge > EDGE_MIN * 100:
                    singles.append({
                        "match":      label,
                        "commence":   comm,
                        "market":     "totals",
                        "outcome":    f"{name} {line}",
                        "fair_prob":  od["fair"] / 100,
                        "best_price": od["best_price"],
                        "best_book":  od["best_book"],
                        "per_book":   od.get("per_book", {}),
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
            if sd.get("fair_prob") is None:
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
            if not bp_price:
                continue
            edge = round((sd["fair_prob"] - 1.0/bp_price) * 100, 2)
            # Human-readable: "Germany (-1.5)" = Germany wins by 2+
            sign = "+" if point > 0 else ""
            outcome_label = f"{team_name} ({sign}{point:g})"

            # Every priced handicap is an acca candidate (e.g. a nailed-on +2).
            acca_pool.append({
                "match":        label,
                "commence":     comm,
                "market":       "spreads",
                "outcome":      outcome_label,
                "fair_prob":    sd["fair_prob"],
                "best_price":   bp_price,
                "best_book":    bp_book,
                "per_book":     per_book,
                "paddy":        paddy,
                "edge":         edge,
                "confidence":   "low",
                "spread_team":  team_name,   # for analyst-recommendation odds lookup
                "spread_point": point,
            })

            if edge > EDGE_MIN * 100:
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
            "weather":    weather_by_label.get(label),
            "round":      round_by_label.get(label),
        })

    # Accumulators can't be placed on exchanges — re-price every acca leg using
    # SPORTSBOOKS ONLY (drop exchange prices, recompute best + edge). Legs that
    # only exist at an exchange are dropped from acca eligibility. Singles are a
    # separate list and keep the exchange.
    sb_pool = []
    for c in acca_pool:
        pb = {k: v for k, v in (c.get("per_book") or {}).items() if k not in EXCHANGE_BOOKS}
        if pb:
            c["per_book"]   = pb
            c["best_book"]  = max(pb, key=pb.get)
            c["best_price"] = pb[c["best_book"]]
            c["edge"]       = round((c["fair_prob"] - 1.0 / c["best_price"]) * 100, 2)
            sb_pool.append(c)
        elif c.get("best_book") not in EXCHANGE_BOOKS and c.get("best_price"):
            sb_pool.append(c)   # no per-book detail (totals/spreads) but already a sportsbook
        # else: only priced at an exchange -> not acca-placeable, drop it
    acca_pool = sb_pool

    # Attach the weather signal + round to every leg/single by match label
    for s in singles:
        s["weather"] = weather_by_label.get(s["match"])
        s["round"]   = round_by_label.get(s["match"])
    for c in acca_pool:
        c["weather"] = weather_by_label.get(c["match"])
        c["round"]   = round_by_label.get(c["match"])

    matches.sort(key=lambda m: (-abs(m["max_gap"]) if m["has_pm_data"] else 999, m["commence"]))
    singles.sort(key=lambda s: -s["edge"])

    # Price index for analyst recommendations: {label: {analyst_token: {...}}}.
    # Lets the Bettor's Analysis tab show real odds next to each recommended bet.
    price_index = {}
    for c in acca_pool:
        tok = _analyst_token(c)
        if not tok:
            continue
        price_index.setdefault(c["match"], {})[tok] = {
            "best_price": c["best_price"],
            "best_book":  c["best_book"],
            "per_book":   c.get("per_book", {}),
            "edge":       c.get("edge"),
        }

    parlays = _build_parlays(acca_pool)

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
            "acca_pool": acca_pool,
        },
        "price_index": price_index,
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

def _best_single_book(combo):
    """
    Best combined price obtainable on a SINGLE bookmaker for this slip.

    An acca has to be placed on one book — you can't take leg 1 at Paddy Power
    and leg 2 at Bet365 on the same slip. So we price the whole combo at each
    book that quotes EVERY leg and keep the book with the highest combined price.

    Returns (book_name, combined_price, mixed_books):
      - book_name / price from the best single book when one covers all legs.
      - if no single book covers all legs the slip isn't placeable as one acca:
        mixed_books=True, book_name=None, and price falls back to the per-leg
        best (line-shopped) purely so the slip can still be shown, clearly flagged.
    """
    books_per_leg = [set((leg.get("per_book") or {}).keys()) for leg in combo]
    common = set.intersection(*books_per_leg) if all(books_per_leg) else set()
    if common:
        best_book, best_price = None, 0.0
        for bk in common:
            prod = 1.0
            for leg in combo:
                prod *= leg["per_book"][bk]
            if prod > best_price:
                best_book, best_price = bk, prod
        return best_book, round(best_price, 2), False
    # No single book prices all legs — not a one-slip acca.
    prod = 1.0
    for leg in combo:
        prod *= leg["best_price"]
    return None, round(prod, 2), True


def _build_parlays(singles, risk="balanced", value_guard=True, top_n=36, round_filter=None):
    """
    Generate high-probability accumulators from the value singles.

    round_filter : None -> build across all rounds (slips may be multi-round)
                   "Group Stage R1"/etc -> only legs from that round, so every
                   slip is a single-round acca (e.g. a "Round 1 only" acca).
    risk         : "banker" | "balanced" | "punchy"  -> see ACCA_PRESETS
    value_guard  : True  -> drop legs whose best price is worse than ~2.5% under
                            fair, i.e. keep only well-priced (low-margin) legs.
                            A high-probability favourites acca is never strictly
                            +EV (books shade favourites), so the guard minimises
                            the bookmaker margin rather than eliminating it.
                   False -> pick the most-likely outcomes regardless of price.

    Legs are floored on per-leg probability; the whole slip is floored on
    combined probability; results are ranked by chance-of-landing, not payout.
    """
    preset = ACCA_PRESETS.get(risk, ACCA_PRESETS["balanced"])
    min_leg_prob      = preset["min_leg_prob"]
    leg_counts        = preset["legs"]
    min_combined_prob = preset["min_combined_prob"]

    # Eligible legs across ALL markets (1X2, totals, handicaps): high enough
    # single-outcome probability. When the value guard is on we also drop legs
    # priced well below fair, so we line-shop into the lowest-margin price.
    eligible = [
        s for s in singles
        if s["fair_prob"] >= min_leg_prob and (s["edge"] >= ACCA_GUARD_TOL_PCT if value_guard else True)
        and (round_filter is None or (s.get("round") or {}).get("label") == round_filter)
    ]

    # One leg per match (a standard acca can't combine correlated same-match
    # outcomes — that's a Same-Game Multi). Keep each match's most nailed-on leg,
    # whatever market it's in. This also bounds the combinatorics cleanly.
    best_by_match = {}
    for s in eligible:
        cur = best_by_match.get(s["match"])
        if cur is None or s["fair_prob"] > cur["fair_prob"]:
            best_by_match[s["match"]] = s
    candidates = sorted(best_by_match.values(), key=lambda s: -s["fair_prob"])[:16]

    parlays = []
    for n_legs in leg_counts:
        if n_legs > len(candidates):
            continue
        for combo in itertools.combinations(candidates, n_legs):
            combined_fair = 1.0
            for leg in combo:
                combined_fair *= leg["fair_prob"]

            # The whole slip must clear the combined-probability floor.
            if combined_fair < min_combined_prob:
                continue

            # Price the slip at a SINGLE book (see _best_single_book) — never
            # line-shop different books across legs, which yields a price no
            # bookmaker will actually lay.
            acca_book, combined_price, mixed_books = _best_single_book(combo)

            ev = combined_fair * combined_price - 1.0

            confidence_scores = {"high": 3, "medium": 2, "low": 1}
            min_conf = min(combo, key=lambda c: confidence_scores.get(c["confidence"], 0))["confidence"]

            # Round span: single-round (all legs same round) vs multi-round.
            rlabels = {c["round"]["label"] for c in combo if c.get("round")}
            if len(rlabels) == 1:
                round_label, round_span = next(iter(rlabels)), "single"
            elif rlabels:
                round_label, round_span = "Multi-round", "multi"
            else:
                round_label, round_span = None, None

            parlays.append({
                "legs":           [_leg_summary(c) for c in combo],
                "combined_price": round(combined_price, 2),
                "combined_fair":  round(combined_fair * 100, 2),
                "ev_pct":         round(ev * 100, 1),
                "confidence":     min_conf,
                "n_legs":         n_legs,
                "round_label":    round_label,
                "round_span":     round_span,
                "acca_book":      acca_book,
                "mixed_books":    mixed_books,
            })

    # Show a spread across leg counts. Ranking purely by chance would only ever
    # surface the shortest slips (fewer legs = higher combined prob), so the
    # bigger-odds accas would never appear. Keep the best few of EACH leg count.
    by_legs = {}
    for p in parlays:
        by_legs.setdefault(p["n_legs"], []).append(p)
    per_count = max(4, top_n // max(1, len(leg_counts)))
    out = []
    for n in leg_counts:
        best = sorted(by_legs.get(n, []), key=lambda p: (-p["combined_fair"], -p["ev_pct"]))
        out.extend(best[:per_count])
    return out


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
        "weather":    s.get("weather"),
        "round":      s.get("round"),
    }


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def get_raw(force=False):
    with _lock:
        # On first call after restart, try loading from disk before hitting the API
        if _cache["raw"] is None and not force and _ODDS_CACHE_FILE.exists():
            try:
                saved = json.loads(_ODDS_CACHE_FILE.read_text())
                age = time.time() - saved.get("fetched_at", 0)
                if age < _CACHE_TTL:
                    _cache["raw"] = saved["raw"]
                    _cache["fetched_at"] = saved["fetched_at"]
                    print(f"[odds] loaded from disk (age {age/60:.0f}m)", file=sys.stderr)
                    return _cache["raw"]
            except Exception:
                pass

        age = time.time() - _cache["fetched_at"]
        if force or _cache["raw"] is None or age > _CACHE_TTL:
            _cache["raw"] = _build_raw()
            _cache["fetched_at"] = time.time()
            try:
                _ODDS_CACHE_FILE.write_text(json.dumps({
                    "raw": _cache["raw"],
                    "fetched_at": _cache["fetched_at"],
                }))
            except Exception:
                pass
        return _cache["raw"]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/divergence")
def divergence():
    d = get_raw()
    return JSONResponse({"fetched_at": d["fetched_at"], "matches": d["matches"]})


@app.get("/api/bets")
def bets(risk: str = "balanced", value_guard: bool = True, round: str = ""):
    d = get_raw()
    # Attach latest intel from background cache before responding
    with _intel_lock:
        cached_intel = dict(_intel_cache)
    bets_data = d["bets"]
    # Rebuild accumulators per requested risk/value/round preset. Cheap (itertools
    # over ~24 cached singles), so the user can flip presets without re-fetching.
    if risk not in ACCA_PRESETS:
        risk = "balanced"
    round_filter = round.strip() or None
    pool = bets_data.get("acca_pool", [])
    parlays = _build_parlays(pool, risk=risk, value_guard=value_guard, round_filter=round_filter)
    for s in bets_data["singles"]:
        s["intel"] = cached_intel.get(s["match"])
    for p in parlays:
        for leg in p["legs"]:
            leg["intel"] = cached_intel.get(leg["match"])
    # Which markets the current odds feed actually offers, so the UI can be
    # honest about coverage (e.g. Asian handicaps aren't posted this far out).
    markets_available = sorted({p["market"] for p in pool})
    # Distinct rounds present (for the round dropdown), ordered by stage.
    _rd = {}
    for p in pool:
        r = p.get("round")
        if r:
            _rd[r["label"]] = r["order"]
    rounds_available = [lbl for lbl, _ in sorted(_rd.items(), key=lambda x: x[1])]
    return JSONResponse({
        "fetched_at":   d["fetched_at"],
        "bets":         {"singles": bets_data["singles"], "parlays": parlays},
        "risk":         risk,
        "value_guard":  value_guard,
        "round":        round_filter or "",
        "markets_available": markets_available,
        "rounds_available":  rounds_available,
        "bookmakers":   d.get("bookmakers", []),
        "intel_ready":  len(cached_intel),
        "intel_loading": _intel_busy,
    })


@app.get("/api/intel")
def intel():
    """Returns current intel map — call this to refresh analyst cards without re-fetching odds.
    Each recommended bet is enriched with the live best odds (price/book/edge)
    for that outcome so the Bettor's Analysis tab can show real prices."""
    with _intel_lock:
        cached_intel = dict(_intel_cache)

    price_index = get_raw().get("price_index", {})
    enriched = {}
    for label, intel_obj in cached_intel.items():
        recs = intel_obj.get("recommended_bets")
        if not recs:
            enriched[label] = intel_obj
            continue
        # Shallow-copy the intel + its bets so we never mutate the cache.
        obj = dict(intel_obj)
        match_prices = price_index.get(label, {})
        new_recs = []
        for rb in recs:
            rb2 = dict(rb)
            odds = match_prices.get(str(rb.get("outcome", "")).lower())
            rb2["best_price"] = odds["best_price"] if odds else None
            rb2["best_book"]  = odds["best_book"]  if odds else None
            rb2["per_book"]   = odds["per_book"]   if odds else {}
            rb2["edge"]       = odds["edge"]       if odds else None
            new_recs.append(rb2)
        obj["recommended_bets"] = new_recs
        enriched[label] = obj

    return JSONResponse({
        "intel":         enriched,
        "intel_ready":   len(enriched),
        "intel_loading": _intel_busy,
    })


@app.get("/admin/stats")
def admin_stats(key: str = ""):
    """Visitor stats — unique IPs + per-IP hit counts. Requires ?key=<ADMIN_KEY>."""
    if not secrets.compare_digest(key, _ADMIN_KEY):
        return JSONResponse({"error": "forbidden — append ?key=<ADMIN_KEY>"}, status_code=403)

    def _iso(ts):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")

    with _access_lock:
        rows = sorted(_visitors.items(), key=lambda kv: -kv[1]["last"])
        visitors = [{
            "ip":         ip,
            "hits":       v["hits"],
            "first_seen": _iso(v["first"]),
            "last_seen":  _iso(v["last"]),
            "last_path":  v["last_path"],
        } for ip, v in rows]
        total = sum(v["hits"] for v in _visitors.values())
    return JSONResponse({
        "unique_visitors": len(visitors),
        "total_requests":  total,
        "visitors":        visitors,
    })


@app.get("/api/injuries")
def injuries():
    """Cached tournament-wide injury digest for the Injuries tab — reads the
    cache only (no web search), so viewing it is free."""
    return JSONResponse(fintel.injury_digest_info())


@app.get("/api/refresh-injuries")
def refresh_injuries():
    """Refresh the tournament-wide injury digest (ONE BBC search), then invalidate
    only the analyst cards for matches whose team is named in the updated digest.
    Cards for teams the digest doesn't mention are kept as-is."""
    before = fintel.peek_injury_digest()

    def _do_refresh():
        after = fintel.fetch_wc_injury_digest(force=True)
        if not after or after == before:
            print("[injuries] digest refresh — no change, analyst cache kept intact")
            return

        text = after.lower()
        with _intel_lock:
            labels = list(_intel_cache.keys())
        affected_pairs, affected_labels = [], []
        for label in labels:
            p = label.split(" vs ", 1)
            if len(p) != 2:
                continue
            home, away = p
            if home.lower() in text or away.lower() in text:
                affected_pairs.append((home, away))
                affected_labels.append(label)

        fintel.invalidate_match_cache(affected_pairs)
        with _intel_lock:
            for label in affected_labels:
                _intel_cache.pop(label, None)
        print(f"[injuries] digest refreshed — {len(affected_labels)} analyst card(s) "
              f"invalidated (teams named in digest), rest kept")

        # Re-analyse the invalidated matches promptly.
        _trigger_intel_bg(get_raw()["bets"]["singles"])

    threading.Thread(target=_do_refresh, daemon=True).start()
    return JSONResponse({"status": "refreshing"})


@app.get("/api/refresh")
def refresh():
    d = get_raw(force=True)
    return JSONResponse({"fetched_at": d["fetched_at"], "matches": d["matches"], "bets": d["bets"]})


@app.get("/")
def index():
    # no-store so the browser always loads the latest UI (avoids stale-cache confusion)
    return FileResponse("static/index.html", headers={"Cache-Control": "no-store"})


app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    import uvicorn
    # Cloud hosts (Render etc.) inject the port to bind via $PORT; default to 8000 locally.
    # Pass the app object (not "server:app") so uvicorn doesn't re-import this module
    # and run all module-level startup twice.
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port, reload=False)
