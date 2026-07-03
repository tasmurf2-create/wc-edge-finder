/* ============================================================
   views-gaa.js — the consolidated GAA tab.

   One rich card per All-Ireland game: Paddy Power (soft) vs the
   Betfair Exchange fair line (sharp) with computed edge, plus a
   Claude analyst read (form, absences, tactical, recommendation).

   Self-contained: its own fetch (/api/gaa) + render, independent
   of the soccer pipeline. Reuses helpers.js (esc, titleCase,
   skeletonCards, emptyState, kickoffCountdown).
   ============================================================ */

let _gaaData = null;
let _gaaPollTimer = null;
let _gaaLoading = false;

async function loadGaa(force = false) {
  const panel = document.getElementById('gaa-panel');
  if (!panel) return;
  if (_gaaData && !force) { renderGaa(); return; }   // already have it
  if (_gaaLoading) return;
  _gaaLoading = true;
  panel.innerHTML = skeletonCards(3);

  try {
    const res = await fetch('/api/gaa');
    _gaaData = await res.json();
    renderGaa();

    // analyst runs in the background server-side — poll until it lands
    if (_gaaData.intel_loading) {
      if (!_gaaPollTimer) _gaaPollTimer = setInterval(pollGaa, 8000);
    }
  } catch (e) {
    panel.innerHTML = emptyState('⚠️', 'Could not load GAA data',
      `${esc(e.message)}<br><button class="linklike" onclick="loadGaa(true)">retry</button>`);
  } finally {
    _gaaLoading = false;
  }
}

async function refreshGaa() {
  const btn = document.getElementById('gaa-refresh-btn');
  if (btn) { btn.disabled = true; btn.textContent = '↻ Refreshing analysis…'; }
  try {
    await fetch('/api/gaa/refresh', { method: 'POST' });
    _gaaData = null;                 // force a fresh fetch + re-render
    await loadGaa(true);
    if (!_gaaPollTimer) _gaaPollTimer = setInterval(pollGaa, 8000);
  } catch { /* ignore */ }
  finally {
    if (btn) { btn.disabled = false; btn.textContent = '↻ Refresh analysis'; }
  }
}

async function pollGaa() {
  try {
    const res = await fetch('/api/gaa');
    const data = await res.json();
    _gaaData = data;
    renderGaa();
    if (!data.intel_loading) { clearInterval(_gaaPollTimer); _gaaPollTimer = null; }
  } catch { /* ignore poll errors */ }
}

function _gaaSportBadge(sport) {
  const s = (sport || '').toLowerCase();
  const label = s === 'football' ? 'Gaelic Football' : 'Hurling';
  const ico = s === 'football' ? '🏐' : '🏑';
  return `<span class="pill" style="font-size:var(--fs-xs)">${ico} ${label}</span>`;
}

function _edgeColour(edge) {
  if (edge == null) return 'var(--tx-4)';
  if (edge > 0) return 'var(--green)';
  if (edge > -5) return 'var(--tx-3)';
  return 'var(--red)';
}

