# WC Edge Finder — Engineering Handoff

A technical reference for a developer taking over this codebase. It documents the
architecture, data flow, modules, configuration, deployment, and known
limitations. For the *product* explanation (what each tab means for a punter) see
[`README.md`](README.md); the in-app **Methodology** tab also has an interactive
map of this same pipeline.

> Scope note: every value and behaviour below was taken from the source at the
> time of writing. Where a number is a tunable constant, the file and symbol are
> named so it can be re-verified.

---

## 1. What it is

A single-page web app that surfaces betting "edges" for the 2026 FIFA World Cup by
combining three independent signals:

1. **De-vigged bookmaker odds** → a consensus *fair probability* per outcome.
2. **Prediction-market prices** (Kalshi, Polymarket) → an independent cross-check.
3. **A grounded LLM football analyst** (Claude) → a football read per match.

The central design principle is a **two-layer separation**: a *price/maths layer*
and an *analyst/football layer* are computed independently and only combined at the
output. The analyst never sees enough to judge value; the maths layer has no
football opinion. This lets the two **agree** (the strongest signal) or **disagree**
(a flag) rather than one contaminating the other.

---

## 2. Tech stack

| Concern | Choice |
|---|---|
| Language / runtime | Python 3.12 (`PYTHON_VERSION=3.12.6` on Render) |
| Web framework | FastAPI, served by `uvicorn[standard]` |
| LLM | Anthropic SDK — `claude-sonnet-4-6` (analysis), `claude-haiku-4-5-20251001` (injury web search) |
| Frontend | Vanilla HTML / CSS / JS — **no framework, no build step** |
| HTTP client | Python stdlib `urllib` (no `requests`) |
| Persistence | Static CSVs (committed) + JSON file caches (gitignored) — **no database** |
| Dependencies | `fastapi`, `uvicorn[standard]`, `anthropic` (entire `requirements.txt`) |

**External services:** The Odds API (odds), Anthropic (analyst + injury search),
Open-Meteo (weather, no key), Kalshi & Polymarket Gamma (prediction markets),
ip-api.com (geo-IP enrichment for the admin view only).

---

## 3. Repository layout

```
server.py              FastAPI app: routes, the build pipeline, caching,
                       background refresh threads, admin + geo-IP.
football_intel.py      Analyst layer: Claude calls, prompt construction, the
                       injury digest, weather, and live team-form refresh.
static_data.py         Static reference data loaded once from data/*.csv
                       (teams, FIFA ranks, recent form, squads, venues, schedule).
build_form.py          Rebuilds data/team_form.csv from the public
                       international-results dataset (CLI + server-callable).
wc_odds.py             The Odds API fetch + per-book proportional de-vig (1X2).
prediction_markets.py  Kalshi + Polymarket fetchers and team-name normalisation.
compare.py             Three-way book-vs-PM divergence report logic.
render.yaml            Render blueprint (build/start commands, env var stubs).
requirements.txt       fastapi, uvicorn[standard], anthropic.
.env.example           Environment variable template.
README.md              Product/user-facing methodology.
ANALYSIS.md            Supplementary analysis notes.

data/                  Sourced reference CSVs (committed):
  teams.csv            48 teams + country climate (heat tolerance).
  team_facts.csv       FIFA world ranking per team.
  team_form.csv        Last-8 internationals per team (rebuilt by build_form.py).
  players.csv          Official FIFA 2026 squad lists.
  venues.csv           Stadiums: city, lat/lon, altitude, roof, climate normals.
  matches.csv          Fixture schedule (venue + round mapping).
  countries.csv, data_dictionary.csv, source_audit.csv  reference / provenance.

static/
  index.html           Single page: nav, all view containers, modals.
  css/app.css          Design tokens (:root) + all styling. Dark theme.
  js/
    helpers.js         Formatting, verdict logic, analystConfirms,
                       analystDisagrees (+ token logic), weather flag.
    data.js            Fetches /api/bets + /api/intel, polling, app state.
    app.js             Nav / view switching, init.
    views-today.js     "Today" tab.
    views-best.js      "Best Bets" (Picks + Analyst Writeups).
    views-markets.js   "Markets" (Value Singles / Accumulators / Builder /
                       Divergence) incl. parlay rendering + the ⚠ disagree flag.
    views-journal.js   "My Bets" journal (localStorage).
    views-injuries.js  "Injuries & Suspensions".
    views-admin.js     "Admin" (owner-only visitor stats).
    views-method.js    "Methodology" interactive pipeline explorer.

Runtime cache files (gitignored; created at runtime):
  odds_cache.json, intel_cache.json, weather_cache.json, injury_digest.json
Committed seed:
  intel_seed.json      Analyst cards shipped so a fresh deploy isn't empty.
```

