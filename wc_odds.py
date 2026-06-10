#!/usr/bin/env python3
"""
World Cup 2026 odds edge-finder  (The Odds API)

For every match it:
  - de-vigs each bookmaker's 1X2 prices individually, then averages to a
    consensus "fair" probability (the sharpest estimate the market gives you)
  - finds the BEST available decimal price per outcome across all books
  - flags outcomes where the fair probability beats the best price you can get
    (i.e. line-shopping / value)
  - reports each match's average bookmaker margin (overround)

Zero dependencies (stdlib only). Get a free key (500 req/month) at the-odds-api.com

Usage:
    export ODDS_API_KEY="your_key_here"
    python wc_odds.py
"""
import os
import sys
import json
import urllib.parse
import urllib.request
from collections import defaultdict

API_KEY = (os.environ.get("ODDS_API_KEY") or "").strip()
BASE = "https://api.the-odds-api.com/v4"
REGIONS = "uk,eu"        # decimal-friendly books for IE/UK; add ",us" for US books
ODDS_FORMAT = "decimal"
VALUE_THRESHOLD = 0.015  # flag when fair prob beats best price by >1.5 pts


def get(path, **params):
    import urllib.error
    params["apiKey"] = API_KEY
    url = f"{BASE}{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "wc-odds/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            rem = resp.headers.get("x-requests-remaining")
            if rem is not None:
                print(f"[quota] requests remaining this month: {rem}", file=sys.stderr)
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except Exception:
            pass
        raise RuntimeError(f"HTTP {e.code} {e.reason} — {body}") from e


def find_world_cup_key():
    """Auto-discover the current sport key so it survives any renaming."""
    for s in get("/sports"):
        blob = (s.get("title", "") + " " + s.get("description", "")).lower()
        if "world cup" in blob and "soccer" in s.get("group", "").lower():
            return s["key"]
    return "soccer_fifa_world_cup"  # known fallback


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
            raw = {o["name"]: 1.0 / o["price"] for o in market["outcomes"]}
            fair, margin = devig(raw)
            margins.append(margin)
            for o in market["outcomes"]:
                name, price = o["name"], o["price"]
                per_book_fair[name].append(fair[name])
                if name not in best_price or price > best_price[name][0]:
                    best_price[name] = (price, bm["title"])

    if not per_book_fair:
        return None
    return {
        "match": f"{home} vs {away}",
        "commence": event.get("commence_time", ""),
        "fair": {k: sum(v) / len(v) for k, v in per_book_fair.items()},
        "best_price": best_price,
        "margin": sum(margins) / len(margins) if margins else 0.0,
    }


def main():
    if not API_KEY:
        sys.exit("Set ODDS_API_KEY first. Free key: https://the-odds-api.com")

    key = find_world_cup_key()
    print(f"Sport key: {key}\n")
    events = get(f"/sports/{key}/odds", regions=REGIONS,
                 markets="h2h", oddsFormat=ODDS_FORMAT)

    rows = [r for r in (analyse(e) for e in events) if r]
    rows.sort(key=lambda r: r["commence"])

    if not rows:
        print("No matches with odds yet — books open closer to kickoff.")
        return

    for r in rows:
        print(f"=== {r['match']}  ({r['commence']})  |  "
              f"avg book margin {r['margin']*100:.1f}% ===")
        for outcome, p in sorted(r["fair"].items(), key=lambda x: -x[1]):
            price, book = r["best_price"][outcome]
            implied_best = 1.0 / price
            edge = (p - implied_best) * 100   # +ve = fair prob beats best price
            flag = "   <-- VALUE" if edge > VALUE_THRESHOLD * 100 else ""
            print(f"  {outcome:<24} fair {p*100:5.1f}%  |  "
                  f"best {price:5.2f} ({book}) = {implied_best*100:5.1f}%  |  "
                  f"edge {edge:+5.1f}%{flag}")
        print()


if __name__ == "__main__":
    main()
