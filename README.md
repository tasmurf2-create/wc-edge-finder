# ⚽ Soccer Edge Finder

A betting edge finder for **club football** across the **Premier League**, **La Liga** and the
**Scottish Premiership**.

It does two independent things and only combines them at the end:

1. **The maths.** De-vigs every bookmaker's prices to a consensus fair probability, finds the best
   available price across the books you can actually bet at, and reports the gap (the *edge*) — then
   cross-checks that against the **sharpest line in the market**.
2. **The football.** Researches each fixture (recent form, league position, team news, head-to-head)
   and has an AI analyst write a grounded read, with up to three recommended bets.

Where the maths and the football agree, that's the strongest signal the app produces. Where they
disagree, it says so rather than hiding it.

> **This is not a tipping service and it does not predict results.** It surfaces pricing soft-spots
> and football reasoning. Club league markets are highly efficient; edges are small and variance
> dominates. Read the Methodology tab before staking anything.

---

## What it actually does

### De-vigging → "fair" probability

Bookmaker odds include a margin — the implied probabilities of Home/Draw/Away sum to more than 100%.
Each book is de-vigged proportionally, then averaged across books into a consensus **fair
probability**.

"Fair" means *the market average*, not the truth. Beating it means you got a better-than-consensus
price — it does not prove the consensus is wrong.

### The sharp-line cross-check

Not all books are equally informed. **Pinnacle** and the betting exchanges run ~2% margins (against
5–8% at a high-street book), accept large stakes, and move first on real money. Their de-vigged line
is the closest available proxy for a true probability.

Every outcome is compared against it:

| Sharp vs consensus | Meaning |
|---|---|
| Sharp rates it **higher** | Sharp money agrees it's underpriced — supportive |
| Sharp rates it **lower** | The apparent edge is more likely model error — treat with caution |

*(The World Cup version of this app used Kalshi/Polymarket here. Those venues price big tournaments
but barely cover a midweek league fixture, so for club football they were empty far more often than
not.)*

### The AI analyst — grounded, not guessing

For each fixture the app runs **one web search** over sources trusted for that league, then has
Claude write the football read from that material **and nothing else**.

It is explicitly constrained. It may not:

- invent a scoreline, table position, or statistic;
- name a manager or signing it isn't confident about;
- read *"no injuries found"* as *"the squad is fit"* — missing information is reported as missing.

Those last two are not hypothetical: both were real failure modes caught while testing this against
live fixtures, and each has a rule in the prompt because of it.

The analyst never sees enough to judge value. It supplies football reasons; the price layer judges
the odds.

---

## Navigation

| Tab | What it shows |
|---|---|
| 📅 **Today** | The next matchday — each fixture with the analyst's read and recommended bets |
| ★ **Best Bets** | Picks that passed **two gates**: the analyst recommended the outcome, *and* the price is fair or better |
| 📊 **Markets** | Value Singles · Accumulators · Acca Builder · **Sharp Line** (consensus vs sharpest book) |
| 📒 **My Bets** | A private journal in your browser. Records the model's fair prob + EV **at the moment you bet** — the groundwork for closing-line-value review |
| 🩹 **Injuries** | Team news across the covered leagues, gathered per match |
| 📖 **Methodology** | An interactive map of the whole pipeline, plus the honest limits |

## Markets covered

**1X2** · **Over/Under** (1.5, 2.5) · **Asian Handicap** · **Accumulators** (priced at a single book —
you can't split legs across books)

## Bookmakers

Irish-accessible books only: Paddy Power · Betfair · Bet365 · BoyleSports · Ladbrokes · William Hill.
Exchanges are used for singles but excluded from accumulator pricing (you can't place an acca on an
exchange).

---

## Setup

```bash
cp .env.example .env
# ODDS_API_KEY      — free tier at https://the-odds-api.com
# ANTHROPIC_API_KEY — https://console.anthropic.com

pip install -r requirements.txt
python server.py     # http://localhost:8000
```

### ⚠️ API quota — read this before deploying

The Odds API bills **`markets × regions` credits per league request**. With the defaults
(3 markets, `uk`, 3 leagues) one full refresh costs **9 credits**.

The free tier is **500 credits per month** — about **55 full refreshes total**, i.e. under two a day.

So the app is **demand-driven by default**: no background timer, and odds are only re-fetched when
someone loads the app and the snapshot is older than the TTL (6h). An idle app spends nothing.
Live quota is shown at `/api/status`.

**For a real, marketable deployment you want a paid Odds API plan.** Then set
`ODDS_REFRESH_MINUTES=15` to keep a background thread warming the cache.

| Env var | Default | Purpose |
|---|---|---|
| `ODDS_REFRESH_MINUTES` | `0` (off) | Background refresh cadence. Set on a paid plan. |
| `ODDS_CACHE_MINUTES` | `360` | Demand-driven cache TTL |
| `ODDS_REGIONS` | `uk` | Widening to `uk,eu` **doubles** credit burn |
| `BOOKMAKER_WHITELIST` | Irish books | Books to show prices from |
| `INTEL_WORKERS` | `1` | Analyst concurrency. Raise only on a higher API tier. |
| `ADMIN_KEY` | random | Unlocks the Admin tab |

## Deploy (Render)

`render.yaml` defines a free web service. Deploy via **New → Blueprint**, then set `ODDS_API_KEY`,
`ANTHROPIC_API_KEY` and `ADMIN_KEY` as dashboard secrets.

---

## Architecture

```
leagues.py      — league registry: sport keys + per-league trusted research domains
odds.py         — Odds API fetch across all leagues, de-vig, line-shopping
names.py        — club-name normalisation (Man Utd / Spurs / Falkirk F.C. → canonical)
club_intel.py   — per-match web research + Claude analyst, cached
server.py       — FastAPI backend, caching, background analysis, visitor stats
static/         — single-page dashboard (index.html + js/ + css/)
```

### Adding a league

One entry in `leagues.py` — sport key, display name, and the domains the analyst may research from.

**The domain list is not a wishlist.** Anthropic's web-search tool rejects the *entire* request if any
listed domain blocks its crawler, so one bad entry silently kills research for that league. BBC,
Guardian, Marca, AS and Transfermarkt all block it. Verified-accessible and verified-blocked lists are
recorded in `leagues.py` — probe before adding.

---

## Caching

| Cache | TTL | Where |
|---|---|---|
| Match odds | 6h (demand-driven) | `odds_cache.json` + memory |
| Analyst cards | 12h | `intel_cache.json` |
| Match research | 6h | `research_cache.json` |

## Reality check

These are +EV leans and pricing soft-spots — **not predictions**. Premier League and La Liga match
markets are among the most efficient in betting: dozens of books, huge liquidity, no information
asymmetry. Observed edges top out around 1%, and the app's confidence tiers are calibrated to that
reality rather than inflated to look impressive.

The analyst layer exists to filter out mathematically-edged bets with no football logic behind them.
Stake flat, treat the analyst as a second opinion, and always line-shop.

Gamble responsibly. If it stops being fun, stop. — [GambleAware](https://www.begambleaware.org/) ·
[Gambling Care (IE)](https://www.gamblingcare.ie/)