---

## 4. Runtime architecture

Single FastAPI process. One shared in-memory cache feeds every endpoint; several
daemon threads keep data warm. No worker pool, no queue, no DB.

**Request → response (the hot path):**

1. `get_raw()` returns the shared snapshot, rebuilding via `_build_raw()` only when
   the odds TTL has expired (TTL is driven by `ODDS_REFRESH_MINUTES`).
2. `_build_raw()` ([server.py](server.py)) pulls one Odds API call covering **h2h +
   totals + spreads**, plus Kalshi/Polymarket, then per match produces:
   - **singles** — outcomes with edge above `EDGE_MIN`.
   - **acca_pool** — *every* priced outcome (favourites included) as an acca leg
     candidate.
   - **matches** — divergence-ranked match list.
   - **price_index** — `{match: {analyst_token: price}}` so analyst recommendations
     can show real odds.
3. Weather signal and round are attached per match; the acca pool is re-priced to
   exclude exchanges (an acca must be placeable at one sportsbook).
4. `_build_parlays()` builds accumulators from the acca pool.
5. Already-cached analyst intel is attached; a background intel fetch is triggered
   for missing matches.

**Background daemon threads** (all started at import; on Render free tier they only
run while the process is awake):

| Thread | Cadence | Purpose |
|---|---|---|
| Odds auto-refresh | `ODDS_REFRESH_MINUTES` (15) | keep the odds snapshot warm |
| Form auto-refresh + startup catch-up | `FORM_REFRESH_HOURS` (12) | rebuild team form, re-analyse changed teams |
| Startup injury fetch | once | populate the injury digest if missing |
| Background intel fetch | on demand | analyse matches lacking a card (capped, serialised) |

---

## 5. Data sources & ingestion

| Source | Module | Cadence / TTL | Notes |
|---|---|---|---|
| Bookmaker odds | `wc_odds.py`, `_fetch_events` | ~15 min | One call: 1X2 + O/U + Asian handicap. Filtered to `BOOKMAKER_WHITELIST`. |
| Prediction markets | `prediction_markets.py` | per build | Kalshi + Polymarket implied probs, normalised to 100%. |
| Recent form | `build_form.py` → `data/team_form.csv` | ~12 h + startup | Last 8 played internationals/team, tagged by competition. WC results roll in during the tournament. |
| Injuries | `football_intel.fetch_wc_injury_digest` | 12 h | One tournament-wide web search on **Haiku**, restricted to skysports/goal/espn/fifa, structured JSON. |
| Weather / venue | `football_intel.get_conditions_for_match` | 6 h | Open-Meteo forecast inside the ~15-day horizon, else venue climate normal. Roofed = climate-controlled. |
| Squad + FIFA rank | `static_data.py` (`players.csv`, `team_facts.csv`) | static | Roster + ranking only — **no per-player performance data**. |

---

## 6. The two layers

### 6.1 Price / maths layer (no football opinion)

- **De-vig:** each bookmaker's implied probabilities (which sum > 100% due to the
  margin) are de-vigged **proportionally**, then averaged across books →
  `fair_prob` (the consensus *fair probability*). "Fair" = the market average, not
  ground truth.
