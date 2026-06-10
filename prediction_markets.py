#!/usr/bin/env python3
"""
Prediction-market price fetchers: Polymarket (Gamma API) + Kalshi.

Why this exists: prediction markets run far lower margins than bookmakers and
are often sharper. Where their implied probability disagrees with the
bookmaker consensus, that gap is your strongest signal (this is exactly the
USA/Paraguay divergence from the research).

Each fetcher returns a dict keyed by a MATCH KEY (an unordered pair of
canonical team names), e.g.:

    { frozenset({"united states","paraguay"}):
        {"source": "polymarket",
         "teams": ("united states", "paraguay"),
         "probs": {"united states": 0.48, "draw": 0.28, "paraguay": 0.24}} }

Zero external dependencies (stdlib only).

!! IMPORTANT !!  The base URLs / params below are my best-known shapes but
these APIs change. In Claude Code, curl each endpoint FIRST, confirm the JSON
shape, and adjust the parsing. Search markers: "VERIFY".
"""
import os
import json
import unicodedata
import urllib.parse
import urllib.request
from collections import defaultdict

# ---- endpoints (VERIFY against live docs in Claude Code) --------------------
POLYMARKET_GAMMA = "https://gamma-api.polymarket.com"          # public, no key
KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"  # confirmed live
# Fallback host (if the above ever stops working):
#   "https://trading-api.kalshi.com/trade-api/v2"
# Reading public market data is keyless; trading needs auth.
KALSHI_WC_SERIES = "KXWCGAME"  # confirmed series ticker for World Cup 1X2 match markets

# ---- team-name normalization (the fiddly but essential part) ----------------
# Different sources spell the same nation differently. Map everything to one
# canonical token so matches line up across books + Polymarket + Kalshi.
ALIASES = {
    "usa": "united states", "us": "united states", "u s a": "united states",
    "korea republic": "south korea", "korea": "south korea",
    "republic of korea": "south korea",
    "czech republic": "czechia",
    "cote divoire": "ivory coast", "cote d ivoire": "ivory coast",
    "ivory coast": "ivory coast",
    "bosnia and herzegovina": "bosnia", "bosnia herzegovina": "bosnia",
    "bosnia-herzegovina": "bosnia",
    "cape verde": "cape verde", "cabo verde": "cape verde",
    "turkey": "turkiye", "türkiye": "turkiye",
    "iran": "iran", "ir iran": "iran",
    "curacao": "curacao", "curaçao": "curacao",
    "congo dr": "dr congo", "democratic republic of congo": "dr congo",
    "democratic republic congo": "dr congo",
}


def normalize_team(name: str) -> str:
    """Lowercase, strip accents/punctuation, collapse spaces, apply aliases."""
    if not name:
        return ""
    n = unicodedata.normalize("NFKD", name)
    n = "".join(c for c in n if not unicodedata.combining(c))
    n = "".join(c if c.isalnum() or c.isspace() else " " for c in n).lower()
    n = " ".join(n.split())
    return ALIASES.get(n, n)


def match_key(a: str, b: str):
    """Order-independent key for a fixture."""
    return frozenset({normalize_team(a), normalize_team(b)})


