/* ============================================================
   views-injuries.js — injuries table + tournament team search
   ============================================================ */

let _injuryInfo = null;   // last /api/injuries payload (items may be null = legacy text)

const INJURY_STATUS_META = {
  out:       { label: 'Out',       col: '#f85149' },
  doubtful:  { label: 'Doubtful',  col: '#e3a93c' },
  suspended: { label: 'Suspended', col: '#bc8cff' },
  fit_again: { label: 'Fit Again', col: '#3fcf6e' },
  unknown:   { label: 'Unclear',   col: '#76838f' },
};

// Legacy text digest fallback — strips any AI preamble lines before rendering.
function fmtInjuryDigest(text) {
  if (!text) return emptyState('🩹', 'No injury data yet', 'Hit "Refresh injuries" to fetch the tournament-wide digest.');
  const preambleRe = /^(i'?ll\s|i will\s|based on\s|here is\s|here'?s\s|let me\s|searching\s|i('ve| have)\s)/i;
  const lines = text.split('\n');
  while (lines.length > 0 && (lines[0].trim() === '' || preambleRe.test(lines[0].trim()))) {
    lines.shift();
  }
  text = lines.join('\n').trim();
  if (!text) return emptyState('🩹', 'Injury data is empty', 'Try refreshing.');
  // Light markdown: ## TEAM headers, **bold**, line breaks. Escaped first.
  return esc(text)
    .replace(/^#+\s*\*\*(.+?)\*\*/gm, '<div style="color:var(--blue);font-weight:700;margin:14px 0 4px;font-size:0.95rem">$1</div>')
    .replace(/^#+\s*(.+)$/gm, '<div style="color:var(--blue);font-weight:700;margin:14px 0 4px;font-size:0.95rem">$1</div>')
    .replace(/\*\*(.+?)\*\*/g, '<strong style="color:var(--tx-1)">$1</strong>')
    .replace(/\n/g, '<br>');
}

function renderInjuryTable() {
  const panel = document.getElementById('injuries-panel');
  const items = _injuryInfo?.items || [];
  const teamFilter = document.getElementById('inj-team-filter')?.value || '';
  const statusFilter = document.getElementById('inj-status-filter')?.value || '';

  const teams = [...new Set(items.map(i => i.team))].sort();
  const statuses = [...new Set(items.map(i => i.status))];
  const list = items.filter(i =>
    (!teamFilter || i.team === teamFilter) && (!statusFilter || i.status === statusFilter));

  const filterBar = `<div class="toolbar" style="padding-left:0;padding-right:0;padding-top:0">
    <div class="field"><label>Team</label>
      <select id="inj-team-filter" onchange="renderInjuryTable()">
        <option value="">All teams (${teams.length})</option>
        ${teams.map(t => `<option value="${esc(t)}"${t === teamFilter ? ' selected' : ''}>${esc(t)}</option>`).join('')}
      </select>
    </div>
    <div class="field"><label>Status</label>
      <select id="inj-status-filter" onchange="renderInjuryTable()">
        <option value="">All statuses</option>
        ${statuses.map(st => `<option value="${esc(st)}"${st === statusFilter ? ' selected' : ''}>${esc(INJURY_STATUS_META[st]?.label || st)}</option>`).join('')}
      </select>
    </div>
    <span style="font-size:var(--fs-xs);color:var(--tx-4)">${list.length} player${list.length !== 1 ? 's' : ''}</span>
  </div>`;

  const rows = list.map(i => {
    const meta = INJURY_STATUS_META[i.status] || INJURY_STATUS_META.unknown;
    return `<tr>
      <td>${esc(i.team)}</td>
      <td style="text-align:left">${esc(i.player)}</td>
      <td style="text-align:left"><span class="badge" style="background:${meta.col}18;color:${meta.col};border-color:${meta.col}55">${meta.label}</span></td>
      <td style="text-align:left;color:var(--tx-3)">${esc(i.detail || '—')}</td>
    </tr>`;
  }).join('');

  const table = list.length
    ? `<div class="table-wrap">
        <table style="min-width:560px"><thead><tr>
          <th>Team</th><th style="text-align:left">Player</th><th style="text-align:left">Status</th><th style="text-align:left">Detail</th>
        </tr></thead><tbody>${rows}</tbody></table>
      </div>`
    : emptyState('🔍', 'No injury or suspension news matches the current filters', '');

  panel.innerHTML = filterBar + table;
}

function renderInjuries(info) {
  const panel = document.getElementById('injuries-panel');
  const upd = document.getElementById('injuries-updated');
  _injuryInfo = info;
  if (Array.isArray(info.items)) {
    renderInjuryTable();   // structured digest → filterable table
  } else {
    panel.innerHTML = `<div style="line-height:1.6;font-size:var(--fs-md);color:var(--tx-2)">${fmtInjuryDigest(info.digest)}</div>`;
  }
  if (info.fetched_at) {
    const d = new Date(info.fetched_at * 1000);
    upd.textContent = 'Last refreshed: ' + d.toLocaleString();
  } else {
    upd.textContent = '';
  }
}

async function loadInjuries() {
  const panel = document.getElementById('injuries-panel');
  panel.innerHTML = skeletonCards(2);
  try {
    const res = await fetch('/api/injuries');   // cached digest — no web search, free
    const info = await res.json();
    _injuriesLoaded = true;
    renderInjuries(info);
  } catch (e) {
    panel.innerHTML = emptyState('⚠️', "Couldn't load injuries", esc(e.message));
  }
}

async function refreshInjuriesDigest() {
  const btn = document.getElementById('injuries-refresh-btn');
  const panel = document.getElementById('injuries-panel');
  btn.disabled = true; btn.textContent = 'Refreshing…';
  try {
    const r = await (await fetch('/api/refresh-injuries')).json();
    if (r.status === 'cooldown') {
      // Server-side cooldown protects the search budget — cached digest is current.
      btn.disabled = false; btn.textContent = '🩹 Refresh injuries';
      const upd = document.getElementById('injuries-updated');
      if (upd) upd.textContent = `Refreshed recently — try again in ~${Math.ceil((r.retry_in_s || 60) / 60)} min`;
      return;
    }
  } catch {
    btn.disabled = false; btn.textContent = '🩹 Refresh injuries';
    return;
  }
  // Restart the intel poll so re-analysis banners appear on match cards promptly
  if (!_intelPollTimer) _intelPollTimer = setInterval(pollIntel, 8000);
  // Poll every 5s for up to 90s — web search + retries can take well over 30s
  let elapsed = 0;
  const pollId = setInterval(async () => {
    elapsed += 5;
    btn.textContent = `Refreshing… (${elapsed}s)`;
    try {
      const res = await fetch('/api/injuries');
      const info = await res.json();
      if (info.digest) {
        clearInterval(pollId);
        _injuriesLoaded = true;
        renderInjuries(info);
        btn.disabled = false; btn.textContent = '🩹 Refresh injuries';
        return;
      }
    } catch { /* keep polling */ }
    if (elapsed >= 90) {
      clearInterval(pollId);
      panel.innerHTML = emptyState('⏳', 'Injury refresh is taking longer than expected', 'Check back in a moment or try again.');
      btn.disabled = false; btn.textContent = '🩹 Refresh injuries';
    }
  }, 5000);
}

/* ---------------- team search (header) ---------------- */

function onTeamSearch(q) {
  const resultsEl = document.getElementById('team-search-results');
  const clearEl = document.getElementById('team-search-clear');
  const summaryEl = document.getElementById('team-search-summary');

  q = q.trim();
  if (!q) { clearTeamSearch(); return; }

  clearEl.style.display = '';
  document.getElementById('primary-nav').style.display = 'none';
  document.querySelectorAll('.view').forEach(p => p.style.display = 'none');
  summaryEl.style.display = '';
  resultsEl.style.display = 'flex';

  const lq = q.toLowerCase();
  const matchesTeam = str => str.toLowerCase().includes(lq);

  const singles = allSingles.filter(s => matchesTeam(s.outcome || '') || matchesTeam(s.match || ''));
  const accas = allParlays.filter(p => p.legs && p.legs.some(l => matchesTeam(l.match || '') || matchesTeam(l.outcome || '')));
  const divMatches = allMatches.filter(m => matchesTeam(m.label || ''));
  const intelMatches = intelEntries().filter(([label]) => matchesTeam(label));

  const total = singles.length + accas.length + divMatches.length + intelMatches.length;
  summaryEl.textContent = total ? `${total} result${total !== 1 ? 's' : ''} for "${q}"` : `No results for "${q}"`;

  let html = '';

  if (divMatches.length) {
    html += `<div><div class="search-section-title">Market Divergence (${divMatches.length})</div>`;
    divMatches.forEach(m => {
      const probs = (m.outcomes || []).map(o =>
        `${fmtPick(o.outcome)} ${o.book_fair != null ? o.book_fair.toFixed(0) + '%' : '—'}`).join(' · ');
      html += `<div class="search-hit">
        <strong style="color:var(--tx-1)">${fmtLabel(m.label)}</strong>
        <span style="color:var(--tx-4);margin-left:8px">${esc(m.round?.label || '')}</span>
        <div style="color:var(--tx-3);margin-top:4px">Book fair: ${probs || '—'}${m.has_pm_data ? ` · PM gap ${m.max_gap > 0 ? '+' : ''}${m.max_gap}%` : ''}</div>
      </div>`;
    });
    html += '</div>';
  }

  if (singles.length) {
    html += `<div><div class="search-section-title">Value Singles (${singles.length})</div>`;
    singles.forEach(s => {
      const edge = s.edge != null ? `${s.edge > 0 ? '+' : ''}${s.edge.toFixed(1)}%` : '';
      const fairPct = s.fair_prob != null ? (s.fair_prob * 100).toFixed(1) : '—';
      html += `<div class="search-hit">
        <strong style="color:var(--tx-1)">${fmtPick(s.outcome)}</strong>
        <span style="color:var(--tx-4);margin-left:6px">${fmtLabel(s.match)}</span>
        <span style="float:right;color:${s.edge > 0 ? 'var(--green)' : 'var(--red)'}">${edge}</span>
        <div style="color:var(--tx-3);margin-top:2px">Best: ${s.best_price} @ ${esc(s.best_book)} · Fair: ${fairPct}%</div>
      </div>`;
    });
    html += '</div>';
  }

  if (accas.length) {
    html += `<div><div class="search-section-title">Accumulators (${accas.length})</div>`;
    accas.forEach(p => {
      const legsStr = p.legs.map(l => {
        const hi = matchesTeam(l.match || '') || matchesTeam(l.outcome || '');
        return `<span style="color:${hi ? 'var(--tx-1)' : 'var(--tx-4)'}">${fmtPick(l.outcome)} (${l.best_price})</span>`;
      }).join(' + ');
      html += `<div class="search-hit">
        <div style="margin-bottom:4px">${legsStr}</div>
        <span style="color:var(--tx-3)">Combined: ${p.combined_price?.toFixed(2)} · ${p.legs.length} legs</span>
      </div>`;
    });
    html += '</div>';
  }

  if (intelMatches.length) {
    html += `<div><div class="search-section-title">Analyst Writeups (${intelMatches.length})</div>`;
    intelMatches.forEach(([label, intel]) => {
      const conf = intel.intel_confidence || 'low';
      const confColor = conf === 'high' ? 'var(--green)' : conf === 'medium' ? 'var(--amber)' : 'var(--tx-4)';
      const summary = intel.overall_summary || '—';
      const recs = intel.recommended_bets || [];
      const recsHtml = recs.length ? recs.map(r => `<div style="color:var(--tx-2);margin-top:3px">→ ${esc(titleCase((r.outcome || '').replace(/_/g, ' ')))} <span style="color:var(--tx-3)">(${esc(r.reasoning || '')})</span></div>`).join('') : '';
      html += `<div class="search-hit">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <strong style="color:var(--tx-1)">${fmtLabel(label)}</strong>
          <span style="font-size:var(--fs-xs);color:${confColor};text-transform:uppercase">${esc(conf)} confidence</span>
        </div>
        <div style="color:var(--tx-3);line-height:1.5">${esc(summary)}</div>
        ${recsHtml}
      </div>`;
    });
    html += '</div>';
  }

  if (!html) html = emptyState('🔍', `No mentions of "${esc(q)}"`, 'Try the full team name, e.g. "South Korea".');
  resultsEl.innerHTML = html;
}

function clearTeamSearch() {
  document.getElementById('team-search').value = '';
  document.getElementById('team-search-clear').style.display = 'none';
  const summaryEl = document.getElementById('team-search-summary');
  summaryEl.textContent = '';
  summaryEl.style.display = 'none';
  document.getElementById('team-search-results').style.display = 'none';
  document.getElementById('primary-nav').style.display = '';
  document.querySelectorAll('.view').forEach(p => p.style.display = '');
}