- **Edge** = `fair_prob − 1/best_price` (percentage points). A model diagnostic.
- **EV** = `fair_prob × price − 1` (the money number).
- **Verdict** (`verdictMeta`, [static/js/helpers.js](static/js/helpers.js)), run on EV
  and gated by a longshot-noise check `edgeReliable` (`edge ≥ 0.5 + 0.3·(price−1)`):
  - **Bet Now** — EV ≥ +2% **and** reliable
  - **Lean** — EV ≥ 0
  - **Track Price** — EV ≥ −3%
  - **Avoid at Price** — below that
- **Server-side confidence** (high/medium/low) is derived from edge vs
  `VALUE_THRESHOLD`/`EDGE_MIN` **plus prediction-market confirmation** — *not* the
  analyst.
- **Divergence** = `fair_prob − prediction-market consensus`, drives the Markets tab.

### 6.2 Analyst / football layer (`football_intel.py`)

- **Model:** `claude-sonnet-4-6`. Injury web search runs on
  `claude-haiku-4-5-20251001` — a cheaper model on a **separate rate-limit bucket**
  so token-heavy searches don't starve the analysis budget.
- **Grounding:** the system prompt forbids inventing stats/records/managers/
  formations and forbids judging value or naming a "best bet". It is given only:
  FIFA ranking, official squad, recent form (now World-Cup-led), the injury digest,
  venue/conditions, and the prices **as context only**.
- **Output:** strict JSON — `home_form`, `away_form`, `key_absences`,
  `conditions_impact`, `tactical_matchup`, `goals_assessment`, `market_read`,
  `recommended_bets[]` (market + outcome + confidence + strength + reasoning),
  `overall_summary`, `intel_confidence`, `knowledge_caveat`.
- **Caching:** `intel_cache.json`, TTL **7 days** (`CACHE_TTL`); falls back to the
  committed `intel_seed.json` on a fresh deploy. The cache key includes
  `PROMPT_VERSION`, so bumping the prompt invalidates stale cards.
- **Rate-limit handling (Tier-1 critical):** analysis calls are **serialised**
  (`INTEL_WORKERS`, default 1) — parallel calls all 429 and burn their retry budget,
  saturating the shared bucket. `max_retries=8`. `MAX_INTEL_MATCHES=24` caps a fetch
  to the current active round.

---

## 7. Output surfaces (frontend tabs) and what drives them

| Tab / sub-tab | Driven by | Notes |
|---|---|---|
| 📅 Today | both | Next matchday + analyst read per fixture. |
| ★ Best Bets · **Picks** | **both (two gates)** | Appears only if (1) analyst recommended the outcome **and** (2) price is fair-or-better. Tiers: Strong / Solid / Speculative. |
| ★ Best Bets · Analyst Writeups | analyst | Full written read per match. No price gate. |
| 📊 Markets · Value Singles (+EV) | maths (+ analyst ★) | Edge/EV-ranked singles; ★ when analyst also recommends it. |
| 📊 Markets · Accumulators (−EV) | maths (legs) + analyst (⚠ flag) | See §8. |
| 📊 Markets · Acca Builder | maths | Build-your-own slip, priced at one book. |
| 📊 Markets · Market Divergence | maths | Book fair prob vs prediction-market consensus. |
| 📒 My Bets | neither | localStorage journal; snapshots fair prob + EV at bet time (CLV groundwork). |
| ⋯ Injuries / Methodology / Admin | reference | Digest view / docs + interactive map / owner stats. |

**The analyst hard-gates exactly one surface: Best Bets · Picks.** Everywhere else it
is a confirming (★) or advisory (⚠) signal, or absent.

---

## 8. Accumulator logic

Legs are selected by **maths only**, never by the analyst:

1. Eligible legs = acca-pool outcomes with `fair_prob` above the preset's
   `min_leg_prob`; with the **value guard** on, also drop any leg priced worse than
   `ACCA_GUARD_TOL_PCT` (−4%) under fair.
2. One leg per match (no correlated same-match legs).
3. The whole slip must clear `min_combined_prob`.
4. Priced at a **single bookmaker** (`_best_single_book`) — never line-shopped across
   books, which would yield an unplaceable price. Exchanges are excluded.
