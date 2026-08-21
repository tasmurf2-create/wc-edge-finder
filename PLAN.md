# Rebrand: WC Edge Finder → Soccer Edge Finder

A club-football edge finder across **Premier League (England)**, **La Liga (Spain)** and
**Scottish Premiership**. Same edge principles as the World Cup app — de-vig bookmaker prices
to a consensus fair probability, line-shop the best price, and confirm with a grounded AI
analyst — but the "team" is now a **club**, not a national team.

## Locked decisions

| Decision | Choice |
|---|---|
| World Cup national-team model | **Replaced** by a club model (not kept as a fallback) |
| Prediction markets (Kalshi/Polymarket) | **Dropped** — thin coverage of club league games. Edge = de-vig value gate **+** analyst agreement |
| GAA vertical | **Deleted** entirely |
| Weather / venue conditions | **Dropped for now** (depends on the WC stadium table). Re-addable later with a club-ground CSV |
| Leagues | Premier League, La Liga, Scottish Premiership |

## What stays (reused as-is)

The edge maths is already sport-agnostic: de-vig (`devig`), consensus fair prob, best-price
line-shopping, EV, accumulator pricing (single-book), and the **My Bets** journal. None of this
changes — only what feeds the analyst and which odds feed we pull.

## Build order

1. **Delete GAA** — remove `gaa_intel.py`, `sportbex.py`, `paddypower.py`, `pp_push.py`,
   `static/js/views-gaa.js`, all `/api/gaa*` routes, the GAA nav tab, GAA env vars in
   `render.yaml`. Verify the app still boots.
2. **Remove prediction markets** — remove `prediction_markets.py`, the Markets "Divergence"
   sub-tab and PM columns/signals in `views-markets.js` and `server.py`. Edge collapses to
   value-gate + analyst.
3. **Swap the team model** (`static_data.py`) — FIFA codes / rankings / FIFA-PDF squads →
   **club lookup** (club name, league, table position, recent form). Retire the WC `data/*.csv`.
4. **Multi-league odds** (`wc_odds.py` → `odds.py`, `server.py` `_fetch_events`) — pull the
   three league sport keys (`soccer_epl`, `soccer_spain_la_liga`, Scottish Premiership), tag each
   event with its league, add a **league filter** in the UI.
5. **Rework the analyst** (`football_intel.py`) — new system prompt for club football (league
   form, table position, injuries, home/away — no tournament framing), grounding via **one web
   search per match**, same JSON `recommended_bets[]` output. Football-news source domains.
6. **Rebrand + reset** — title/brand → `Soccer Edge Finder`, favicon, README / ARCHITECTURE /
   methodology copy, `render.yaml` service name; wipe WC caches and rebuild `intel_seed.json`.

## Sequencing rationale

Phases 1–2 are pure deletions (self-contained, low risk) — do and verify first. Phase 3–4 get
three leagues' **odds** flowing end-to-end. Phase 5 (analyst rework) is the hardest and most
judgment-heavy. Phases 6 is polish. Work is committed per phase on a dedicated branch so every
step is reversible.
