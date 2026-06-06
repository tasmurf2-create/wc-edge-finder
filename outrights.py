#!/usr/bin/env python3
"""
WC 2026 outright / futures market analysis.

Markets covered:
  - Tournament Winner
  - To Reach Final / Semi-finals / Quarter-finals
  - Group Winner (A-L)
  - Top Goalscorer (Golden Boot)

Data sources:
  - The Odds API  (bookmaker prices, de-vigged)
  - Kalshi        (prediction market probability)
  - Polymarket    (prediction market probability)

Divergence logic is identical to match odds: where PM implied probability
exceeds the de-vigged bookmaker fair probability, that gap is the signal.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

import wc_odds
import prediction_markets as pmkt

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

REGIONS = os.environ.get("ODDS_REGIONS", "uk")
BOOKMAKER_WHITELIST = {
    "Paddy Power", "Betfair", "Betfair Exchange",
    "Bet365", "BoyleSports", "Ladbrokes", "William Hill",
}
CACHE_FILE = Path("outrights_cache.json")
CACHE_TTL  = 3600   # 1-hour cache — outrights move slowly

KALSHI_BASE      = pmkt.KALSHI_BASE
POLYMARKET_GAMMA = pmkt.POLYMARKET_GAMMA


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _devig(raw):
    total = sum(raw.values())
    return ({k: v / total for k, v in raw.items()}, total - 1.0) if total else ({}, 0.0)


def _http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "wc-outrights/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode())


def _looks_like_match(title: str) -> bool:
    return bool(re.search(r'\bvs?\.?\b', title, re.I))


def _classify_outright(title: str) -> str | None:
    """Map a market title to a canonical market type key, or None if unrecognised."""
    t = title.lower()
    # Golden Boot / Top Goalscorer
    if any(kw in t for kw in ("golden boot", "top scorer", "top goalscorer",
                               "most goals", "leading scorer")):
        return "top_goalscorer"
    # Tournament winner
    if any(kw in t for kw in ("win the tournament", "win the world cup",
                               "winner", "champions", "lift the trophy",
                               "world cup 2026 winner")):
        return "tournament_winner"
    # Stage progression
    if "final" in t and any(kw in t for kw in ("reach", "make", "qualify")):
        return "reach_final"
    if "semi" in t and any(kw in t for kw in ("reach", "make", "qualify")):
        return "reach_semis"
    if ("quarter" in t or "qf" in t) and any(kw in t for kw in ("reach", "make", "qualify")):
        return "reach_quarters"
    if "round of 16" in t and any(kw in t for kw in ("reach", "make", "qualify")):
        return "reach_r16"
    # Group markets
    if "group" in t and "winner" in t:
        return "group_winner"
    if "group" in t and ("qualify" in t or "advance" in t or "top 2" in t):
        return "qualify_group"
    return None


MARKET_LABELS = {
    "tournament_winner": "Tournament Winner",
    "reach_final":       "To Reach the Final",
    "reach_semis":       "To Reach Semi-finals",
    "reach_quarters":    "To Reach Quarter-finals",
    "reach_r16":         "To Reach Round of 16",
    "group_winner":      "Group Winner",
    "qualify_group":     "To Qualify from Group",
    "top_goalscorer":    "Golden Boot (Top Goalscorer)",
}


# ---------------------------------------------------------------------------
# Odds API — outright prices
# ---------------------------------------------------------------------------

def _fetch_book_outrights():
    """
    Query The Odds API for outright (futures) markets.
    Returns raw events list (empty if unavailable or quota exhausted).
    """
    try:
        key = wc_odds.find_world_cup_key()
        return wc_odds.get(
            f"/sports/{key}/odds",
            regions=REGIONS,
            markets="outrights",
            oddsFormat=wc_odds.ODDS_FORMAT,
        )
    except Exception as e:
        print(f"[outrights] odds-API fetch failed: {e}")
        return []


def _parse_book_outrights(events):
    """
    Parse raw outright events into structured form.
    Returns {market_type: {team_norm: {fair_prob, best_price, best_book, paddy, per_book, edge}}}
    """
    markets = defaultdict(lambda: defaultdict(list))   # mtype -> team -> [implied_probs]
    best    = defaultdict(dict)                         # mtype -> team -> (price, book)
    per_bk  = defaultdict(lambda: defaultdict(dict))   # mtype -> team -> {book: price}

    for ev in events:
        # Identify market type from event title or home_team field
        title = (ev.get("home_team") or ev.get("sport_title") or "").lower()
        mtype = _classify_outright(title)
        if not mtype:
            continue

        for bm in ev.get("bookmakers", []):
            book_name = bm.get("title", "")
            if book_name not in BOOKMAKER_WHITELIST:
                continue
            for mkt in bm.get("markets", []):
                if mkt.get("key") not in ("outrights", "h2h"):
                    continue
                for o in mkt.get("outcomes", []):
                    name  = pmkt.normalize_team(o.get("name", ""))
                    price = o.get("price")
                    if not name or not price:
                        continue
                    markets[mtype][name].append(1.0 / price)
                    per_bk[mtype][name][book_name] = price
                    if name not in best[mtype] or price > best[mtype][name][0]:
                        best[mtype][name] = (price, book_name)

    result = {}
    for mtype, teams in markets.items():
        if len(teams) < 2:
            continue
        avg_implied = {t: sum(v) / len(v) for t, v in teams.items()}
        fair, margin = _devig(avg_implied)
        outcomes = {}
        for team, fp in fair.items():
            bp, bb = best[mtype].get(team, (None, None))
            edge   = round((fp - 1.0 / bp) * 100, 2) if bp else None
            paddy  = per_bk[mtype][team].get("Paddy Power")
            outcomes[team] = {
                "fair_prob": round(fp * 100, 2),
                "best_price": bp,
                "best_book":  bb,
                "paddy":      paddy,
                "per_book":   dict(per_bk[mtype][team]),
                "edge":       edge,
            }
        result[mtype] = {"outcomes": outcomes, "margin": round(margin * 100, 1)}
    return result


# ---------------------------------------------------------------------------
# Kalshi — outright / futures
# ---------------------------------------------------------------------------

def _kalshi_prob(m):
    try:
        yb = float(m["yes_bid_dollars"])  if m.get("yes_bid_dollars")  is not None else None
        ya = float(m["yes_ask_dollars"])  if m.get("yes_ask_dollars")  is not None else None
    except (TypeError, ValueError):
        yb = ya = None
    if yb is not None and ya is not None:
        return (yb + ya) / 2
    try:
        return float(m["last_price_dollars"])
    except (TypeError, ValueError):
        return None


def _fetch_kalshi_outrights():
    """
    Search all open Kalshi events for WC 2026 outright markets.
    Returns {market_type: {team_norm: prob_0_to_1}}
    """
    results = defaultdict(dict)
    cursor  = None

    for _ in range(10):
        params = {"status": "open", "with_nested_markets": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        url = f"{KALSHI_BASE}/events?" + urllib.parse.urlencode(params)
        try:
            data = _http_get(url)
        except Exception as e:
            print(f"[kalshi outrights] request failed: {e}")
            break

        for ev in data.get("events", []):
            title = (ev.get("title") or "").lower()
            if not any(kw in title for kw in ("world cup", "wc26", "wc 2026", "fifa 2026")):
                continue
            if _looks_like_match(title):
                continue

            # Check event-level classification first
            mtype = _classify_outright(title)

            for m in ev.get("markets", []):
                prob = _kalshi_prob(m)
                if prob is None:
                    continue
                label = (m.get("yes_sub_title") or m.get("subtitle") or
                         m.get("question") or "").strip()
                if not label:
                    continue

                # If event-level mtype known, label is the team
                eff_mtype = mtype
                if not eff_mtype:
                    eff_mtype = _classify_outright(label)
                if not eff_mtype:
                    continue

                team = pmkt.normalize_team(label)
                if team:
                    results[eff_mtype][team] = prob

        cursor = data.get("cursor")
        if not cursor:
            break

    return dict(results)


# ---------------------------------------------------------------------------
# Polymarket — outright / futures
# ---------------------------------------------------------------------------

def _fetch_polymarket_outrights(max_pages=4, page_size=500):
    """
    Scan Polymarket events for WC 2026 outright markets.
    Returns {market_type: {team_norm: prob_0_to_1}}
    """
    results = defaultdict(dict)

    for page in range(max_pages):
        params = {"active": "true", "closed": "false",
                  "limit": page_size, "offset": page * page_size}
        url = f"{POLYMARKET_GAMMA}/events?" + urllib.parse.urlencode(params)
        try:
            events = _http_get(url)
        except Exception as e:
            print(f"[polymarket outrights] page {page} failed: {e}")
            break
        if not events:
            break

        for ev in events:
            title = (ev.get("title") or ev.get("question") or "").lower()
            if not any(kw in title for kw in ("world cup", "wc 2026", "fifa 2026")):
                continue
            if _looks_like_match(title):
                continue

            ev_mtype = _classify_outright(title)

            for m in (ev.get("markets") or []):
                q     = (m.get("question") or "").lower()
                label = (m.get("groupItemTitle") or "").strip()

                mtype = ev_mtype or _classify_outright(q)
                if not mtype:
                    continue

                try:
                    prices = json.loads(m.get("outcomePrices") or "[]")
                    p_yes  = float(prices[0]) if prices else None
                except (json.JSONDecodeError, ValueError, IndexError):
                    p_yes = None

                if p_yes is None:
                    continue

                # Get team name: prefer groupItemTitle, fall back to extracting from question
                if not label:
                    match = re.search(r'will ([A-Za-z\s]+?) (?:win|reach|advance)', q)
                    label = match.group(1).strip() if match else ""
                if not label:
                    continue

                team = pmkt.normalize_team(label)
                if team:
                    results[mtype][team] = p_yes

        if not events or len(events) < page_size:
            break

    return dict(results)


# ---------------------------------------------------------------------------
# Combined analysis
# ---------------------------------------------------------------------------

def get_outright_analysis(force=False):
    """
    Fetch from all sources, merge, and return structured outright analysis.
    Cached for CACHE_TTL seconds.

    Returns {
      market_type: {
        "label":    "Human-readable market name",
        "margin":   bookmaker_margin_pct_or_null,
        "rows": [
          {
            "team", "fair_prob", "best_price", "best_book", "paddy", "per_book",
            "pm_prob", "gap", "edge"
          }, ...
        ]
      }
    }
    """
    # Try disk cache
    if not force and CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - cached.get("_fetched_at", 0) < CACHE_TTL:
                return cached.get("data", {})
        except Exception:
            pass

    # Fetch from all sources
    book_events  = _fetch_book_outrights()
    book_markets = _parse_book_outrights(book_events)

    try:
        kalshi_out = _fetch_kalshi_outrights()
    except Exception as e:
        print(f"[outrights] kalshi failed: {e}")
        kalshi_out = {}

    try:
        poly_out = _fetch_polymarket_outrights()
    except Exception as e:
        print(f"[outrights] polymarket failed: {e}")
        poly_out = {}

    # Merge PM data (average Kalshi + Polymarket where both present)
    pm = defaultdict(dict)
    for mtype, teams in kalshi_out.items():
        for team, p in teams.items():
            pm[mtype][team] = p
    for mtype, teams in poly_out.items():
        for team, p in teams.items():
            if team in pm[mtype]:
                pm[mtype][team] = (pm[mtype][team] + p) / 2
            else:
                pm[mtype][team] = p

    # Build final output
    all_mtypes = set(list(book_markets.keys()) + list(pm.keys()))
    output = {}

    for mtype in all_mtypes:
        pm_data   = pm.get(mtype, {})
        book_data = book_markets.get(mtype, {}).get("outcomes", {})
        margin    = book_markets.get(mtype, {}).get("margin")

        if not book_data and not pm_data:
            continue

        all_teams = set(list(book_data.keys()) + list(pm_data.keys()))
        rows = []

        for team in all_teams:
            bd     = book_data.get(team, {})
            pm_raw = pm_data.get(team)
            pm_pct = round(pm_raw * 100, 1) if pm_raw is not None else None
            book_f = bd.get("fair_prob")
            gap    = round(pm_pct - book_f, 1) if (pm_pct is not None and book_f is not None) else None

            rows.append({
                "team":       team.title(),
                "fair_prob":  book_f,
                "best_price": bd.get("best_price"),
                "best_book":  bd.get("best_book"),
                "paddy":      bd.get("paddy"),
                "per_book":   bd.get("per_book", {}),
                "pm_prob":    pm_pct,
                "gap":        gap,
                "edge":       bd.get("edge"),
            })

        # Sort: largest positive gap (PM > books = underpriced by books) first
        rows.sort(key=lambda r: (-(r["gap"] or -99) if r["gap"] is not None else -99))

        output[mtype] = {
            "label":  MARKET_LABELS.get(mtype, mtype.replace("_", " ").title()),
            "margin": margin,
            "rows":   rows,
        }

    # Cache to disk
    try:
        CACHE_FILE.write_text(
            json.dumps({"data": output, "_fetched_at": time.time()},
                       indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception:
        pass

    return output
