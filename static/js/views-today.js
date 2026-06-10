/* ============================================================
   views-today.js — next matchday at a glance
   ============================================================ */

function renderToday() {
  const panel = document.getElementById('today-panel');
  if (!panel) return;
  if (!allMatches.length) { panel.innerHTML = _dataLoaded ? noOddsState() : skeletonCards(3); return; }

  const now = new Date();
  let dayMatches = [], dayLabel = '';

  for (let d = 0; d <= 6; d++) {
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate() + d, 0, 0, 0);
    const end   = new Date(now.getFullYear(), now.getMonth(), now.getDate() + d, 23, 59, 59);
    const from  = d === 0 ? now : start;   // today: from now, not midnight
    dayMatches = allMatches.filter(m => { const k = new Date(m.commence); return k >= from && k <= end; });
    if (dayMatches.length) {
      dayLabel = d === 0 ? 'Today' : d === 1 ? 'Tomorrow'
               : start.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'short' });
      break;
    }
  }

  if (!dayMatches.length) {
    panel.innerHTML = emptyState('📅', 'No upcoming matches in the next 7 days',
      `Browse <button class="linklike" onclick="switchView('markets')">Markets</button> for everything that's priced.`);
    return;
  }

  dayMatches.sort((a, b) => (a.commence || '').localeCompare(b.commence || ''));
  const logged = new Set(loadPlacedBets().map(b => b.match + '|' + b.outcome));

  const cards = dayMatches.map(match => {
    const label = match.label;
    const intel = allIntel[label] || allIntel[normalizeMatchLabel(label)];
    const recs  = intel?.recommended_bets || [];
    const parts = label.split(' vs ');
    const homeN = normalizeTeam(parts[0] || ''), awayN = normalizeTeam(parts[1] || '');

    const recRows = recs.map(rb => {
      const ao = (rb.outcome || '').toLowerCase().replace(/ /g, '_');
      let norm = ao === 'home_win' ? homeN : ao === 'away_win' ? awayN : ao === 'draw' ? 'draw' : null;
      if (!norm) return '';
      const pd = (match.outcomes || []).find(o => o.outcome === norm);
      if (!pd || !pd.best_price) return '';
      const cCls = rb.confidence === 'high' ? 'badge--green' : rb.confidence === 'medium' ? 'badge--amber' : '';
      const edgeCol = (pd.edge || 0) > 1.5 ? 'var(--green)' : (pd.edge || 0) > 0 ? 'var(--amber)' : 'var(--tx-3)';
      const betKey = label + '|' + norm;
      const isLogged = logged.has(betKey);
      const safeMatch = label.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      const safeBook  = (pd.best_book || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'");
      return `<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;flex-wrap:wrap;
                          padding:10px 12px;background:var(--bg-0);border-radius:var(--radius-sm);margin-top:8px">
        <div style="flex:1;min-width:0">
          <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
            <strong style="color:var(--tx-1)">${fmtPick(norm)}</strong>
            ${rb.confidence ? `<span class="badge ${cCls}">${esc(rb.confidence)}${rb.strength ? ' · ' + esc(rb.strength) : ''}</span>` : ''}
            <span style="font-size:var(--fs-sm);color:var(--tx-2)"><b style="color:var(--tx-1)">${pd.best_price.toFixed(2)}</b> @ ${esc(pd.best_book)}</span>
            ${pd.edge != null ? `<span style="font-size:var(--fs-xs);color:${edgeCol}">${pd.edge > 0 ? '+' : ''}${pd.edge.toFixed(1)}% edge</span>` : ''}
          </div>
          ${rb.reasoning ? `<div style="font-size:var(--fs-xs);color:var(--tx-3);margin-top:3px;font-style:italic">${esc(rb.reasoning)}</div>` : ''}
        </div>
        <button class="btn btn--primary btn--sm" ${isLogged ? 'disabled' : ''} style="flex-shrink:0"
          onclick="openBetModal('${safeMatch}','${norm}','h2h',${pd.best_price},'${safeBook}',${pd.book_fair != null ? (pd.book_fair / 100) : 'null'}); this.blur()">
          ${isLogged ? '✓ Logged' : '+ Log bet'}
        </button>
      </div>`;
    }).filter(Boolean).join('');

    const wBadge = match.weather
      ? `<span class="wflag neutral" title="${esc(match.weather.detail || '')}">${esc(match.weather.emoji)} ${esc(fmtAltitudeText(match.weather.headline))}</span>` : '';
    const rBadge = match.round ? `<span class="badge badge--cyan badge--ghost">${esc(match.round.label)}</span>` : '';
    const age = intelAge(intel);

    const updatingBanner = _reanalysing.has(label)
      ? `<div style="display:flex;align-items:center;gap:8px;margin-top:8px;padding:8px 10px;background:var(--amber-bg);border:1px solid #5d4715;border-radius:var(--radius-sm);font-size:var(--fs-sm);color:var(--amber)">
           <div class="spinner" style="border-top-color:var(--amber)"></div>
           Injury news detected — updating analysis, check back in a moment
         </div>`
      : '';

    let bodyHTML;
    if (recRows) {
      bodyHTML = recRows;
    } else if (intel) {
      bodyHTML = `<div style="margin-top:8px;font-size:var(--fs-sm);color:var(--tx-4)">Analyst sees no clear edge — no bet recommended.</div>`;
    } else {
      bodyHTML = `<div style="margin-top:8px;font-size:var(--fs-sm);color:var(--tx-4);display:flex;align-items:center;gap:8px">
        <div class="spinner" style="width:12px;height:12px"></div> Analyst not yet run for this match
      </div>`;
    }

    return `<div class="bet-card">
      <div class="bet-card__top">
        <div>
          <div class="bet-card__pick" style="font-size:var(--fs-md)">${fmtLabel(label)}</div>
          <div class="bet-card__meta">${kickoffCountdown(match.commence)} ${rBadge} ${wBadge}</div>
        </div>
        ${age ? `<span style="color:var(--tx-4);font-size:var(--fs-xs);flex-shrink:0">${age}</span>` : ''}
      </div>
      ${updatingBanner}
      ${bodyHTML}
    </div>`;
  }).join('');

  const analysed = dayMatches.filter(m => allIntel[m.label] || allIntel[normalizeMatchLabel(m.label)]).length;
  panel.innerHTML = `
    <div class="section-title">
      📅 ${dayLabel} — ${dayMatches.length} match${dayMatches.length > 1 ? 'es' : ''}
      <small>${analysed === dayMatches.length ? `all ${analysed} analysed` : `${analysed}/${dayMatches.length} analysed · more analysis running`}</small>
    </div>
    ${cards}`;
}
