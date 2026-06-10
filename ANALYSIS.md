# WC Edge Finder — Overnight Audit (ui-v2 branch)

Audit performed as both a professional gambler and a senior engineer. Findings ordered by
severity within each section. Items marked **[FIXED]** were implemented on this branch.

---

## 1. Mathematical correctness

### 1.1 Frontend "EV" is not EV — probability-points gap mislabelled **[FIXED — critical]**
Four places in `static/index.html` computed:

```
ev = (fairProb − 1/combinedPrice) × 100
```

and displayed it as "EV" / "Expected gain: +€X per €Y staked"
(`parlayHTML`, `recommendedAccaHTML`, `renderAccaTray`, `renderFixtureAcca`).

That is the **probability-point gap**, not expected value. True EV per unit stake is

```
EV = fairProb × price − 1
```

The difference is a factor of the price. Example: fair 10%, price 12.0 →
the old code shows "+1.7%" (+€0.17 per €10); the true EV is **+20% (+€2.00 per €10)**.
For −EV accas the old code *understated the expected loss* by the same factor — a slip the
UI showed as "Expected cost −€0.30 per €10" could really cost ~€2+ per €10 in expectation.
Anyone checking the maths would have caught this immediately. Now computed as
`fair × price − 1` everywhere.

The backend parlay `ev_pct` (`combined_fair * combined_price - 1`) was already correct —
only the client-side recomputation (needed when the user switches bookmaker) was wrong.

