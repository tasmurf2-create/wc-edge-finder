# WC 2026 Edge Finder

A betting edge finder for the 2026 FIFA World Cup. Combines bookmaker odds, prediction markets (Kalshi/Polymarket), and AI-powered football analysis to surface genuine value bets across match and tournament markets.

## What it does

- **De-vigs** bookmaker prices to expose the true consensus fair probability
- **Compares** that fair prob against Kalshi and Polymarket implied prices — divergence is the edge signal
- **AI analyst** (Claude Sonnet) analyses form, injuries, altitude, heat and tactics for each match, then recommends specific bets across all markets
- **Confirms or contradicts** each price-edge bet with analyst logic — so a +1.5% edge on a 10/1 shot the analyst disagrees with is flagged, not promoted
- **Outright/futures markets** — Tournament Winner, To Reach Semi-finals, Group Winner, Golden Boot — with the same PM divergence logic

## Tabs

| Tab | What it shows |
|---|---|
| **Market Divergence** | Every match ranked by bookmaker vs prediction-market gap. Red = books overpricing that side. Green = potential value. |
| **Recommended Bets** | Value singles (1X2, Over/Under, Asian Handicap) + Multi-Bets, with analyst confirmation badge on each card. |
| **Top Picks** | Top 5 analyst-confirmed bets, grouped by tournament round (Group Stage R1/R2/R3, then knockouts). |
| **Futures & Outrights** | Tournament Winner, Semi-final progression, Group Winner, Golden Boot — book vs PM divergence. |

## Bet types covered

- **1X2** — Home win / Draw / Away win
- **Over/Under** — Goals totals (1.5, 2.5, 3.5)
- **Asian Handicap** — Win by 2+, cover a handicap, etc.
- **Tournament Winner** — Full outright
- **Stage progression** — To Reach Final / Semi-finals / Quarter-finals
- **Group Winner / To Qualify**
- **Golden Boot** — Top goalscorer

## Bookmakers covered

Irish-accessible books only: **Paddy Power · Betfair · Bet365 · BoyleSports · Ladbrokes · William Hill**

## AI Analyst

Each match gets a Claude analysis covering:
- Squad profile (from official WC 2026 announcements — cached permanently)
- Injury & suspension news (refreshed every 12 hours)
- Venue conditions: altitude (Mexico City 2240m, Guadalajara 1560m), heat (Monterrey 37°C+, Houston, Dallas), humidity
- Tactical matchup and form
- Specific `recommended_bets[]` — up to 3 bets with clear football reasoning, not just price signal

Analyst cards show **✓ Analyst backed** (green) or **⚠ Analyst prefers other outcome** (amber) on every bet card.

## Architecture

```
wc_odds.py          — Odds API fetch + de-vig + line-shopping
prediction_markets.py — Kalshi + Polymarket implied probs
football_intel.py   — Claude analyst: team profiles, injuries, conditions, recommended bets
outrights.py        — Outright/futures: Tournament Winner, Semis, Groups, Golden Boot
server.py           — FastAPI backend, caching, background intel fetch
static/index.html   — Single-page dashboard (4 tabs)
```

## Setup

```bash
cp .env.example .env
# Add your keys:
#   ODDS_API_KEY    — free tier at https://the-odds-api.com (500 req/month)
#   ANTHROPIC_API_KEY — at https://console.anthropic.com

pip install fastapi uvicorn python-dotenv
python server.py
# Open http://localhost:8000
```

## Caching

| Cache | TTL | File |
|---|---|---|
| Match odds | 5 min | in-memory |
| Match intel (analyst) | 12 hours | `intel_cache.json` |
| Team squad profiles | Permanent | `team_profiles.json` |
| Injury/suspension news | 12 hours | `team_injuries.json` |
| Outright/futures | 1 hour | `outrights_cache.json` |

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

## Reality check

These are +EV leans and pricing soft-spots — not predictions. World Cup match markets are efficient; variance dominates over a small sample. The analyst confirmation layer filters out mathematically-edged bets that have no football logic behind them. Stake in flat units, treat the analyst as a second opinion, and always line-shop.
