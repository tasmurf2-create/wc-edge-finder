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

# CRAWLER ACCESS — the `domains` lists below are NOT a wishlist.
# Anthropic's web-search tool rejects the WHOLE request (HTTP 400) if any listed
# domain blocks its crawler, so one bad entry kills the search for that league.
# Verified accessible (probed 2026-08-21):
#   skysports.com, espn.com, espn.co.uk, goal.com, premierleague.com, spfl.co.uk,
#   football365.com, whoscored.com, fotmob.com, sofascore.com, flashscore.com,
#   90min.com, givemesport.com, scotsman.com, laliga.com, besoccer.com,
#   football-espana.net, football-lineups.com
# Verified BLOCKED — do not re-add without re-probing:
#   bbc.com, bbc.co.uk, theguardian.com, marca.com, as.com, transfermarkt.com,
#   heraldscotland.com, dailyrecord.co.uk, talksport.com, reuters.com
LEAGUES = [
    {
        "key":      "soccer_epl",
        "name":     "Premier League",
        "short":    "EPL",
        "country":  "England",
        "flag":     "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
        "tier":     1,
        # Sources the analyst is allowed to ground league context in.
        "domains":  ["skysports.com", "espn.com", "premierleague.com",
                     "football365.com", "whoscored.com", "fotmob.com", "90min.com"],
    },
    {
        "key":      "soccer_spain_la_liga",
        "name":     "La Liga",
        "short":    "LaLiga",
        "country":  "Spain",
        "flag":     "🇪🇸",
        "tier":     1,
        "domains":  ["skysports.com", "espn.com", "laliga.com",
                     "football-espana.net", "besoccer.com", "whoscored.com",
                     "fotmob.com"],
    },
    {
        "key":      "soccer_spl",
        "name":     "Scottish Premiership",
        "short":    "SPFL",
        "country":  "Scotland",
        "flag":     "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
        "tier":     1,
        "domains":  ["skysports.com", "espn.com", "spfl.co.uk", "scotsman.com",
                     "fotmob.com", "sofascore.com", "goal.com"],
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
    """Trusted grounding domains for a league (falls back to the general set).
    All entries must be crawler-accessible — see the note above LEAGUES."""
    l = BY_KEY.get(key)
    return list(l["domains"]) if l else ["skysports.com", "espn.com", "fotmob.com"]


def public_list():
    """League metadata for the UI filter (no domain lists)."""
    return [{k: l[k] for k in ("key", "name", "short", "country", "flag")}
            for l in LEAGUES]


if __name__ == "__main__":
    for l in LEAGUES:
        print(f"{l['key']:<24} {l['flag']} {l['name']:<24} ({l['country']})")
