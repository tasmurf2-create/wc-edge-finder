/* Methodology — interactive pipeline explorer.
   A clickable map of the site's data flow. Every description below is grounded in
   the actual code (server.py / odds.py / club_intel.py / leagues.py and the
   frontend), not a guess. Click a box or a relationship chip to see what
   it is and how it links to the rest. */
(function () {
  'use strict';

  // ---- accurate per-node content -----------------------------------------
  const INFO = {
    'src-odds': {
      t: 'Bookmaker odds — The Odds API',
      d: `Live decimal odds for every fixture in the <b>Premier League</b>, <b>La Liga</b> and the
          <b>Scottish Premiership</b>, covering three markets: <b>match result (1X2)</b>,
          <b>Over/Under</b> and <b>Asian handicap</b>. Filtered to the six Irish-accessible books —
          Paddy Power, Betfair, Bet365, BoyleSports, Ladbrokes, William Hill. This is the backbone:
          every fair-probability, edge and EV number on the site derives from it.`,
      m: 'odds.py fetch_all() · leagues.py · BOOKMAKER_WHITELIST',
    },
    'src-sharp': {
      t: 'Sharp line — Pinnacle & exchanges',
      d: `The same feed also carries the <b>sharpest</b> prices in the market. Pinnacle and the betting
          exchanges run ~2% margins (against 5–8% at a high-street book), take large stakes and move first
          on real money, so their de-vigged line is the closest available proxy for a true probability.
          Used to <b>confirm or temper</b> every edge: consensus above the sharp line means the sharp side
          agrees the outcome is underpriced. An independent cross-check, not a price you bet here.`,
      m: '_sharp_h2h_fair() · SHARP_BOOKS · sharp_gap',
    },
    'src-research': {
      t: 'Club research — one web search per match',
      d: `For each fixture, <b>one web search</b> (run on <b>Claude Haiku</b>, restricted to that league's
          trusted sources — Sky Sports, ESPN, the official league sites, FotMob) gathering recent form,
          league position, confirmed team news and head-to-head. Cached 6 hours. This is the analyst's
          only factual grounding — clubs have no fixed squad list or ranking to fall back on.`,
      m: 'club_intel.get_research() · leagues.domains_for() · RESEARCH_TTL=6h',
    },
    'layer-price': {
      t: 'Price / maths layer',
      d: `Pure arithmetic on the odds — no football opinion. It <b>de-vigs</b> each book and averages to a
          consensus fair probability, then computes <b>edge</b> (fair − price-implied) and
          <b>EV</b> (fair × price − 1), assigns a verdict — <b>Bet Now</b> (EV ≥ +2% and outside the
          longshot-noise band), <b>Lean</b> (≥ 0), <b>Track Price</b> (≥ −3%), <b>Avoid</b> below — and
          measures the gap to the sharp line. It produces every number on the site.`,
      m: '_devig() · edge/EV · verdictMeta() · edgeReliable() · sharp_gap',
    },
    'layer-analyst': {
      t: 'Analyst / football layer — Claude Sonnet',
      d: `A grounded football read per match, written from the web research and <b>nothing else</b>
          (prices are supplied as context only). It may not invent a scoreline, table position or statistic,
          may not name a manager it is unsure of, and may not treat "no injuries found" as "squad fit".
          It never judges value — it ranks outcomes by football logic and returns <b>up to 3 recommended
          bets</b>. Cached 12 hours. Calls run one-at-a-time to stay under the API rate limit.`,
      m: 'claude-sonnet-4-6 · recommended_bets · CACHE_TTL=12h · INTEL_WORKERS=1',
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
      t: '📊 Markets · Sharp Line',
      d: `Every match ranked by the gap between the soft-book consensus and the <b>sharpest</b> line in the
          market. <span style="color:var(--green)">Green</span> = the sharp book rates the outcome higher
          than the consensus (supportive of value); <span style="color:var(--red)">red</span> = the sharp
          book is shorter (treat the edge with caution). <b>Maths only.</b>`,
      m: 'driven by: maths (consensus vs sharp-book gap)',
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
      t: 'Link · Sharp-line cross-check (★)',
      d: `A single's edge is <b>confirmed</b> when the sharpest book also rates the outcome at least as
          likely as the consensus does (the ★ both-agree signal and a confidence lift), and
          <b>tempered</b> when the sharp line is shorter — the card says the "edge" is probably the model
          being wrong rather than a real opportunity.`,
      m: 'sharp_confirms / sharp_gap · analystConfirms() ★',
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
      ${node('src-odds', 16, 16, 260, 44, 'Bookmaker odds', '3 leagues · The Odds API', G)}
      ${node('src-sharp', 300, 16, 260, 44, 'Sharp line', 'Pinnacle · exchanges', G)}
      ${node('src-research', 584, 16, 260, 44, 'Club research', 'web search · per match', V)}

      <line x1="146" y1="60" x2="180" y2="90" stroke="${DG}" stroke-width="1" opacity=".5"/>
      <line x1="430" y1="60" x2="300" y2="90" stroke="${DG}" stroke-width="1" opacity=".5"/>
      <line x1="714" y1="60" x2="650" y2="90" stroke="${DV}" stroke-width="1" opacity=".5"/>

      ${node('layer-price', 16, 92, 400, 80, 'PRICE · MATHS LAYER', 'de-vig · edge · EV · sharp gap', G, 2)}
      ${node('layer-analyst', 444, 92, 400, 80, 'ANALYST · FOOTBALL LAYER', 'Claude Sonnet · grounded read', V, 2)}
      <line x1="416" y1="132" x2="444" y2="132" stroke="var(--tx-3)" stroke-width="1" stroke-dasharray="3 3"/>

      <text x="16" y="190" font-size="9.5" font-weight="700" fill="var(--tx-3)">WHAT EACH TAB SHOWS — dots: ● maths ● analyst ● neither</text>
      ${node('out-today', 16, 198, 196, 58, '📅 Today', null, L, 1.4, [DG, DV])}
      ${node('out-bestpicks', 226, 198, 196, 58, '★ Best Bets · Picks', null, V, 2.2, [DG, DV])}
      ${node('out-writeups', 436, 198, 196, 58, '★ Analyst Writeups', null, L, 1.4, [DV])}
      ${node('out-singles', 646, 198, 196, 58, '📊 Value Singles', null, L, 1.4, [DG, DV])}
      ${node('out-accas', 16, 268, 196, 58, '📊 Accumulators ⚠', null, L, 1.4, [DG, AMBER])}
      ${node('out-builder', 226, 268, 196, 58, '📊 Acca Builder', null, L, 1.4, [DG])}
      ${node('out-divergence', 436, 268, 196, 58, '📊 Sharp Line', null, L, 1.4, [DG])}
      ${node('out-mybets', 646, 268, 196, 58, '📒 My Bets', null, L, 1.4, [DGREY])}
    </svg>`;
  }

  const CHIPS = [
    ['link-devig', 'De-vig'],
    ['link-confirm', 'Sharp cross-check ★'],
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