### 1.2 "Edge" is probability points, not % return — now disambiguated **[FIXED]**
Server-side `edge = (fair_prob − 1/best_price) × 100` is a legitimate metric (probability
points above the price's implied probability), and the code uses it consistently. But the
UI displayed it as "+2.1% edge" alongside money figures, inviting the reading "2.1% return".
A 2-point edge is ~2.6% EV on a 1.30 favourite but ~16% EV on an 8.0 longshot. The UI now
shows **EV (€ per stake and %) as the primary money metric** on singles, sensible bets and
accas, with the probability-point edge kept as the secondary model diagnostic. Verdict
thresholds (Bet Now / Lean / Track Price / Avoid) now run on EV%, gated by the existing
longshot-noise check (`edgeReliable`).

### 1.3 Book vs prediction-market gap was not apples-to-apples **[FIXED]**
Book probabilities are de-vigged (sum to 1.0). Kalshi probabilities are raw bid/ask
midpoints and Polymarket raw prices — a 3-way market's quotes typically sum to 0.97–1.05,
so up to ±2 points of every reported "PM gap" was just the prediction market's own spread,
not signal. `prediction_markets.py` now normalises a 3-way's probabilities to sum to 1
(when the raw sum is within a sane 0.85–1.20 band), so divergence numbers compare
de-vigged vs de-vigged.

### 1.4 De-vig method: proportional only — acceptable, now documented
`devig()` uses the proportional (margin-weights) method, applied per-book then averaged —
a sound consensus approach and the standard baseline. It is known to slightly overstate
fair probabilities of longshots versus the power/Shin methods (favourite–longshot bias),
which means **edges on outsiders are systematically optimistic**. The existing
`edgeReliable()` demotion of small edges on long prices partially compensates. Documented
honestly in the new Methodology tab rather than silently swapped (proportional + a
noise-gate is defensible; power-method de-vig is a sensible future improvement).

### 1.5 Accumulator maths
- Combined fair probability multiplies leg fair probs — correct **given independence**,
  which holds across different matches (no same-match legs are allowed: good).
- Slips are priced at a single bookmaker (`_best_single_book`) — correct and unusually
  honest; most acca tools line-shop legs across books into a price nobody will lay.
- Margin compounding is real: with the value guard allowing legs up to −4 points under
  fair, a 6-leg slip can quietly compound to roughly −10…−20% EV. The UI did label accas
  −EV in a banner, but the per-slip number understated it (see 1.1). Fixed by 1.1.

### 1.6 Disk odds cache never worked — `json` not imported **[FIXED — costs real money]**
`server.py` `get_raw()` calls `json.loads`/`json.dumps` but never imports `json`. Both
calls sit inside `try/except Exception: pass`, so the `NameError` was silently swallowed:
**the odds disk cache has never saved or loaded**. On Render's free tier the process spins
down on idle and restarts on every visit; every restart burned a fresh Odds API call even
when a <2h-old snapshot existed. With a 500 req/month budget this is material. Fixed
(`import json`), and `odds_cache.json` added to `.gitignore`.

### 1.7 Minor
- `_active_round()` compares `m["commence"] > datetime.now(timezone.utc).isoformat()` —
  string-comparing `"...Z"` against `"...+00:00"` suffixes. Works for date-distinct values;
  fragile at second-level granularity. **[FIXED]** with real datetime parsing.
- `_intel_busy` is checked-then-set outside the lock (benign race: duplicate background
  fetches possible). **[FIXED]** — flag now flipped under `_intel_lock`.
- Rounding is display-only everywhere (probabilities kept as floats internally) — fine.

## 2. Betting-logic audit (professional gambler's view)

### 2.1 The two-signal "Sensible Bets" design is sound — with caveats
Analyst (football reasons) gates the candidate list; the price layer scores value. This is
the right division of labour, and the prompt discipline ("you do NOT have reliable odds,
never crown value") is genuinely well done. Caveats a sharp would raise:
- **The "fair" benchmark is the de-vigged consensus of ~6 soft books.** That measures
  *line-shopping value vs the consensus*, not value vs the true probability. Soft-book
  consensus on international football is decent but biased (favourite–longshot, home-nation
  money). The honest claim is "you're beating the market average price", not "this bet wins
  long-term". The Methodology tab now states exactly this.
- **Edge ≥1.5pts = "Bet Now" was too eager** on thin data (one snapshot, 2h cache, six
  books). Recalibrated to EV-based thresholds plus the reliability gate; "Bet Now" also
  requires the edge to be outside the longshot-noise band.
- **No variance/bankroll guidance existed.** Added: flat-stakes note + responsible
  gambling footer; EV framing makes the long-run nature explicit.

### 2.2 Things that would embarrass the owner — addressed
- **Profit-if-wins dominated every money panel** while EV was absent (singles) or wrong
  (accas). That is the classic recreational-tout pattern. Inverted: EV first, profit
  secondary. **[FIXED]**
- **"Expected cost" of accas understated** (see 1.1). **[FIXED]**
- **A "🎯 Bet Now" badge** on a +1.5pt edge derived from one odds snapshot is overconfident.
  Thresholds tightened and semantics documented in Methodology. **[FIXED]**
- **No track record.** The My Bets journal now records the model's fair probability and EV
  at log time (closing-line-value groundwork) and the journal summary shows expected vs
  actual P/L — the only honest way to prove (or disprove) the edge. **[ADDED]**
- The **"⭐ Recommended Acca"** headline block ranks by chance-of-landing and shows
  profit-if-wins prominently; it is typically −EV after sportsbook margin compounding. It
  now carries the corrected EV figure. It remains entertainment-framed; consider removing
  it entirely from any paid tier.

### 2.3 Legal/ethical flags (not legal advice)
- Advertising betting recommendations to Irish/UK users without 18+ messaging and safer-
  gambling signposting is a regulatory problem (and a moral one). **[FIXED — footer with
  18+, BeGambleAware / Gambling Care links, "not financial advice" disclaimer]**
- Deep links "Place at <bookmaker>" look like affiliate marketing. They are plain links
  (no tags), but if this ever charges money, check Irish Gambling Regulation Act
  advertising rules before adding affiliate codes.
- Charging subscriptions for tips in IE/UK is legal but jurisdictions differ; terms of
  service + "for information only" language are table stakes. Not yet present beyond the
  footer disclaimer.

## 3. Data pipeline reliability

- **API budget**: one Odds API call per 2h TTL (plus retry fallback) — frugal. But
  `/api/refresh` was **unauthenticated and uncooled**: anyone (or a crawler) could force
  fetches and drain the 500/month quota. **[FIXED — server-side cooldown (10 min) on
  forced refresh; same for `/api/refresh-injuries` (5 min), which burns Anthropic web
  searches and cascades analyst re-runs.]**
- **Render restarts**: ephemeral disk means `intel_cache.json`, `odds_cache.json`,
  `injury_digest.json`, `weather_cache.json` vanish on redeploy (and free-tier instances
  restart on idle). The committed `intel_seed.json` cushions analyst cards; the odds
  cache fix (1.6) now actually works within a single instance's lifetime but not across
  deploys — acceptable at this budget, worth a small KV store if it ever charges money.
- **Race conditions**: intel fetching is well-locked around file I/O; the `_intel_busy`
  race is fixed; `/api/bets` mutates cached singles in place while holding no lock
  (worst case: a torn read of `intel` attachment — benign, left as is).
- **Stale data**: odds age is shown in the header; analyst cards show "analysed Xh ago".
  Weather circuit-breaker on 429s is good engineering.

## 4. Security

- **No hardcoded secrets found** (scanned for key patterns; `.env` is gitignored;
  Render env vars used). `.env.example` contains placeholders only.
- **XSS — real risk, fixed**: dozens of template-literal `innerHTML` sinks interpolate
  text that originates outside the app: analyst JSON fields (LLM output influenced by web
  search results), the injury digest, team names from The Odds API, bookmaker titles.
  The digest renderer escaped HTML, but analyst free-text (`reasoning`,
  `overall_summary`, `home_form`, …) and team labels did not. A poisoned web page quoted
  by the injury search could in principle ride into `reasoning` and execute. **[FIXED —
  added `esc()` and applied it to the external-text interpolations in the render paths.]**
- `/admin/stats` uses `secrets.compare_digest` — fine. The random fallback key prints to
  logs — acceptable.
- CORS: no middleware added → same-origin only. Fine.
- Rate limiting: none globally (Render fronts it); the two cost-bearing endpoints now have
  cooldowns, which is the part that matters.
- `X-Forwarded-For` trust is spoofable but only feeds vanity stats.

## 5. Subscription readiness — honest assessment

**Not ready to charge for.** What a paying customer would expect and what exists:

| Expectation | Status |
|---|---|
| Proof the edge is real (CLV / settled P&L history) | Started: journal now captures fair prob + EV at log time; needs months of data |
| Methodology they can interrogate | **Added** (Methodology tab) |
| Coverage | One tournament, six books, 1X2/totals/AH only |
| Alerting (odds move, new pick) | Absent |
| Account system / multi-device journal | localStorage only — wiped per device |
| Responsible gambling compliance | **Added** (footer), needs T&Cs for paid tier |

The honest sellable pitch is a **transparent line-shopping + second-opinion tool**:
"de-vigged consensus pricing, prediction-market cross-checks, and a grounded AI football
read — with every recommendation's EV shown and a journal that tracks whether it actually
worked." Claims that must be avoided: "guaranteed profit", "beat the bookies", any
unaudited win-rate, and anything implying the de-vig consensus equals true probability.

---

## Implementation log (Phase 2)

1. Backend correctness/reliability: `import json` cache fix, PM probability
   normalisation, refresh cooldowns, `_intel_busy` race, `_active_round` datetime fix,
   `.gitignore` odds cache.
2. Frontend maths: true EV everywhere (`fair × price − 1`), EV-first money panels,
   EV-based verdict thresholds.
3. XSS hardening: `esc()` applied across analyst/digest/team interpolations.
4. Trust features: Methodology tab, responsible-gambling footer, EV-first framing.
5. My Bets: fair-prob/EV capture at log time, expected-vs-actual P&L summary, CLV column.
6. Injuries tab: structured JSON digest (team/player/status/impact) with team & status
   filters, graceful fallback to legacy text digests.
7. Mobile: scrollable tab bar, stacking acca-builder sidebar, smaller-screen fixes.
