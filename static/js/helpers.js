/* ============================================================
   helpers.js — shared state + pure helpers (no DOM rendering)
   Loaded first; everything is intentionally global (classic
   scripts, no build step) so inline handlers keep working.
   ============================================================ */

// ---- shared state ----
let allMatches    = [];
let allSingles    = [];
let allParlays    = [];
let allIntel      = {};   // {match_label: analyst intel}
let allBookmakers = [];
let threshold     = 0;    // divergence min-gap filter
let betsSubTab    = 'singles';   // 'singles' | 'parlays'
let accaRisk      = 'balanced';  // 'banker' | 'balanced' | 'punchy'
let accaGuard     = true;
let _accaBusy     = false;
let accaMarkets   = [];
let accaRound     = '';
let roundsAvailable = [];
let accaSort      = 'chance';    // 'chance' | 'return'
let _injuriesLoaded = false;
let _reanalysing    = new Set(); // match labels being re-analysed (injury news)
let _intelPollTimer = null;
let _dataLoaded     = false;     // first successful /api load completed (distinguishes "loading" from "empty")

// Shared empty state for "the odds feed returned nothing"
function noOddsState() {
  return emptyState('📡', 'No odds available right now',
    `The bookmakers' feed returned no priced matches — books may not have posted these markets yet, or the odds service may be down. <button class="linklike" onclick="loadData(true)">Try a refresh</button> or check back shortly.`);
}

