# WC 2026 Edge Finder

A betting edge finder for the 2026 FIFA World Cup. It combines bookmaker odds, prediction markets (Kalshi/Polymarket), and a **fact-grounded** AI football analyst to surface genuine value across match markets.

## What it does

- **De-vigs** bookmaker prices to expose the true consensus fair probability
- **Compares** that fair prob against Kalshi and Polymarket implied prices — divergence is the edge signal
- **AI analyst** (Claude Sonnet) gives a football read grounded **only in sourced data** — squad, FIFA ranking, recent form, injuries, venue/conditions, prices — and is explicitly forbidden from inventing stats, records, managers or formations
- **Confirms or contradicts** each price-edge bet with the analyst — agreement between the maths and the football view (★ Both agree) is the strongest signal

## Tabs

| Tab | What it shows |
|---|---|
| **Market Divergence** | Every match ranked by bookmaker vs prediction-market gap. Green = PM rates it higher than books (possible value); Red = books shorter (possible trap). |
| **★ Sensible Bets** | One shortlist scoring each bet on edge + PM agreement + conditions + analyst, graded **Strong / Solid / Speculative**. |
| **The Maths** | Value singles (1X2, Over/Under, Asian Handicap) + accumulators, with the analyst-confirmation badge on each card. |
| **Bettor's Analysis** | The analyst's football read + recommended bets (with live odds) per match. A second opinion, not fact. |
| **🩹 Injuries** | Tournament-wide injury/suspension digest in one place. Manual refresh only (no auto-poll). |

## Bet types covered

- **1X2** — Home win / Draw / Away win
- **Over/Under** — Goals totals (1.5, 2.5)
- **Asian Handicap** — symmetric (either team, either line)
- **Accumulators** — priced at a **single bookmaker** (you can't split legs across books); each slip names the book to place it at

## Bookmakers covered

Irish-accessible books only: **Paddy Power · Betfair · Bet365 · BoyleSports · Ladbrokes · William Hill**. Exchanges are used for singles but excluded from accumulator pricing.

## The AI analyst — grounded, not guessing

The analyst is given **only sourced inputs** and is instructed not to invent anything beyond them (no fabricated stats, scorelines, records, managers or formations):

| Input | Source |
|---|---|
| Squad — players, clubs, ages | official FIFA 2026 squad PDF → `data/players.csv` |
| FIFA world ranking | `data/team_facts.csv` |
| Recent form — last 8, W/D/L, GF/GA, with competition labels | `data/team_form.csv` (built by `build_form.py`) |
| Injuries / suspensions | one tournament-wide web digest → `injury_digest.json` (12 h) |
| Venue, altitude, weather | `data/venues.csv` + Open-Meteo (live forecast inside 16 days, else climate normal — labelled which) |
| Bookmaker prices | live odds, de-vigged |

It outputs up to 3 `recommended_bets[]` with football reasoning. Cards show **✓ Analyst backed** / **⚠ Analyst prefers other outcome** / **★ Both agree**.

## Architecture

```
wc_odds.py            — Odds API fetch + de-vig + line-shopping
prediction_markets.py — Kalshi + Polymarket implied probs
static_data.py        — sourced reference data (squads, venues, FIFA ranking, recent form)
football_intel.py     — Claude analyst (grounded) + injury digest + weather
build_form.py         — (manual) rebuild data/team_form.csv from the open results dataset
server.py             — FastAPI backend, caching, background intel, visitor stats
static/index.html     — single-page dashboard (5 tabs)
data/                 — players.csv, teams.csv, venues.csv, matches.csv, team_facts.csv, team_form.csv
```

## Setup

```bash
cp .env.example .env
# Add your keys:
#   ODDS_API_KEY      — free tier at https://the-odds-api.com (500 req/month)
#   ANTHROPIC_API_KEY — at https://console.anthropic.com

pip install -r requirements.txt
python server.py
# Open http://localhost:8000
```

Refresh the recent-form data whenever you like (one download, no per-analysis web calls):

```bash
python build_form.py    # rebuilds data/team_form.csv from the public results dataset
```

## Deploy (Render)

`render.yaml` defines a free web service. Deploy via **New → Blueprint**, then set `ODDS_API_KEY` and `ANTHROPIC_API_KEY` (and optionally `ADMIN_KEY` for `/admin/stats`) as dashboard secrets. `intel_seed.json` ships pre-built analyst cards so the deployed app isn't empty on a cold start. Visitor stats: `/admin/stats?key=<ADMIN_KEY>`.

## Caching

| Cache | TTL | File |
|---|---|---|
| Match odds | 5 min | in-memory |
| Match intel (analyst) | 12 hours | `intel_cache.json` (falls back to committed `intel_seed.json`) |
| Injury/suspension digest (tournament-wide) | 12 hours | `injury_digest.json` |
| Weather forecasts | 6 hours | `weather_cache.json` |
| Squad / FIFA ranking / recent form | static (manual refresh) | `data/*.csv` |

## Edge logic

```
fair_prob   = de-vigged consensus across all books
best_price  = best available decimal price from whitelisted books
edge %      = (fair_prob − 1/best_price) × 100

pm_gap      = (kalshi/polymarket implied − fair_prob) × 100
              positive = PM thinks this outcome is MORE likely than books
              negative = PM thinks it's LESS likely

confidence:
  high   = edge > 1.5% AND pm_gap confirms (PM > books)
  medium = edge > 0.5% OR strong PM signal
  low    = small edge, no PM confirmation
```

Accumulators are priced at the **single best book that covers all legs** (never line-shopped across books), and EV is computed off that realistic price — so favourite-heavy slips correctly show negative EV.

## Reality check

These are +EV leans and pricing soft-spots — not predictions. World Cup match markets are efficient; variance dominates over a small sample. The analyst confirmation layer filters out mathematically-edged bets that have no football logic behind them. Stake in flat units, treat the analyst as a second opinion, and always line-shop.
