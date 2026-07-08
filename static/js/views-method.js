/* Methodology — interactive pipeline explorer.
   A clickable map of the site's data flow. Every description below is grounded in
   the actual code (server.py / football_intel.py / static_data.py / build_form.py
   and the frontend), not a guess. Click a box or a relationship chip to see what
   it is and how it links to the rest. */
(function () {
  'use strict';

  // ---- accurate per-node content -----------------------------------------
  const INFO = {
    'src-odds': {
      t: 'Bookmaker odds — The Odds API',
      d: `Live decimal odds for every World Cup match, pulled in one request covering three markets:
          <b>match result (1X2)</b>, <b>Over/Under</b> and <b>Asian handicap</b>. Filtered to the six
          Irish-accessible books — Paddy Power, Betfair, Bet365, BoyleSports, Ladbrokes, William Hill.
          This is the backbone: every fair-probability, edge and EV number on the site derives from it.`,
      m: '_fetch_events() · BOOKMAKER_WHITELIST · refresh ≈15 min (ODDS_REFRESH_MINUTES)',
    },
    'src-pm': {
      t: 'Prediction markets — Kalshi & Polymarket',
      d: `Real-money exchanges with low margins. Their implied probabilities are normalised to sum to
          100% and compared with the book consensus. Used two ways: to rank matches by <b>divergence</b>
          (Market Divergence tab) and to <b>confirm or temper</b> a single's edge — agreement earns the
          ★ both-agree signal. It is an independent cross-check, not a price you bet here.`,
      m: 'prediction_markets.py (Kalshi + Polymarket implied probabilities)',
    },
    'src-form': {
      t: 'Recent form — last 8 internationals ●',
      d: `Each team's last <b>8 played internationals</b> (W/D/L, scores, opponents), each tagged by
          competition, built into <code>data/team_form.csv</code> from the public international-results
          dataset. Auto-rebuilt about every 12 hours (plus a catch-up on startup if stale), so
          <b>World Cup results roll into the window</b> during the tournament and push out older friendlies.
          Feeds only the analyst. ● marks the live-refresh feature added in this work.`,
      m: 'build_form.py · refresh_team_form() · FORM_REFRESH_HOURS=12 · team_form_text()',
    },
    'src-injuries': {
      t: 'Injuries & suspensions digest',
      d: `One tournament-wide web search (run on <b>Claude Haiku</b>, restricted to Sky Sports / Goal /
          ESPN / FIFA), returned as structured JSON and cached 12 hours. Shown in the Injuries tab and
          injected into every analyst card. When the digest changes, only the affected matches' cards
          are invalidated and re-analysed.`,
      m: 'fetch_wc_injury_digest() · INJURY_DOMAINS · INJURIES_TTL=12h',
    },
    'src-weather': {
      t: 'Weather & venue',
      d: `A real <b>Open-Meteo</b> forecast for the venue when the match is within ~16 days, otherwise the
          venue's June/July climate normal — always labelled which. Roofed stadiums are treated as
          climate-controlled. This drives a heat/altitude signal that can lean goals Under/Over or favour
          an acclimatised side, and is passed to the analyst.`,
      m: 'get_conditions_for_match() · weather_signal() · Open-Meteo (no key)',
    },
    'src-squad': {
      t: 'Squad & FIFA ranking',
      d: `The official FIFA 2026 squad lists (players, clubs, ages) and the FIFA world ranking, from
          static sourced files. The analyst's strength anchor and roster reference. Note: this is
          <b>roster only</b> — there is no per-player form or performance data anywhere in the system.`,
      m: 'data/players.csv · data/team_facts.csv · static_data.py',
    },
    'layer-price': {
      t: 'Price / maths layer',
      d: `Pure arithmetic on the odds — no football opinion. It <b>de-vigs</b> each book and averages to a
          consensus fair probability, then computes <b>edge</b> (fair − price-implied) and
          <b>EV</b> (fair × price − 1), assigns a verdict — <b>Bet Now</b> (EV ≥ +2% and outside the
          longshot-noise band), <b>Lean</b> (≥ 0), <b>Track Price</b> (≥ −3%), <b>Avoid</b> below — and
          measures book-vs-prediction-market divergence. It produces every number on the site.`,
      m: '_devig() · edge/EV · verdictMeta() · edgeReliable()',
    },
    'layer-analyst': {
      t: 'Analyst / football layer — Claude Sonnet',
      d: `A grounded football read per match, using <b>only</b> the sourced inputs (rank, squad, WC-led
          form, injuries, weather — and the prices as context only). It is forbidden from inventing
          stats, managers or formations, and from judging value; it ranks outcomes by football logic and
          returns <b>up to 3 recommended bets</b>. Cached 7 days and re-run when form or injuries change.
          Calls run one-at-a-time to stay under the API rate limit.`,
      m: 'claude-sonnet-4-6 · recommended_bets · CACHE_TTL=7d · INTEL_WORKERS=1',
    },
    'out-today': {
      t: '📅 Today',
      d: `The soonest matchday at a glance — each fixture with the analyst's read and any recommended
          bets, and a flag on bets you've already logged. Shows <b>both</b> layers side by side.`,
      m: 'driven by: maths + analyst',
    },
    'out-bestpicks': {
      t: '★ Best Bets · Picks',
      d: `The only <b>two-gate</b> section. A pick appears <b>only if</b> (1) the analyst explicitly
          recommended that exact outcome <b>and</b> (2) the price is fair-or-better. Graded into tiers
          (<b>Strong / Solid / Speculative</b>) and given a verdict. This is where the maths and the
          football have to agree.`,
      m: 'gated: analyst recommendation + price · _analyst_confirms()',
    },
    'out-writeups': {
      t: '★ Best Bets · Analyst Writeups',
      d: `The analyst's full written read per match — form, key absences, conditions, tactical matchup,
          goals view and summary. <b>Analyst layer only</b>; there is no price gate here.`,
      m: 'driven by: analyst',
    },
    'out-singles': {
      t: '📊 Markets · Value Singles (+EV)',
      d: `Individual bets ranked by edge / EV from the price layer, filterable by confidence and market.
          Carries the <b>★ both-agree</b> badge when the analyst also recommends that outcome — the
          maths leads, the analyst confirms.`,
      m: 'driven by: maths (+EV) · analyst confirms (★)',
    },
    'out-accas': {
      t: '📊 Markets · Accumulators (−EV)',
      d: `Slips built by the <b>maths layer</b>: high-probability legs (one per match), priced at a single
          bookmaker, ranked by chance of landing, with honest negative EV. The analyst does <b>not</b>
          pick the legs — but a leg now shows a <b>⚠ analyst-disagrees</b> flag when the analyst
          recommends a mutually-exclusive outcome for that match. The flag is advisory only; the leg
          stays in the slip.`,
      m: 'driven by: maths picks legs · analyst = context + ⚠ soft flag · _build_parlays()',
    },
    'out-builder': {
      t: '📊 Markets · Acca Builder',
      d: `Build-your-own slip: pick any legs and the maths layer prices the combination at a single book
          and shows the (negative) EV.`,
      m: 'driven by: maths',
    },
    'out-divergence': {
      t: '📊 Markets · Market Divergence',
      d: `Every match ranked by the gap between the book fair probability and the prediction-market
          consensus. <span style="color:var(--green)">Green</span> = the markets rate it higher than the
          books (possible value); <span style="color:var(--red)">red</span> = books shorter (possible
          trap). <b>Maths only.</b>`,
      m: 'driven by: maths (book vs prediction-market gap)',
    },
    'out-mybets': {
      t: '📒 My Bets',
      d: `Your private journal, saved in your browser. Logs each bet's odds, stake and book, and
          <b>snapshots the model's fair probability + EV at the moment you bet</b> — the groundwork for
          closing-line-value review. Not driven by either layer; it's your record.`,
      m: 'localStorage · records fair_prob + EV at bet time (CLV groundwork)',
    },
    // ---- relationship chips ----
    'link-devig': {
      t: 'Link · De-vig (odds → fair probability)',
      d: `Bookmaker odds bake in a margin, so the implied probabilities of Home/Draw/Away sum to more than
          100%. Each book is de-vigged <b>proportionally</b>, then averaged across books → the consensus
          <b>fair probability</b>. "Fair" means the market average, <b>not</b> the truth — beating it just
          means you got a better-than-consensus price.`,
      m: '_devig() · proportional, then averaged across books',
    },
    'link-confirm': {
      t: 'Link · Prediction-market cross-check (★)',
      d: `A single's edge is <b>confirmed</b> when Kalshi/Polymarket also rate the outcome higher than the
          books (the ★ both-agree signal and a confidence lift), and <b>tempered</b> when they disagree
          against you — the card says the "edge" is probably the model being wrong.`,
      m: 'pm_confirms / pm_gap · analystConfirms() ★',
    },
    'link-context': {
      t: 'Link · Prices → analyst (context only)',
      d: `The analyst is shown the book prices as background, but is <b>explicitly told not to judge
          value</b> or crown a "best bet" from them. That keeps the football read independent of the
          maths — which is the whole point: two independent views can then genuinely <b>agree (★)</b> or
          <b>disagree (⚠)</b>.`,
      m: 'price_notes in _build_prompt() — "stay in your lane" system prompt',
    },
    'link-gate': {
      t: 'Link · Analyst → Best Bets (two gates)',
      d: `Best Bets requires <b>both</b> gates: the analyst recommended the outcome (gate 1) <b>and</b> the
          price is fair-or-better (gate 2). This is the <b>only</b> place the analyst hard-gates what
          appears on the site.`,
      m: '_analyst_confirms() + price check · debug_sensible()',
    },
    'link-flag': {
      t: 'Link · Analyst → Accumulators (⚠ disagrees)',
      d: `New in this work: an acca leg is flagged <b>⚠ analyst disagrees</b> when the analyst recommends
          an outcome that is <b>mutually exclusive</b> with that leg (e.g. backing the draw against a
          team you've put on a −1.5 handicap). It fires only on a genuine contradiction, never on mere
          absence of endorsement — and it's <b>advisory</b>: the leg is still chosen by maths and stays
          in the slip.`,
      m: 'analystDisagrees() (client) · soft flag, no veto',
    },
  };

  // ---- SVG map -------------------------------------------------------------
  const G = 'var(--green-dim)', V = 'var(--violet)', L = 'var(--line-2)';
  const DG = 'var(--green)', DV = 'var(--violet)', DGREY = 'var(--tx-3)', AMBER = 'var(--amber)';

  function node(id, x, y, w, h, title, sub, stroke, sw, dots) {
    const cx = x + w / 2;
    const titleY = sub ? y + h / 2 - 4 : y + h / 2 + 4;
    const subEl = sub ? `<text x="${cx}" y="${y + h / 2 + 12}" text-anchor="middle" font-size="9" fill="var(--tx-3)">${sub}</text>` : '';
    const dotsEl = (dots || []).map((c, i) =>
      `<circle cx="${x + 13 + i * 13}" cy="${y + h - 11}" r="3.4" fill="${c}"/>`).join('');
    return `<g class="md-node" data-id="${id}" tabindex="0" role="button" aria-label="${title}">
      <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="7" fill="var(--bg-1)" stroke="${stroke}" stroke-width="${sw || 1.4}"/>
      <text x="${cx}" y="${titleY}" text-anchor="middle" font-size="11" font-weight="600" fill="var(--tx-1)">${title}</text>
      ${subEl}${dotsEl}
    </g>`;
  }

  function buildSvg() {
    return `<svg viewBox="0 0 860 360" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Clickable data-flow map">
      <text x="16" y="10" font-size="9.5" font-weight="700" fill="var(--tx-3)">DATA SOURCES</text>
      ${node('src-odds', 16, 16, 128, 44, 'Bookmaker odds', 'The Odds API', G)}
      ${node('src-pm', 154, 16, 128, 44, 'Kalshi · Poly', 'prediction mkts', G)}
      ${node('src-form', 292, 16, 128, 44, 'Recent form ●', 'last-8 · WC-aware', V)}
      ${node('src-injuries', 430, 16, 128, 44, 'Injuries', 'web digest · 12h', V)}
      ${node('src-weather', 568, 16, 128, 44, 'Weather · venue', 'Open-Meteo', V)}
      ${node('src-squad', 706, 16, 128, 44, 'Squad · rank', 'static FIFA data', V)}

      <line x1="80"  y1="60" x2="120" y2="90" stroke="${DG}" stroke-width="1" opacity=".5"/>
      <line x1="218" y1="60" x2="160" y2="90" stroke="${DG}" stroke-width="1" opacity=".5"/>
      <line x1="356" y1="60" x2="560" y2="90" stroke="${DV}" stroke-width="1" opacity=".5"/>
      <line x1="494" y1="60" x2="600" y2="90" stroke="${DV}" stroke-width="1" opacity=".5"/>
      <line x1="632" y1="60" x2="650" y2="90" stroke="${DV}" stroke-width="1" opacity=".5"/>
      <line x1="770" y1="60" x2="700" y2="90" stroke="${DV}" stroke-width="1" opacity=".5"/>

      ${node('layer-price', 16, 92, 400, 80, 'PRICE · MATHS LAYER', 'de-vig · edge · EV · divergence', G, 2)}
      ${node('layer-analyst', 444, 92, 400, 80, 'ANALYST · FOOTBALL LAYER', 'Claude Sonnet · grounded read', V, 2)}
      <line x1="416" y1="132" x2="444" y2="132" stroke="var(--tx-3)" stroke-width="1" stroke-dasharray="3 3"/>

      <text x="16" y="190" font-size="9.5" font-weight="700" fill="var(--tx-3)">WHAT EACH TAB SHOWS — dots: ● maths ● analyst ● neither</text>
      ${node('out-today', 16, 198, 196, 58, '📅 Today', null, L, 1.4, [DG, DV])}
      ${node('out-bestpicks', 226, 198, 196, 58, '★ Best Bets · Picks', null, V, 2.2, [DG, DV])}
      ${node('out-writeups', 436, 198, 196, 58, '★ Analyst Writeups', null, L, 1.4, [DV])}
      ${node('out-singles', 646, 198, 196, 58, '📊 Value Singles', null, L, 1.4, [DG, DV])}
      ${node('out-accas', 16, 268, 196, 58, '📊 Accumulators ⚠', null, L, 1.4, [DG, AMBER])}
      ${node('out-builder', 226, 268, 196, 58, '📊 Acca Builder', null, L, 1.4, [DG])}
      ${node('out-divergence', 436, 268, 196, 58, '📊 Market Divergence', null, L, 1.4, [DG])}
      ${node('out-mybets', 646, 268, 196, 58, '📒 My Bets', null, L, 1.4, [DGREY])}
    </svg>`;
  }

  const CHIPS = [
    ['link-devig', 'De-vig'],
    ['link-confirm', 'PM cross-check ★'],
    ['link-context', 'Prices → analyst (context)'],
    ['link-gate', 'Best Bets two-gate'],
    ['link-flag', 'Acca ⚠ disagrees'],
  ];

  function render(id) {
    const info = INFO[id];
    const detail = document.getElementById('md-detail');
    if (!info || !detail) return;
    detail.innerHTML = `<h4>${info.t}</h4><p>${info.d}</p>`
      + (info.m ? `<span class="md-meta">In the code: ${info.m}</span>` : '');
    document.querySelectorAll('#md-explorer .md-node, #md-explorer .md-chip')
      .forEach(el => el.classList.toggle('active', el.dataset.id === id));
  }

  function init() {
    const exp = document.getElementById('md-explorer');
    if (!exp || exp.dataset.ready) return;
    exp.dataset.ready = '1';

    document.getElementById('md-stage').innerHTML = buildSvg();
    document.getElementById('md-links').innerHTML = CHIPS.map(
      ([id, label]) => `<button class="md-chip" data-id="${id}" type="button">${label}</button>`
    ).join('');

    exp.addEventListener('click', e => {
      const el = e.target.closest('[data-id]');
      if (el) render(el.dataset.id);
    });
    exp.addEventListener('keydown', e => {
      if (e.key !== 'Enter' && e.key !== ' ') return;
      const el = e.target.closest('.md-node[data-id]');
      if (el) { e.preventDefault(); render(el.dataset.id); }
    });

    render('layer-analyst');   // open on the layer this work upgraded
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