// ---- escaping (XSS hardening — applied to ALL external-origin text:
// analyst/LLM output, web-sourced injury digest, team & bookmaker names
// from third-party APIs). Do not regress this. ----
function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Title-case a single team/outcome name: "south korea" -> "South Korea".
// Returns UNESCAPED text — pass through esc() when interpolating.
function titleCase(name) {
  return String(name || '').split(' ')
    .map(w => (w === 'vs' || w === 'v') ? w : w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

// Title-cased, escaped match label ("Brazil vs South Korea") — safe for innerHTML.
function fmtLabel(label) { return esc(titleCase(label)); }

// Title-cased, escaped pick/outcome name — safe for innerHTML.
// Handles "draw", team names, "Over 2.5", "Germany (-1.5)".
function fmtPick(outcome) { return esc(titleCase(outcome)); }

// ---- money / EV ----
// True expected value per unit stake: fair probability × decimal price − 1.
// NOT the probability-point "edge" (fair − 1/price). Returns % or null.
function evPct(fairProb, price) {
  if (fairProb == null || !price || price <= 0) return null;
  return (fairProb * price - 1) * 100;
}

// The primary money metric: "EV +€0.23 per €10".
function evMoneyHTML(fairProb, price, stake, size = '') {
  const ev = evPct(fairProb, price);
  if (ev == null) return '<span style="color:var(--tx-4)">EV —</span>';
  const amt = ev / 100 * stake;
  const cls = ev >= 0 ? 'pos' : 'neg';
  return `<span class="ev-num ${cls} help" ${size ? `style="font-size:${size}"` : ''}`
    + ` title="Expected value: the average profit/loss of this bet per €${stake} staked if it were repeated many times at the model's fair probability. = (fair prob × price − 1) × stake.">`
    + `${amt >= 0 ? '+' : '−'}€${Math.abs(amt).toFixed(2)} <small>per €${stake} (${ev >= 0 ? '+' : ''}${ev.toFixed(1)}%)</small></span>`;
}

function eur(val) { return '€' + val.toFixed(2); }

function fmt(iso) {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
      + ' ' + d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  } catch { return iso; }
}

function kickoffCountdown(iso) {
  if (!iso) return '';
  const now = new Date();
  const ko  = new Date(iso);
  if (ko - now < 0) return 'In progress / finished';
  const time = ko.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' });
  const nowDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const koDay  = new Date(ko.getFullYear(), ko.getMonth(), ko.getDate());
  const daysDiff = Math.round((koDay - nowDay) / 86400000);
  if (daysDiff === 0) return `<span style="color:#f0883e;font-weight:600">Today ${time}</span>`;
  if (daysDiff === 1) return `<span style="color:var(--amber);font-weight:600">Tomorrow ${time}</span>`;
  return fmt(iso);
}

function intelAge(intel) {
  const ca = intel?.cached_at;
  if (!ca) return '';
  const h = (Date.now() - ca * 1000) / 3600000;
  if (h < 1)  return 'analysed just now';
  if (h < 24) return `analysed ${Math.round(h)}h ago`;
  return `analysed ${Math.round(h / 24)}d ago`;
}

// "2240.0m" -> "2,240m" anywhere inside free text (weather headlines etc.)
function fmtAltitudeText(text) {
  return String(text || '').replace(/\b(\d{3,5})(?:\.0)?m\b/g, (_, n) => parseInt(n, 10).toLocaleString() + 'm');
}

// ---- team-name normalisation (mirror of Python prediction_markets.normalize_team) ----
const _TEAM_ALIASES = {
  "usa": "united states", "us": "united states", "u s a": "united states",
  "korea republic": "south korea", "korea": "south korea",
  "republic of korea": "south korea",
  "czech republic": "czechia",
  "cote divoire": "ivory coast", "cote d ivoire": "ivory coast",
  "ivory coast": "ivory coast",
  "bosnia and herzegovina": "bosnia", "bosnia herzegovina": "bosnia",
  "bosnia-herzegovina": "bosnia",
  "cabo verde": "cape verde", "cape verde": "cape verde",
  "turkey": "turkiye", "ir iran": "iran",
  "curacao": "curacao",
  "congo dr": "dr congo", "democratic republic of congo": "dr congo",
  "democratic republic congo": "dr congo",
};
function normalizeTeam(name) {
  if (!name) return "";
  let n = name.normalize("NFKD").replace(/\p{M}/gu, "");
  n = n.replace(/[^a-z0-9 ]/gi, " ").toLowerCase().replace(/\s+/g, " ").trim();
  return _TEAM_ALIASES[n] ?? n;
}
function normalizeMatchLabel(label) {
  return (label || '').split(' vs ').map(normalizeTeam).join(' vs ');
}

// The intel cache stores each match under BOTH its display label and a
// normalised lowercase label. Return deduped [label, intel] pairs, preferring
// the display-cased key.
function intelEntries() {
  const byNorm = new Map();
  for (const [label, intel] of Object.entries(allIntel || {})) {
    const norm = normalizeMatchLabel(label.toLowerCase());
    const cur = byNorm.get(norm);
    // Prefer a label with any uppercase (the display form)
    if (!cur || (/[A-Z]/.test(label) && !/[A-Z]/.test(cur[0]))) byNorm.set(norm, [label, intel]);
  }
  return [...byNorm.values()];
}

// ---- analyst confirmation (same-market comparison only) ----
function analystConfirms(single, intel) {
  if (!intel) return null;
  const recs = intel.recommended_bets;
  if (!recs || !recs.length) return null;
  const sMarket  = single.market;
  const sOutcome = single.outcome.toLowerCase();
  const parts    = single.match.includes(' vs ') ? single.match.split(' vs ') : ['', ''];
  const homeName = normalizeTeam(parts[0]);
  const awayName = normalizeTeam(parts[1]);

  const isH2hRec     = ao => ao === 'home_win' || ao === 'away_win' || ao === 'draw';
  const isTotalsRec  = ao => ao.startsWith('over') || ao.startsWith('under');
  const isSpreadsRec = ao => ao.startsWith('home_-') || ao.startsWith('home_+') || ao.startsWith('away_-') || ao.startsWith('away_+');
  const inSameMarket = ao =>
    (sMarket === 'h2h'     && isH2hRec(ao))    ||
    (sMarket === 'totals'  && isTotalsRec(ao)) ||
    (sMarket === 'spreads' && isSpreadsRec(ao));

  const sameMarketRecs = recs.filter(rb => inSameMarket((rb.outcome || '').toLowerCase().replace(/ /g, '_')));
  if (!sameMarketRecs.length) return null;

  for (const rb of sameMarketRecs) {
    const ao = (rb.outcome || '').toLowerCase().replace(/ /g, '_');
    if (sMarket === 'h2h') {
      if (ao === 'home_win' && sOutcome === homeName) return true;
      if (ao === 'away_win' && sOutcome === awayName) return true;
      if (ao === 'draw' && sOutcome === 'draw') return true;
    } else if (sMarket === 'totals') {
      if (ao.startsWith('over')  && sOutcome.includes('over'))  return true;
      if (ao.startsWith('under') && sOutcome.includes('under')) return true;
    } else if (sMarket === 'spreads') {
      if (ao.startsWith('home_')) {
        const pt = ao.split('home_')[1];
        if (sOutcome.includes(homeName) && sOutcome.includes(pt)) return true;
      }
      if (ao.startsWith('away_')) {
        const pt = ao.split('away_')[1];
        if (sOutcome.includes(awayName) && sOutcome.includes(pt)) return true;
      }
    }
  }
  return false;
}

// A small edge on a long-priced outcome is within the de-vig's own margin of
// error — noise, not value. Require the edge to grow with the price.
function edgeReliable(s) {
  return s.edge >= (0.5 + 0.3 * ((s.best_price || 1) - 1));
}

// ---- verdict — THE dominant element on every bet card ----
// Runs on TRUE EV (fair × price − 1), gated by the longshot-noise check.
// Thresholds: ≥+2% EV and reliable = Bet Now; ≥0% = Lean; ≥−3% = Track; else Avoid.
function verdictMeta(s) {
  const ev = evPct(s.fair_prob, s.best_price);
  if (ev == null) return { cls: 'wait', label: 'Awaiting Price', ico: '…' };
  const reliable = s.edge != null && edgeReliable(s);
  if (ev >= 2 && reliable) return { cls: 'bet',   label: 'Bet Now',        ico: '🎯' };
  if (ev >= 0)             return { cls: 'lean',  label: s.rb_strength === 'strong' ? 'Lean (Analyst Strong)' : 'Lean Only', ico: '→' };
  if (ev >= -3)            return { cls: 'track', label: 'Track Price',    ico: '⏳' };
  return { cls: 'avoid', label: 'Avoid at Price', ico: '⚠' };
}
function verdictBadge(s) {
  const v = verdictMeta(s);
  return `<span class="verdict verdict--${v.cls}">${v.ico} ${v.label}</span>`;
}

// ---- weather flag ----
function weatherFlagHTML(item) {
  const w = item.weather;
  if (!w) return '';
  const o   = (item.outcome || '').toLowerCase();
  const fav = (w.favours || '').toLowerCase();
  const dis = (w.disfavours || '').toLowerCase();
  const hits = (name) => name && (name.includes(o) || o.includes(name));
  let cls = 'wflag neutral', prefix = '';
  if (hits(fav))      { cls = 'wflag good'; prefix = '✓ conditions favour this — '; }
  else if (hits(dis)) { cls = 'wflag warn'; prefix = '⚠ conditions against this — '; }
  else if (w.goals_lean === 'under' && o.includes('under')) { cls = 'wflag good'; prefix = '✓ heat suits Under — '; }
  else if (w.goals_lean === 'under' && o.includes('over'))  { cls = 'wflag warn'; prefix = '⚠ heat works against Over — '; }
  else if (w.goals_lean === 'over'  && o.includes('over'))  { cls = 'wflag good'; prefix = '✓ altitude suits Over — '; }
  else if (w.goals_lean === 'over'  && o.includes('under')) { cls = 'wflag warn'; prefix = '⚠ altitude works against Under — '; }
  const srcTag = w.source === 'forecast'
    ? `<span style="color:var(--green);font-weight:600"> · live forecast${w.days_out != null ? ' ' + esc(w.days_out) + 'd out' : ''}</span>`
    : `<span style="color:var(--tx-3)"> · historical avg (no live forecast)</span>`;
  const tip = esc((w.detail || '') + (w.source === 'forecast'
    ? '  [Live Open-Meteo forecast.]'
    : '  [Historical climate normal — live forecast unavailable, so an abnormal forecast would NOT be reflected here.]'));
  return `<div class="${cls}" title="${tip}">${esc(w.emoji)} ${prefix}${esc(fmtAltitudeText(w.headline))}${srcTag}</div>`;
}

// ---- collapsible explainer banners (seen-state in localStorage 'wc26_seen') ----
function hasSeen(key) {
  try { return !!JSON.parse(localStorage.getItem('wc26_seen') || '{}')[key]; } catch { return false; }
}
function markSeen(key) {
  try {
    const s = JSON.parse(localStorage.getItem('wc26_seen') || '{}');
    s[key] = true;
    localStorage.setItem('wc26_seen', JSON.stringify(s));
  } catch {}
}
function collapsibleBanner(key, shortText, fullHTML, tone = '') {
  const safeShort = shortText.replace(/"/g, '&quot;');
  if (hasSeen(key)) return `<div class="note note--mini">${shortText}</div>`;
  return `<div class="note ${tone}" data-banner-key="${key}" data-short="${safeShort}" style="padding-right:34px">
    ${fullHTML}
    <button class="note__close" onclick="dismissBanner(this)" title="Got it — hide this">×</button>
  </div>`;
}
function dismissBanner(btn) {
  const b = btn.closest('[data-banner-key]');
  markSeen(b.dataset.bannerKey);
  b.className = 'note note--mini';
  b.removeAttribute('style');
  b.innerHTML = b.dataset.short;
}

// ---- placed-bets journal storage (localStorage 'wc26_placed_bets' — key and
// shape unchanged from v1, existing user data loads as-is) ----
const _BETS_KEY = 'wc26_placed_bets';
function loadPlacedBets() {
  try {
    const raw = JSON.parse(localStorage.getItem(_BETS_KEY) || '[]');
    return Array.isArray(raw) ? raw : [];
  } catch { return []; }
}
function savePlacedBets(bets) { localStorage.setItem(_BETS_KEY, JSON.stringify(bets)); }

// ---- bookmaker helpers ----
const BOOK_URLS = {
  'Paddy Power':        'https://www.paddypower.com',
  'Betfair':            'https://www.betfair.com/sport/football',
  'Betfair Sportsbook': 'https://www.betfair.com/sport/football',
  'Betfair Exchange':   'https://www.betfair.com/exchange',
  'Bet365':             'https://www.bet365.com',
  'Ladbrokes':          'https://www.ladbrokes.com',
  'BoyleSports':        'https://www.boylesports.com',
  'William Hill':       'https://www.williamhill.com',
  'Coral':              'https://www.coral.co.uk',
  'Sky Bet':            'https://www.skybet.com',
  'BetVictor':          'https://www.betvictor.com',
};

function chosenBook()  { return document.getElementById('book-select')?.value || 'best'; }
function chosenStake() { return parseFloat(document.getElementById('stake-input')?.value) || 10; }
function sensibleStake() { return parseFloat(document.getElementById('sensible-stake-input')?.value) || 10; }
function picksChosenBook()  { return document.getElementById('picks-book-select')?.value || 'best'; }
function picksChosenStake() { return parseFloat(document.getElementById('picks-stake-input')?.value) || 10; }

// Price for a selection at the chosen bookmaker (falls back to best price).
function priceForBook(s, book) {
  if (book === 'best') return { price: s.best_price, bookLabel: s.best_book, fallback: false };
  const p = s.per_book?.[book];
  if (p) return { price: p, bookLabel: book, fallback: false };
  return { price: s.best_price, bookLabel: s.best_book, fallback: true };
}

// ---- skeleton / empty-state building blocks ----
function skeletonCards(n = 3) {
  const one = `<div class="skel-card">
    <div style="display:flex;justify-content:space-between;gap:12px">
      <div style="flex:1;display:grid;gap:8px"><div class="skel skel-line w60"></div><div class="skel skel-line w40"></div></div>
      <div class="skel skel-pill"></div>
    </div>
    <div class="skel skel-line w80"></div>
  </div>`;
  return Array.from({ length: n }, () => one).join('');
}

function emptyState(ico, title, subHTML) {
  return `<div class="empty-state">
    <div class="empty-ico">${ico}</div>
    <div class="empty-title">${title}</div>
    ${subHTML ? `<div class="empty-sub">${subHTML}</div>` : ''}
  </div>`;
}

// ---- full analyst research block (used on value-singles cards) ----
function intelHTML(intel) {
  if (!intel) return `<div class="intel-loading"><div class="spinner"></div> Analyst researching form, conditions &amp; injuries…</div>`;

  const rec  = intel.recommendation || {};
  const cond = intel.conditions || {};
  const conf = intel.intel_confidence || 'low';
  const confColour = conf === 'high' ? 'var(--green)' : conf === 'medium' ? 'var(--amber)' : 'var(--tx-3)';

  const altWarn = cond.altitude_m > 800
    ? `<span style="color:var(--red);font-weight:700"> ALTITUDE ${Math.round(cond.altitude_m).toLocaleString()}m</span>` : '';
  const condLine = cond.city
    ? `<div><span class="lbl">Venue:</span> <strong>${esc(cond.city)}</strong>${altWarn} · <span class="lbl">Local KO:</span> <strong>${esc(cond.local_kickoff)}</strong> · ${esc(cond.avg_high_c)}°C feels ${esc(cond.feels_like_c)}°C, ${esc(cond.humidity_pct)}% humidity</div>`
    : '';

  const strengthColour = rec.strength === 'strong' ? 'var(--green)' : rec.strength === 'moderate' ? 'var(--amber)' : 'var(--tx-3)';
  const recOutcome = rec.outcome || '';

  return `<div class="intel-block">
    <div class="intel-block__head">
      <span>ANALYST RESEARCH</span>
      <span style="font-weight:400;color:${confColour}">analyst confidence: ${esc(conf)}</span>
    </div>
    <div class="intel-block__body">
      ${condLine}
      <div><span class="lbl">Conditions impact:</span> ${esc(intel.conditions_impact || '—')}</div>
      <div><span class="lbl">Home form:</span> ${esc(intel.home_form || '—')}</div>
      <div><span class="lbl">Away form:</span> ${esc(intel.away_form || '—')}</div>
      <div><span class="lbl">Tactical matchup:</span> ${esc(intel.tactical_matchup || '—')}</div>
      <div><span class="lbl">Goals:</span> ${esc(intel.goals_assessment || '—')}</div>
      <div><span class="lbl">Market read:</span> ${esc(intel.market_read || '—')}</div>
      ${intel.key_absences ? `<div><span class="lbl">Absences:</span> ${esc(intel.key_absences)}</div>` : ''}
      <div class="intel-rec">
        <div style="font-size:var(--fs-xs);color:var(--tx-4);margin-bottom:4px">ANALYST RECOMMENDATION</div>
        <div style="font-weight:700;color:${strengthColour};margin-bottom:4px">${esc(titleCase(recOutcome.replace(/_/g, ' ')))} <span style="font-weight:400;font-size:var(--fs-xs)">(${esc(rec.strength || '—')})</span></div>
        <div style="color:var(--tx-2);line-height:1.5">${esc(rec.reasoning || '—')}</div>
        ${rec.watch_out ? `<div style="margin-top:6px;color:var(--amber);font-size:var(--fs-xs)">Watch out: ${esc(rec.watch_out)}</div>` : ''}
      </div>
      ${intel.overall_summary ? `<div style="color:var(--tx-2);line-height:1.6;font-style:italic">${esc(intel.overall_summary)}</div>` : ''}
      ${intel.knowledge_caveat ? `<div style="font-size:var(--fs-xs);color:var(--tx-4);border-top:1px solid var(--line-1);padding-top:6px">Data caveat: ${esc(intel.knowledge_caveat)}</div>` : ''}
    </div>
  </div>`;
}
