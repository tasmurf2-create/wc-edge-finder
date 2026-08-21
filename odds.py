#!/usr/bin/env python3
"""
Club-football odds edge-finder (The Odds API).

Pulls every fixture across the covered leagues (see leagues.py) and, per match:
  - de-vigs each bookmaker's 1X2 prices individually, then averages to a
    consensus "fair" probability (the sharpest estimate the market gives you)
  - finds the BEST available decimal price per outcome across all books
  - flags outcomes where the fair probability beats the best price you can get
    (i.e. line-shopping / value)
  - reports each match's average bookmaker margin (overround)

Every event is tagged with the league it came from, so downstream code can
filter and label without a second lookup.

Zero dependencies (stdlib only). Get a free key (500 req/month) at the-odds-api.com

Usage:
    export ODDS_API_KEY="your_key_here"
    python odds.py
"""
import os
import sys
import json
import urllib.parse
import urllib.request
from collections import defaultdict

import leagues

API_KEY = (os.environ.get("ODDS_API_KEY") or "").strip()
BASE = "https://api.the-odds-api.com/v4"
ODDS_FORMAT = "decimal"

# QUOTA MATH — read before widening either of these.
# The Odds API bills [markets] x [regions] credits PER league request, so a full
# refresh costs  len(MARKETS) x len(REGIONS) x len(LEAGUES).
#   uk        x h2h,totals,spreads x 3 leagues =  9 credits/refresh
#   uk,eu     x h2h,totals,spreads x 3 leagues = 18 credits/refresh
# The free tier is 500 credits/MONTH — at 9 credits that is ~55 refreshes total,
# so the background cadence must stay slow (see ODDS_REFRESH_MINUTES) unless the
# key is on a paid plan. Widening to "uk,eu" doubles the burn for a handful of
# extra books; keep it off unless the quota allows it.
REGIONS = os.environ.get("ODDS_REGIONS", "uk").strip() or "uk"
MARKETS = os.environ.get("ODDS_MARKETS", "h2h,totals,spreads").strip()
VALUE_THRESHOLD = 0.015  # flag when fair prob beats best price by >1.5 pts

# Updated from every response's x-requests-remaining header so the app can show
# real quota state instead of guessing.
QUOTA = {"remaining": None, "used": None, "last_cost": None}


def get(path, **params):
    import urllib.error
    params["apiKey"] = API_KEY
    url = f"{BASE}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "soccer-edge/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            rem = resp.headers.get("x-requests-remaining")
            if rem is not None:
                QUOTA["remaining"] = int(float(rem))
                QUOTA["used"] = int(float(resp.headers.get("x-requests-used") or 0)) or None
                QUOTA["last_cost"] = int(float(resp.headers.get("x-requests-last") or 0)) or None
                print(f"[quota] remaining this month: {rem}"
                      f" (last call cost {QUOTA['last_cost']})", file=sys.stderr)
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {e.reason} — {body}") from e


def fetch_league(sport_key, regions=REGIONS, markets=MARKETS):
    """Odds for one league. Falls back to h2h-only if the plan lacks the
    extra markets, so a restricted key still returns 1X2 rather than nothing."""
    try:
        events = get(f"/sports/{sport_key}/odds", regions=regions,
                     markets=markets, oddsFormat=ODDS_FORMAT)
    except Exception as e:
        print(f"[odds] {sport_key}: {markets} failed ({e}); retrying h2h-only",
              file=sys.stderr)
        events = get(f"/sports/{sport_key}/odds", regions=regions,
                     markets="h2h", oddsFormat=ODDS_FORMAT)
    for ev in events:
        ev["league_key"] = sport_key           # tag so downstream can filter/label
        ev["league"] = leagues.league_name(sport_key)
    return events


def fetch_all(sport_keys=None, regions=REGIONS, markets=MARKETS):
    """Every fixture across the covered leagues, tagged with its league.

    One league failing (feed hiccup, out of season) must not take the others
    down — each is caught, reported, and skipped.
    """
    keys = sport_keys or leagues.KEYS
    out, errors = [], {}
    for sk in keys:
        try:
            evs = fetch_league(sk, regions=regions, markets=markets)
            out.extend(evs)
            print(f"[odds] {leagues.league_name(sk)}: {len(evs)} fixtures", file=sys.stderr)
        except Exception as e:
            errors[sk] = f"{type(e).__name__}: {e}"
            print(f"[odds] {sk} FAILED: {e}", file=sys.stderr)
    out.sort(key=lambda e: e.get("commence_time", ""))
    return out, errors


def devig(raw):
    """raw = {outcome: implied_prob}. Returns (fair_probs, margin)."""
    total = sum(raw.values())
    return {k: v / total for k, v in raw.items()}, total - 1.0


def analyse(event):
    home, away = event["home_team"], event["away_team"]
    best_price = {}                     # outcome -> (decimal_price, book)
    per_book_fair = defaultdict(list)   # outcome -> [fair prob from each book]
    margins = []

    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market["key"] != "h2h":
                continue
            raw = {o["name"]: 1.0 / o["price"] for o in market["outcomes"] if o.get("price")}
            if not raw:
                continue
            fair, margin = devig(raw)
            margins.append(margin)
            for o in market["outcomes"]:
                name, price = o["name"], o.get("price")
                if not price:
                    continue
                per_book_fair[name].append(fair[name])
                if name not in best_price or price > best_price[name][0]:
                    best_price[name] = (price, bm["title"])

    if not per_book_fair:
        return None
    return {
        "match": f"{home} vs {away}",
        "league_key": event.get("league_key"),
        "league": event.get("league"),
        "commence": event.get("commence_time", ""),
        "fair": {k: sum(v) / len(v) for k, v in per_book_fair.items()},
        "best_price": best_price,
        "margin": sum(margins) / len(margins) if margins else 0.0,
    }


def main():
    if not API_KEY:
        sys.exit("Set ODDS_API_KEY first. Free key: https://the-odds-api.com")

    events, errors = fetch_all()
    rows = [r for r in (analyse(e) for e in events) if r]

    if not rows:
        print("No fixtures with odds right now.")
        if errors:
            print("Errors:", errors)
        return

    current = None
    for r in rows:
        if r["league"] != current:
            current = r["league"]
            print(f"\n{'='*70}\n  {current}\n{'='*70}")
        print(f"\n--- {r['match']}  ({r['commence'][:16]})  |  "
              f"avg book margin {r['margin']*100:.1f}% ---")
        for outcome, p in sorted(r["fair"].items(), key=lambda x: -x[1]):
            price, book = r["best_price"][outcome]
            implied_best = 1.0 / price
            edge = (p - implied_best) * 100   # +ve = fair prob beats best price
            flag = "   <-- VALUE" if edge > VALUE_THRESHOLD * 100 else ""
            print(f"  {outcome:<26} fair {p*100:5.1f}%  |  "
                  f"best {price:6.2f} ({book}) = {implied_best*100:5.1f}%  |  "
                  f"edge {edge:+5.1f}%{flag}")
    print(f"\n{len(rows)} fixtures across {len(set(r['league'] for r in rows))} leagues.")


if __name__ == "__main__":
    main()
