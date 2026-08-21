#!/usr/bin/env python3
"""
League registry — the single source of truth for which competitions the app
covers.

Everything downstream (odds fetching, UI filters, the analyst's league context)
reads from LEAGUES. Adding a competition is a one-entry change here; the sport
keys are The Odds API's, verified live against GET /v4/sports.

    soccer_epl             EPL                        English Premier League
    soccer_spain_la_liga   La Liga - Spain            Spanish Soccer
    soccer_spl             Premiership - Scotland     Scottish Soccer
"""

LEAGUES = [
    {
        "key":      "soccer_epl",
        "name":     "Premier League",
        "short":    "EPL",
        "country":  "England",
        "flag":     "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "tier":     1,
        # Sources the analyst is allowed to ground league context in.
        "domains":  ["bbc.com", "skysports.com", "premierleague.com",
                     "theguardian.com", "espn.com"],
    },
    {
        "key":      "soccer_spain_la_liga",
        "name":     "La Liga",
        "short":    "LaLiga",
        "country":  "Spain",
        "flag":     "🇪🇸",
        "tier":     1,
        "domains":  ["bbc.com", "skysports.com", "marca.com", "as.com",
                     "espn.com", "theguardian.com"],
    },
    {
        "key":      "soccer_spl",
        "name":     "Scottish Premiership",
        "short":    "SPFL",
        "country":  "Scotland",
        "flag":     "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
        "tier":     1,
        "domains":  ["bbc.com", "skysports.com", "spfl.co.uk",
                     "theguardian.com", "heraldscotland.com"],
    },
]

BY_KEY = {l["key"]: l for l in LEAGUES}
KEYS = [l["key"] for l in LEAGUES]


def league(key):
    """League record for an Odds API sport key, or None."""
    return BY_KEY.get(key)


def league_name(key):
    l = BY_KEY.get(key)
    return l["name"] if l else (key or "")


def league_short(key):
    l = BY_KEY.get(key)
    return l["short"] if l else (key or "")


def domains_for(key):
    """Trusted grounding domains for a league (falls back to the general set)."""
    l = BY_KEY.get(key)
    return list(l["domains"]) if l else ["bbc.com", "skysports.com", "espn.com"]


def public_list():
    """League metadata for the UI filter (no domain lists)."""
    return [{k: l[k] for k in ("key", "name", "short", "country", "flag")}
            for l in LEAGUES]


if __name__ == "__main__":
    for l in LEAGUES:
        print(f"{l['key']:<24} {l['flag']} {l['name']:<24} ({l['country']})")
