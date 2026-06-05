#!/usr/bin/env python3
"""
Three-way divergence report:  bookmaker consensus  vs  Polymarket  vs  Kalshi.

The actionable signal: when the de-vigged bookmaker probability for an outcome
sits well ABOVE the prediction-market probability, the bookmakers are likely
too short on that side (overpriced) -> the OTHER outcomes are where value sits,
and vice-versa. This is the engine behind the USA/Paraguay read.

Run order:
    1. populate .env  (see .env.example)
    2. python compare.py
"""
import os

# --- load .env BEFORE importing modules that read env at import time ---------
def _load_env(path=".env"):
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
_load_env()

import wc_odds                       # noqa: E402  (must follow _load_env)
import prediction_markets as pmkt    # noqa: E402

DIVERGENCE_FLAG = 0.04   # flag when book vs prediction-market prob differ by >4 pts


def bookmaker_matches():
    """Return {match_key: {canonical_outcome: fair_prob}} from The Odds API."""
    key = wc_odds.find_world_cup_key()
    events = wc_odds.get(f"/sports/{key}/odds",
                         regions=wc_odds.REGIONS, markets="h2h",
                         oddsFormat=wc_odds.ODDS_FORMAT)
    out = {}
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
        out[mk] = {"label": f"{home} vs {away}", "probs": probs}
    return out


def main():
    print("Pulling bookmaker odds...")
    books = bookmaker_matches()
    print(f"  {len(books)} matches with bookmaker odds\n")

    print("Pulling prediction markets...")
    poly = pmkt.fetch_polymarket()
    kal = pmkt.fetch_kalshi()
    print(f"  Polymarket: {len(poly)}   Kalshi: {len(kal)}\n")

    matched = 0
    for mk, b in sorted(books.items(), key=lambda x: x[1]["label"]):
        pm = poly.get(mk, {}).get("probs", {})
        kl = kal.get(mk, {}).get("probs", {})
        if not pm and not kl:
            continue
        matched += 1
        print(f"=== {b['label']} ===")
        outcomes = sorted(b["probs"], key=lambda o: -b["probs"][o])
        for o in outcomes:
            bp = b["probs"].get(o)
            pp = pm.get(o)
            kp = kl.get(o)
            # consensus prediction-market prob (avg of whatever we have)
            pmvals = [x for x in (pp, kp) if x is not None]
            cons = sum(pmvals) / len(pmvals) if pmvals else None
            line = f"  {o:<18} book {bp*100:5.1f}%"
            line += f" | poly {pp*100:5.1f}%" if pp is not None else " | poly   -- "
            line += f" | kalshi {kp*100:5.1f}%" if kp is not None else " | kalshi   -- "
            if cons is not None:
                diff = (bp - cons) * 100
                tag = ""
                if diff > DIVERGENCE_FLAG * 100:
                    tag = "  <-- books LONG (this side likely overpriced)"
                elif diff < -DIVERGENCE_FLAG * 100:
                    tag = "  <-- books SHORT (possible VALUE here)"
                line += f" | diff {diff:+5.1f}%{tag}"
            print(line)
        print()

    if matched == 0:
        print("No overlap yet. Either books haven't opened these markets, or the "
              "prediction-market parsing needs the live-shape fixes (see VERIFY "
              "notes in prediction_markets.py).")


if __name__ == "__main__":
    main()