5. Ranked by **combined probability** (chance of landing), not payout. EV is shown
   and is essentially always negative for favourite accas (multiplying legs
   multiplies the margin) — this is stated honestly in the UI.

**Presets** (`ACCA_PRESETS`, [server.py](server.py)):

| Preset | min_leg_prob | leg counts | min_combined_prob |
|---|---|---|---|
| banker | 0.62 | 2–4 | 0.30 |
| balanced | 0.55 | 4–6 | 0.12 |
| punchy | 0.45 | 6–8 | 0.04 |

**Analyst-disagrees soft flag (advisory):** a leg shows **⚠ Analyst disagrees** when
the analyst recommends an outcome that is *mutually exclusive* with that leg (e.g.
backing the draw against a team on a −1.5 handicap). Implemented client-side
(`analystDisagrees` in [helpers.js](static/js/helpers.js)); the server passes
`spread_team`/`spread_point` onto each leg so handicaps can be evaluated. It fires
only on a genuine contradiction — never on mere absence of endorsement — and is
**advisory only**: it does not remove, re-rank, or veto the leg.

---

## 9. HTTP API

All read endpoints serve the shared cache; the cost-bearing ones are cooldown-gated.

| Method · Path | Purpose | Notes |
|---|---|---|
| `GET /` | Single-page app | serves `static/index.html` |
| `GET /api/status` | Health: odds key set, match count, last fetch | public |
| `GET /api/bets?risk&value_guard&round` | Singles + parlays + acca_pool | `risk` ∈ banker/balanced/punchy |
| `GET /api/intel` | Analyst cards map + ready/loading/reanalysing flags | reads cache only |
| `GET /api/divergence` | Book vs prediction-market divergence | |
| `GET /api/injuries` | Cached injury digest | reads cache only |
| `GET /api/refresh` | Force odds re-fetch | cooldown 600 s |
| `GET /api/refresh-injuries` | Re-run injury search, invalidate affected cards | cooldown 300 s |
| `GET /api/refresh-form` | Rebuild form, re-analyse changed teams | cooldown 600 s |
| `GET /api/debug/sensible` | Why each single does/doesn't reach Best Bets | diagnostic |
| `GET /admin/stats?key=` | Visitor stats (geo-enriched) | requires `ADMIN_KEY` |
| `GET /admin/feed-books?key=` | Full bookmaker feed inventory | requires `ADMIN_KEY` |

The two refresh endpoints power UI buttons and are unauthenticated, so the
server-side cooldowns exist to stop a crawler draining the Odds API quota or
Anthropic web-search budget.

---

## 10. Configuration (environment variables)

Set in the Render env group **`WC EDGE`** (production) or a local `.env` (gitignored).

| Var | Required | Default | Effect |
|---|---|---|---|
| `ODDS_API_KEY` | ✅ | — | The Odds API key |
| `ANTHROPIC_API_KEY` | ✅ | — | Claude (analyst + injury search) |
| `ADMIN_KEY` | — | random per boot | unlocks the Admin tab; set a stable secret |
| `PORT` | — | 8000 | bind port (Render injects this) |
| `ODDS_REGIONS` | — | `uk` | Odds API regions |
| `BOOKMAKER_WHITELIST` | — | Irish books | comma-separated book titles to include |
| `ODDS_REFRESH_MINUTES` | — | 15 | background odds refresh cadence (0 = request-driven 2 h TTL) |
| `FORM_REFRESH_HOURS` | — | 12 | team-form refresh cadence (0 = disable) |
| `INTEL_WORKERS` | — | 1 | concurrent analyst calls (raise only above Tier 1) |
| `PYTHON_VERSION` | — | 3.12.6 | Render build |

**Tunable constants** (in [server.py](server.py), not env): `EDGE_MIN=0.005`,
`VALUE_THRESHOLD=0.015`, `PARLAY_MIN=0.005`, `ACCA_GUARD_TOL_PCT=-4.0`,
`MAX_INTEL_MATCHES=24`, `EXCHANGE_BOOKS`, refresh cooldowns. Analyst model IDs and
`PROMPT_VERSION` live in [football_intel.py](football_intel.py).