// Odds & edge table: PP price vs Betfair fair line per runner.
function _gaaOddsTable(game) {
  const edges = game.edges || [];
  const soft = game.soft || {};
  const rows = [];

  if (edges.length) {
    for (const e of edges) {
      const col = _edgeColour(e.edge_pct);
      const edgeTxt = e.edge_pct == null ? '—'
        : `${e.edge_pct > 0 ? '+' : ''}${e.edge_pct}%`;
      rows.push(`<tr${e.value ? ' style="background:rgba(46,160,67,0.08)"' : ''}>
        <td style="font-weight:600">${esc(e.runner)}${e.value ? ' <span style="color:var(--green)">◆ value</span>' : ''}</td>
        <td style="text-align:right">${e.pp}</td>
        <td style="text-align:right;color:var(--tx-3)">${e.back}/${e.lay}</td>
        <td style="text-align:right;color:var(--tx-3)">${e.fair_pct}%</td>
        <td style="text-align:right;color:var(--tx-3)">${e.fair_odds ?? '—'}</td>
        <td style="text-align:right;font-weight:700;color:${col}">${edgeTxt}</td>
      </tr>`);
    }
  } else if (Object.keys(soft).length) {
    // PP but no Betfair fair line (e.g. football before the exchange opens)
    for (const [runner, price] of Object.entries(soft)) {
      rows.push(`<tr>
        <td style="font-weight:600">${esc(runner)}</td>
        <td style="text-align:right">${price}</td>
        <td colspan="4" style="text-align:right;color:var(--tx-4)">no exchange fair line yet</td>
      </tr>`);
    }
  } else if (game.sharp) {
    // Betfair fair line only — e.g. Paddy Power blocked from this server's IP
    for (const [runner, fr] of Object.entries(game.sharp)) {
      rows.push(`<tr>
        <td style="font-weight:600">${esc(runner)}</td>
        <td style="text-align:right;color:var(--tx-4)">—</td>
        <td style="text-align:right;color:var(--tx-3)">${fr.back}/${fr.lay}</td>
        <td style="text-align:right;color:var(--tx-3)">${fr.fair_pct}%</td>
        <td style="text-align:right;color:var(--tx-3)">${(100 / fr.fair_pct).toFixed(2)}</td>
        <td style="text-align:right;color:var(--tx-4)">—</td>
      </tr>`);
    }
  }

  if (!rows.length) return '<div style="color:var(--tx-4)">No odds posted yet.</div>';

  const ppMissing = !Object.keys(soft).length && game.sharp;
  const note = ppMissing
    ? `<div style="font-size:var(--fs-xs);color:var(--amber);margin-top:6px">Paddy Power price unavailable from this server (Cloudflare/geo block) — showing the Betfair fair line only.</div>`
    : `<div style="font-size:var(--fs-xs);color:var(--tx-4);margin-top:6px">Edge = how much Paddy Power's price beats (+) or trails (−) the vig-free Betfair fair odds.</div>`;

  return `<table class="gaa-odds" style="width:100%;border-collapse:collapse;font-size:var(--fs-sm)">
    <thead><tr style="color:var(--tx-4);font-size:var(--fs-xs);text-align:right">
      <th style="text-align:left">Runner</th><th>Paddy Power</th><th>BF back/lay</th>
      <th>Fair %</th><th>Fair odds</th><th>Edge</th>
    </tr></thead>
    <tbody>${rows.join('')}</tbody>
  </table>
  ${note}`;
}

// GAA analyst block — mirrors the soccer intel card but for GAA fields/markets.
function _gaaIntel(intel) {
  if (!intel) {
    return `<div class="intel-loading" style="display:flex;align-items:center;gap:8px;color:var(--tx-4)">
      <div class="spinner" style="width:12px;height:12px"></div> Analyst researching form &amp; team news…</div>`;
  }
  const conf = intel.intel_confidence || 'low';
  const confColour = conf === 'high' ? 'var(--green)' : conf === 'medium' ? 'var(--amber)' : 'var(--tx-3)';

  const recs = (intel.recommended_bets || []).map(rb => {
    const sc = rb.strength === 'strong' ? 'var(--green)' : rb.strength === 'moderate' ? 'var(--amber)' : 'var(--tx-3)';
    return `<div class="intel-rec" style="margin-top:6px">
      <div style="font-weight:700;color:${sc}">${esc(titleCase((rb.outcome || '').replace(/_/g, ' ')))}
        <span style="font-weight:400;font-size:var(--fs-xs);color:var(--tx-4)">(${esc(rb.market || '')} · ${esc(rb.strength || '—')})</span></div>
      <div style="color:var(--tx-2);line-height:1.5">${esc(rb.reasoning || '—')}</div>
    </div>`;
  }).join('') || `<div style="color:var(--tx-4);font-size:var(--fs-sm)">Analyst sees no clear edge — no bet flagged.</div>`;

  return `<div class="intel-block" style="margin-top:12px">
    <div class="intel-block__head" style="display:flex;justify-content:space-between">
      <span>ANALYST RESEARCH</span>
      <span style="font-weight:400;color:${confColour}">match-read confidence: ${esc(conf)}</span>
    </div>
    <div class="intel-block__body">
      <div><span class="lbl">Home form:</span> ${esc(intel.home_form || '—')}</div>
      <div><span class="lbl">Away form:</span> ${esc(intel.away_form || '—')}</div>
      ${intel.key_absences ? `<div><span class="lbl">Absences:</span> ${esc(intel.key_absences)}</div>` : ''}
      <div><span class="lbl">Tactical matchup:</span> ${esc(intel.tactical_matchup || '—')}</div>
      <div><span class="lbl">Scoring:</span> ${esc(intel.points_assessment || '—')}</div>
      <div><span class="lbl">Market read:</span> ${esc(intel.market_read || '—')}</div>
      <div class="intel-rec-wrap" style="margin-top:8px">
        <div style="font-size:var(--fs-xs);color:var(--tx-4)">ANALYST RECOMMENDATION</div>
        ${recs}
      </div>
      ${intel.overall_summary ? `<div style="color:var(--tx-2);line-height:1.6;font-style:italic;margin-top:8px">${esc(intel.overall_summary)}</div>` : ''}
      ${intel.knowledge_caveat ? `<div style="font-size:var(--fs-xs);color:var(--tx-4);border-top:1px solid var(--line-1);padding-top:6px;margin-top:6px">Data caveat: ${esc(intel.knowledge_caveat)}</div>` : ''}
    </div>
  </div>`;
}