def _http_get(url: str, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "wc-pm/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode())


def _is_draw(label: str) -> bool:
    return normalize_team(label) in ("draw", "tie", "draw tie")


def _normalize_probs(probs: dict) -> dict:
    """
    Normalise a 3-way market's outcome probabilities to sum to 1.

    Raw prediction-market quotes (bid/ask midpoints, last prices) rarely sum to
    exactly 1 — typically 0.97-1.05 across the three outcomes. The bookmaker
    side of every comparison IS de-vigged (sums to 1), so without this step up
    to a couple of points of any reported "gap" is just the prediction market's
    own spread, not signal. Only rescales when the raw sum is in a sane band;
    a wildly off sum means bad data, which we pass through untouched so the
    upstream shape checks can reject it.
    """
    total = sum(probs.values())
    if 0.85 <= total <= 1.20 and total > 0:
        return {k: v / total for k, v in probs.items()}
    return probs


# ---- Polymarket -------------------------------------------------------------
def fetch_polymarket(max_pages: int = 4, page_size: int = 500) -> dict:
    """
    Pull active events from Polymarket's Gamma API and assemble any that look
    like a 3-way football match (two team outcomes + a draw).

    Gamma event shape (VERIFY): each event has .title and .markets[]; for a
    grouped 3-way, each market is one outcome with .groupItemTitle (e.g. "USA",
    "Draw", "Paraguay"), .outcomes == '["Yes","No"]' and
    .outcomePrices == '["0.48","0.52"]' where the first price is P(outcome).
    """
    out = {}
    for page in range(max_pages):
        params = {"active": "true", "closed": "false",
                  "limit": page_size, "offset": page * page_size}
        url = f"{POLYMARKET_GAMMA}/events?" + urllib.parse.urlencode(params)
        try:
            events = _http_get(url)
        except Exception as e:
            print(f"[polymarket] page {page} failed: {e}")
            break
        if not events:
            break

        for ev in events:
            markets = ev.get("markets") or []
            probs = {}
            for m in markets:
                label = m.get("groupItemTitle") or m.get("question") or ""
                try:
                    prices = json.loads(m.get("outcomePrices", "[]"))
                    p_yes = float(prices[0]) if prices else None
                except (json.JSONDecodeError, ValueError, IndexError):
                    p_yes = None
                if p_yes is None or not label:
                    continue
                key = "draw" if _is_draw(label) else normalize_team(label)
                probs[key] = p_yes

            teams = [k for k in probs if k != "draw"]
            if len(teams) == 2 and "draw" in probs:   # looks like a 3-way match
                mk = frozenset(teams)
                out[mk] = {"source": "polymarket",
                           "teams": tuple(teams), "probs": _normalize_probs(probs)}
    return out


# ---- Kalshi -----------------------------------------------------------------
def fetch_kalshi(max_pages: int = 6) -> dict:
    """
    Pull open Kalshi events with nested markets and assemble football 3-ways.

    Kalshi market prices are in CENTS (1-99) == probability. Use the midpoint
    of yes_bid/yes_ask, falling back to last_price. (VERIFY field names live.)

    To narrow results, set series_ticker once you discover the World Cup series
    in Claude Code:  GET /series  or  GET /events?status=open
    """
    out = {}
    cursor = None
    for _ in range(max_pages):
        params = {"status": "open", "with_nested_markets": "true", "limit": 200,
                  "series_ticker": KALSHI_WC_SERIES}
        if cursor:
            params["cursor"] = cursor
        url = f"{KALSHI_BASE}/events?" + urllib.parse.urlencode(params)
        try:
            data = _http_get(url)
        except Exception as e:
            print(f"[kalshi] request failed (check base URL / host): {e}")
            break

        events = data.get("events", [])
        cursor = data.get("cursor")
        for ev in events:
            title = ev.get("title", "")
            if "vs" not in title.lower() and " v " not in title.lower():
                continue
            probs = {}
            for m in ev.get("markets", []):
                label = m.get("yes_sub_title") or m.get("subtitle") or ""
                # Kalshi prices are in _dollars fields, 0-1 range (e.g. "0.08" = 8%)
                try:
                    yb = float(m["yes_bid_dollars"]) if m.get("yes_bid_dollars") is not None else None
                    ya = float(m["yes_ask_dollars"]) if m.get("yes_ask_dollars") is not None else None
                except (TypeError, ValueError):
                    yb = ya = None
                if yb is not None and ya is not None:
                    prob = (yb + ya) / 2
                elif m.get("last_price_dollars") is not None:
                    try:
                        prob = float(m["last_price_dollars"])
                    except (TypeError, ValueError):
                        continue
                else:
                    continue
                if not label:
                    continue
                key = "draw" if _is_draw(label) else normalize_team(label)
                probs[key] = prob

            teams = [k for k in probs if k != "draw"]
            if len(teams) == 2 and "draw" in probs:
                mk = frozenset(teams)
                out[mk] = {"source": "kalshi",
                           "teams": tuple(teams), "probs": _normalize_probs(probs)}
        if not cursor:
            break
    return out


if __name__ == "__main__":
    print("Fetching Polymarket...")
    pm = fetch_polymarket()
    print(f"  found {len(pm)} football 3-way markets")
    for mk, v in list(pm.items())[:5]:
        print("   ", " / ".join(f"{k} {p*100:.0f}%" for k, p in v["probs"].items()))

    print("\nFetching Kalshi...")
    kl = fetch_kalshi()
    print(f"  found {len(kl)} football 3-way markets")
    for mk, v in list(kl.items())[:5]:
        print("   ", " / ".join(f"{k} {p*100:.0f}%" for k, p in v["probs"].items()))