---

## 11. Deployment

Hosted on **Render** (free plan; the process spins down on idle and cold-starts on
the next request — relevant because background loops only run while awake).

- **Build:** `pip install -r requirements.txt`  ·  **Start:** `python server.py`
- **Two services, one repo:**
  - `wc-edge-finder` → branch **`ui-v2`** → **production** (custom domain).
  - `wc-edge-finder-3` → branch **`ui-v3`** → **staging** (custom domain).
  - `master` is the clone/ZIP default and trails `ui-v2` by a README-only commit.
- **Secrets:** Render env group **`WC EDGE`**, linked to both services. `.env` is
  gitignored; the repo is public — never commit keys.
- **Promote flow:** edit on `ui-v3` → `git push` (staging auto-deploys) → verify →
  `git push origin ui-v3:ui-v2` (fast-forward; live auto-deploys).
- **Cache-busting:** frontend scripts are versioned (`?v=N` in `index.html`); bump
  on any JS/CSS change so returning browsers reload.

---

## 12. Local development

```bash
pip install -r requirements.txt
cp .env.example .env          # add ODDS_API_KEY + ANTHROPIC_API_KEY
python server.py              # http://localhost:8000
python build_form.py          # (optional) refresh data/team_form.csv manually
```

No build step for the frontend — it is served as-is from `static/`. The server must
run with the project root as the working directory (relative paths for `.env`,
`static/`, and the JSON caches).

---

## 13. Known limitations & gotchas

- **Anthropic Tier-1 rate limit is the real bottleneck**, not latency. Analysis is
  serialised on purpose; symptom of over-parallelism is "analyst never loads"
  (silent 429s). To scale: raise the API tier, then bump `INTEL_WORKERS` and
  `MAX_INTEL_MATCHES`.
- **No per-player form/performance data** — squad data is roster only. The analyst
  reasons at team level; a single in-form player is only captured indirectly via
  team results. This is the largest analytical gap.
- **Accumulators are always −EV** by construction; the app finds the least-bad
  version and labels the negative EV honestly.
- **Odds feed gaps:** the live feed has at times returned totals but **0
  Asian-handicap (spreads)** prices, so analyst handicap picks may not surface as
  cards even though the code supports them.
- **"Fair" ≠ truth** — it's the market consensus; beating it means a better price,
  not a proven correct probability. Proportional de-vig slightly flatters longshots,
  so small edges on big prices are treated as noise (speculative).
- **No database / single process** — visitor stats are in-memory and reset on
  restart; all other state is JSON files on disk that vanish on a fresh container
  (hence the committed `intel_seed.json`).
- **Public repo** — keys must stay in Render only.

---

## 14. Recent changes (June 2026)

| Change | Commit | Files |
|---|---|---|
| Live team-form refresh during the tournament (rebuild + invalidate changed teams, 12 h loop + startup catch-up, `/api/refresh-form`) | `e0d1f3f` | build_form.py, football_intel.py, static_data.py, server.py |
| Analyst prompt now leads with / names in-tournament World Cup results (no longer blurs a WC draw into friendlies); `PROMPT_VERSION` 1→2 | `1be82dd` | football_intel.py |
| Accumulator legs show a ⚠ "analyst disagrees" soft flag on genuine contradictions (advisory, no veto) | `baa54b9` | server.py, static/js/helpers.js, static/js/views-markets.js |
| Methodology tab gained an interactive, clickable pipeline explorer | `d19f8de` | static/index.html, static/js/views-method.js |

---

## 15. Suggested next steps for a new owner

1. **Add a results-backed evaluation loop** — persist `My Bets` server-side and
   compare modelled EV vs realised P/L and closing-line value over a real sample.
2. **Player-level form** — the biggest signal gap; needs a per-player stats source
   and a new analyst prompt input (token-expensive at current API tier).
3. **Promote analyst caching to a store** that survives cold starts (e.g. a small
   managed DB or object storage) instead of disk JSON.
4. **Move tunables to env/config** so thresholds can be changed without a deploy.
