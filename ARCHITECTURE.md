# Soccer Edge Finder — Engineering Handoff

Technical reference for a developer taking over this codebase. For the *product* explanation (what
each tab means for a punter) see [`README.md`](README.md); the in-app **Methodology** tab has an
interactive map of the same pipeline.

> Every value below was taken from the source at the time of writing. Where a number is a tunable
> constant, the file and symbol are named so it can be re-verified.

---

## 1. Shape of the system

Two independent layers that meet only at the output:

```
                    ┌─────────────────────────────────────────┐
  The Odds API ────▶│ PRICE LAYER  (pure arithmetic)          │
   3 league keys    │ de-vig · consensus fair · best price    │──┐
                    │ edge · EV · sharp-line gap              │  │
                    └─────────────────────────────────────────┘  │
                                                                 ├──▶ UI
                    ┌─────────────────────────────────────────┐  │
  Web search   ────▶│ ANALYST LAYER  (Claude)                 │──┘
   per fixture      │ research → grounded read → up to 3 bets │
                    └─────────────────────────────────────────┘
```

The price layer has no football opinion. The analyst layer never sees enough to judge value (it gets
prices as context only, and is told not to). Agreement between them is the strongest signal the app
produces; disagreement is surfaced, not hidden.

## 2. Modules

| File | Responsibility |
|---|---|
| `leagues.py` | League registry. Sport keys + per-league trusted research domains. **The single place to add a competition.** |
| `odds.py` | Odds API client. `fetch_all()` across leagues, `devig()`, `analyse()`. Tracks quota from response headers in `QUOTA`. |
| `names.py` | Club-name normalisation. `normalize_team()` / `match_key()` / `is_draw()`. Has a self-test: `python names.py`. |
| `club_intel.py` | Research (Haiku + web search) → analysis (Sonnet) → disk cache. Owns the prompts. |
| `server.py` | FastAPI app, caching, background analysis, accumulator building, visitor stats. |
| `static/` | Single-page dashboard: `index.html` + `js/` views + `css/app.css`. No build step. |

## 3. Request flow

`GET /` serves the SPA. On load the frontend fires three calls in parallel:

| Endpoint | Returns |
|---|---|
| `/api/matches` | Per-match consensus fair prices, sharp line, gap, totals |
| `/api/bets` | Value singles + accumulators (`risk`, `value_guard`, `round` params) |
| `/api/intel` | Cached analyst cards; `intel_loading` drives frontend polling |

`get_raw()` (server.py) is the single shared build behind all three — one odds fetch feeds
everything. It enforces the cache TTL and persists to `odds_cache.json` so a restart doesn't
re-spend quota.

Analyst cards are built by a **background thread** (`_run_intel_bg`), so the odds render immediately
and cards fill in. The frontend polls `/api/intel` every 8s while `intel_loading` is true.

## 4. The price layer

**De-vig.** Each bookmaker's 1X2 implied probabilities are normalised proportionally to sum to 1,
then averaged across books → consensus fair probability. Proportional de-vig slightly flatters
longshots (favourite–longshot bias); the frontend treats small edges on big prices as noise.

**Edge.** `edge = (fair_prob − 1/best_price) × 100`, in probability points.

**Sharp line.** `_sharp_h2h_fair()` de-vigs the first available book from `SHARP_BOOKS`
(Pinnacle, then exchanges). `sharp_gap = fair_prob − sharp_prob`; **negative means the sharp book
rates the outcome more likely than consensus** — supportive.

**Confidence tiers** (`server.py`, calibrated for club markets — see §7):

| Tier | Condition |
|---|---|
| `high` | edge > `VALUE_THRESHOLD` (1.0%) **and** sharp confirms |
| `medium` | edge > 1.0%, or edge > `EDGE_MIN` (0.4%) with sharp confirming |
| `low` | any remaining positive edge above `EDGE_MIN` |

**Accumulators.** Exchanges are dropped from acca legs (you cannot place an acca on an exchange) and
every leg is re-priced from sportsbooks only, so EV is computed off a placeable price. Presets in
`ACCA_PRESETS` floor the *combined* win probability, not just per-leg.

## 5. The analyst layer

Two calls per fixture:

1. **Research** — `get_research()`, Haiku + `web_search`, restricted to `leagues.domains_for(key)`.
   Asks for form, table position, team news, head-to-head. Cached 6h in `research_cache.json`.
2. **Analysis** — `get_match_intel()`, Sonnet, reads only that research + price notes. Returns
   strict JSON with `recommended_bets[]`. Cached 12h in `intel_cache.json`.

`PROMPT_VERSION` is part of the cache key — bump it and every card re-analyses.

### Prompt rules that exist because of real failures

Do not remove these without re-testing against live fixtures:

- **Attribution.** Research mixes clubs up (a Bournemouth article surfaced in a Liverpool fixture
  search, and the analyst reported Bournemouth's manager as Liverpool's). The prompt requires
  verifying club attribution and forbids naming a manager it isn't confident about.
- **Absence of evidence.** The analyst read "no injuries found" as "squad fully fit" and built an
  edge on it. The prompt now requires "no absentees confirmed" phrasing and forbids treating one
  side's missing data as the other side's advantage.
- **Numbers discipline.** No invented scorelines, table positions, or xG.

## 6. Quota — the real deployment constraint

The Odds API bills **`markets × regions` credits per league request** (empirically verified):

| Config | Cost/league | Full refresh (3 leagues) |
|---|---|---|
| `uk` + h2h | 1 | 3 |
| `uk` + h2h,totals,spreads | 3 | **9** |
| `uk,eu` + h2h,totals,spreads | 6 | 18 |

Free tier = 500 credits/month ≈ **55 full refreshes**. Hence `ODDS_REFRESH_MINUTES` defaults to `0`
(demand-driven, 6h TTL). A background timer at 15min would exhaust the month in a day.

Anthropic spend scales with *fixtures*, not time: ~28 fixtures × (1 Haiku search + 1 Sonnet call)
per 12h cycle.

## 7. Why the thresholds are lower than the World Cup version

Club league 1X2 is among the most efficient markets in betting. Observed best-price edges top out
around 1%, where the tournament markets this app was originally built for routinely offered 2–3%.
`VALUE_THRESHOLD` was lowered 1.5% → 1.0% and `EDGE_MIN` 0.5% → 0.4%.

**The measurement did not change** — only the labels, so they describe the market the app now covers.
Do not raise these back without checking that Value Singles is still non-empty.

## 8. Known limitations

- **No weather/venue layer.** Removed with the WC stadium table. Re-addable with a club-ground CSV
  (lat/lon per home ground) feeding an Open-Meteo lookup.
- **No league table data.** Position/form come from web search, so they inherit its variance — two
  runs can differ in completeness. A proper standings API would make this deterministic.
- **Exchange commission is not modelled.** Betfair/Smarkets often show as `best_book`, but the
  realised price is 2–5% lower after commission. Singles EV is therefore mildly optimistic when the
  best price is an exchange.
- **Research quality varies by league.** EPL and La Liga are well covered; Scottish Premiership
  sources are thinner, so cards there lean more on the model's own knowledge.
- **Frontend has no build step or tests.** Views are plain scripts sharing globals; verification is
  manual in-browser.

## 9. Local development

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python server.py            # http://localhost:8000
python names.py             # normaliser self-test
python odds.py              # CLI edge report across all leagues
python club_intel.py "Arsenal" "Chelsea" soccer_epl   # single-fixture analyst check
```

`/api/status` is the health endpoint: quota, per-league fetch errors, analyst cache state.