// Freshness banner for the pushed Paddy Power snapshot (Option B). Shows how long
// ago the residential-IP fetcher last pushed, and flags it stale (>30 min).
function _gaaSoftFreshness() {
  const src = _gaaData?.soft_source;
  const ts = _gaaData?.soft_updated_at;
  if (src !== 'push' || !ts) return '';   // only relevant for the hosted push path
  const ageMin = Math.round((Date.now() / 1000 - ts) / 60);
  const stale = ageMin > 300;   // pusher runs every 4h; only warn if a cycle was missed
  const col = stale ? 'var(--amber)' : 'var(--green)';
  const ageTxt = ageMin < 1 ? 'just now'
    : ageMin < 90 ? `${ageMin} min ago`
    : `${(ageMin / 60).toFixed(1)}h ago`;
  return `<div class="legend" style="margin-bottom:12px">
    <span style="color:${col}">● Paddy Power odds updated ${ageTxt}${stale ? ' — stale (fetcher offline?)' : ''}</span>
  </div>`;
}

function renderGaa() {
  const panel = document.getElementById('gaa-panel');
  if (!panel) return;
  const games = _gaaData?.games || [];

  if (!games.length) {
    panel.innerHTML = emptyState('☘', 'No live GAA games',
      'No All-Ireland hurling or football markets are open right now. Championship runs ~May–July.');
    return;
  }

  const intelNote = (!_gaaData.intel_available)
    ? `<div class="legend" style="margin-bottom:12px"><span style="color:var(--amber)">Analyst offline — set ANTHROPIC_API_KEY to enable form/injury analysis. Odds &amp; edges still live.</span></div>`
    : '';

  const toolbar = `<div class="toolbar" style="justify-content:flex-end">
    <button id="gaa-refresh-btn" class="btn btn--sm" onclick="refreshGaa()"
      title="Re-run the analyst research to pick up the latest form &amp; injury news">↻ Refresh analysis</button>
  </div>`;

  panel.innerHTML = toolbar + intelNote + _gaaSoftFreshness() + games.map(game => `
    <div class="bet-card" style="margin-bottom:16px">
      <div class="bet-card__top">
        <div>
          <div class="bet-card__pick" style="font-size:var(--fs-md)">${esc(game.match)}</div>
          <div class="bet-card__meta">${kickoffCountdown(game.throw_in)} ${_gaaSportBadge(game.sport)}
            <span style="color:var(--tx-4)">${esc(game.competition || '')}</span></div>
        </div>
      </div>
      <div style="margin-top:10px">${_gaaOddsTable(game)}</div>
      ${_gaaIntel(game.intel)}
    </div>`).join('');
}
