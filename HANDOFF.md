# Overnight handoff — 21 Aug 2026

**WC Edge Finder is now Soccer Edge Finder.** It runs on club football across the Premier League,
La Liga and the Scottish Premiership, verified working end-to-end against the live feed.

- **Repo:** https://github.com/tasmurf2-create/soccer-edge-finder — **private**, flip it public when
  you want. All work is on `main`.
- **Branch here:** `soccer-rebrand` (the old `origin/wc-edge-finder` remote is untouched, so the
  World Cup version is still intact if you ever want it).
- **Run it:** `python server.py` → http://localhost:8000

---

## What it does now

Same principles as before — de-vig, line-shop, confirm with an analyst — but the "team" is a club.

| Layer | World Cup version | Now |
|---|---|---|
| Fixtures | 1 tournament sport key | 3 league keys, each fixture tagged with its league |
| Team model | FIFA codes, rankings, FIFA-PDF squads, bracket, WC stadiums | Club names; form/table/team-news from web research |
| Cross-check | Kalshi / Polymarket | **Sharp line** — Pinnacle & exchanges |
| Analyst grounding | Static CSVs + one tournament injury digest | One web search per fixture, per-league sources |
| Grouping/filter | Tournament round | **League** |
| GAA vertical | present | removed entirely |

**Verified live:** 28 fixtures · 8 value singles · 25 accumulators · analyst cards across all three
leagues, every one research-grounded · zero JS errors across every view · mobile clean.

---

## Three things I found and fixed that you should know about

**1. Every reported edge was overstated.** Exchanges post the best raw price on nearly every
outcome, so Betfair won the best-price comparison on **10 out of 10** value singles. But exchange
prices are *pre-commission*, and on markets where real edges are ~1%, a 2–5% commission **is** the
edge. The app was advertising value that doesn't survive a betslip.

Prices are now converted to what you actually keep before any edge is computed or any book is called
best. Value singles went 10 → 8 (two were pure commission illusions) and a sportsbook now correctly
beats Betfair on one outcome. Configurable via `EXCHANGE_COMMISSION` (default 2%) — **set this to
your real rate.**

**2. Two leagues were never analysed.** The analyst picked "the lowest round still to be played" —
correct for a tournament, but round-order now carries the league index, so it resolved to Premier
League and La Liga and Scotland got nothing. Now filtered by *time* (next 8 days), all leagues.

**3. The analyst hallucinated under pressure.** Testing against live fixtures caught it (a) naming
Bournemouth's manager as Liverpool's, because the research mixed clubs up, and (b) reading "no
injuries found" as "squad fully fit" and building an edge on it. Both now have explicit prompt rules.
Please don't remove them without re-testing.

---

## What needs your decision

**The Odds API quota is the real constraint.** Billing is `markets × regions` **per league**, so one
full refresh = **9 credits**. The free tier is 500/month ≈ **55 refreshes total**, under two a day.

I set the app to demand-driven (no background timer, 6h cache) so it can't drain the key. **For
something you market to other people, you want a paid plan** — then set `ODDS_REFRESH_MINUTES=15`.
Current quota is visible at `/api/status`. About 90 credits went on tonight's testing.

**Anthropic spend** scales with fixtures: ~28 per 12h cycle × (1 Haiku search + 1 Sonnet call).

---

## Deploying to Render

`render.yaml` is updated (service renamed, GAA vars removed). Point a new Blueprint at the new repo
and set `ODDS_API_KEY`, `ANTHROPIC_API_KEY`, `ADMIN_KEY`. Consider also setting
`EXCHANGE_COMMISSION`.

I did **not** touch your existing Render service — deploying is your call.

---

## Known gaps (deliberate, not bugs)

- **No weather/venue layer.** It depended on the WC stadium table. Re-addable with a club-ground CSV.
- **Research varies by league.** EPL and La Liga are well covered; Scottish sources are thinner, so
  those cards lean more on the model's own knowledge.
- **No league-table API.** Position and form come from web search, so completeness varies run to run.
  A standings API would make this deterministic — the biggest available quality win.
- **`wc26_*` localStorage keys kept.** Renaming them would have wiped any bets you'd already logged.

Full technical detail in [ARCHITECTURE.md](ARCHITECTURE.md); product explanation in
[README.md](README.md).

---

## Suggested first moves when you wake up

1. Open http://localhost:8000 and click through Today → Best Bets → Markets → Sharp Line.
2. Read the **Methodology** tab — it's the trust surface if you're showing this to other people.
3. Decide on the Odds API plan; set `EXCHANGE_COMMISSION` to your actual rate.
4. Tell me if the analyst's voice is right — that's the most subjective part and the easiest to tune.
