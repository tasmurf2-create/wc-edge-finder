# World Cup 2026 — Betting Edge Finder

A research toolkit that finds value across the 2026 World Cup betting markets by
combining three probability sources and flagging where they disagree.

## What each file does

| File | Role |
|---|---|
| `wc_odds.py` | Pulls 1X2 odds from **The Odds API**, de-vigs each book, builds a consensus "fair" probability, and flags line-shopping value (best price vs fair). |
| `prediction_markets.py` | Fetches implied probabilities from **Polymarket** (Gamma API) and **Kalshi**. Includes the team-name normalization layer so the same fixture lines up across sources. |
| `compare.py` | Joins bookmaker consensus + Polymarket + Kalshi into one report and flags **divergence** — the strongest signal. |
| `.env.example` | Template for your API key. |

## The core idea

1. **De-vig** removes the bookmaker margin to expose the true probability a price implies.
2. **Prediction markets** (Polymarket/Kalshi) run far lower margins and are often sharper.
3. **Divergence** = where the de-vigged bookmaker probability disagrees with the prediction-market probability. That gap is where mispricing — and value — lives.

Two structural edges to layer on top (build these next):
- **Line-shopping**: always take the best available price across books. Already in `wc_odds.py`.
- **Format edge**: 32 of 48 teams advance (top 2 per group **+** 8 best third-place teams = two-thirds of the field). "To qualify" markets on solid-but-unspectacular sides are systematically generous. Build a qualification module.

## Quick start (local or in Claude Code)

```bash
# 1. put the files in one folder, then:
cp .env.example .env
# 2. edit .env and paste your free Odds API key
# 3. run the pieces individually first:
python wc_odds.py              # bookmaker odds + line-shopping value
python prediction_markets.py   # confirms Polymarket/Kalshi parsing works
python compare.py              # the three-way divergence report
```

No pip installs needed — everything is Python standard library.

## IMPORTANT: verify the prediction-market endpoints live

The Polymarket and Kalshi endpoint URLs and JSON field names in
`prediction_markets.py` are best-known shapes and **change over time**. Before
trusting the output, have Claude Code confirm them live. Search the file for
`VERIFY`. Quick checks:

```bash
# Polymarket — should return a JSON array of events:
curl "https://gamma-api.polymarket.com/events?active=true&closed=false&limit=5"

# Kalshi — if this host errors, try the trading-api.kalshi.com host instead:
curl "https://api.elections.kalshi.com/trade-api/v2/events?status=open&limit=5"
```

Adjust the parsing (`groupItemTitle`, `outcomePrices`, `yes_bid/yes_ask`,
`yes_sub_title`) to match what the live responses actually contain.

## Hand this to Claude Code to build the full app

> Build a World Cup 2026 betting-edge app around the four attached files.
> - **Data layer:** keep The Odds API (UK/EU + US books), Polymarket, and Kalshi as sources. First, curl each prediction-market endpoint and fix any URL/field mismatches in `prediction_markets.py` (see the VERIFY notes).
> - **Engine:** reuse the de-vig + consensus logic; surface (a) line-shopping value and (b) book-vs-prediction-market divergence, sorted by gap size.
> - **Format module:** add a "to qualify" model — each team's chance of finishing top-2 OR top-8 third place — and compare to bookmaker qualification prices.
> - **Persistence:** snapshot every poll into SQLite (timestamp, match, source, outcome, price) so line movement is tracked, not just one frame. Schedule with APScheduler or cron.
> - **Interface:** FastAPI backend + a small dashboard (React or plain HTML) listing matches ranked by edge, with a line-movement chart per match.
> - **Hygiene:** key stays in `.env`; cache responses to respect the 500-req/month free quota; make all network calls fail soft.
> Start by getting `compare.py` returning real divergence numbers, then build outward.

## Reality check

These are small +EV leans and pricing soft-spots, not predictions. World Cup
match markets are highly efficient; variance dominates over a handful of games.
Line-shop everything, stake in flat units (1–2% of bankroll), and treat the
qualification markets as where the steadiest value sits.
