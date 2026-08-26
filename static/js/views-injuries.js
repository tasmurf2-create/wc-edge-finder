/* ============================================================
   views-injuries.js — team-news table + club search
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
  if (!text) return emptyState('🩹', 'No team news yet', 'Team news is gathered per match when the analyst runs. Hit "Refresh injuries" to re-research the upcoming fixtures.');
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
  const rawItems = _injuryInfo?.items || [];   // per-match: {match, league, commence, absences}
  const leagueFilter = document.getElementById('inj-team-filter')?.value || '';

  // The cache can hold one fixture under two label spellings (e.g. "Hearts" vs
  // "Heart of Midlothian"), which otherwise shows the same match twice. Collapse
  // by normalised fixture key, keeping the richer entry (longest team-news text).
  const byFixture = new Map();
  for (const it of rawItems) {
    const key = normalizeMatchLabel((it.match || '').toLowerCase());
    const cur = byFixture.get(key);
    if (!cur || (it.absences || '').length > (cur.absences || '').length) byFixture.set(key, it);
  }
  const items = [...byFixture.values()];

  const leagues = [...new Set(items.map(i => i.league).filter(Boolean))].sort();
  const list = items.filter(i => !leagueFilter || i.league === leagueFilter);

  const filterBar = `<div class="toolbar" style="padding-left:0;padding-right:0;padding-top:0">
    <div class="field"><label>League</label>
      <select id="inj-team-filter" onchange="renderInjuryTable()">
        <option value="">All leagues (${leagues.length})</option>
        ${leagues.map(l => `<option value="${esc(l)}"${l === leagueFilter ? ' selected' : ''}>${esc(l)}</option>`).join('')}
      </select>
    </div>
    <span style="font-size:var(--fs-xs);color:var(--tx-4)">${list.length} match${list.length !== 1 ? 'es' : ''} with team news</span>
  </div>`;

  const legend = `<div class="legend" style="margin-bottom:12px">
    <span>Team news is gathered per match from the analyst's research. It reflects what was found — a match with no entry means nothing notable was reported, not that every player is fit.</span>
  </div>`;

  const cards = list.length
    ? list.map(i => {
        const when = i.commence ? fmt(i.commence) : '';
        return `<div class="card" style="margin-bottom:10px">
          <div class="card__head">
            <div>
              <div class="match-title">${fmtLabel(i.match)}</div>
              <div class="match-sub">${esc(i.league || '')}${when ? ' · ' + when : ''}</div>
            </div>
          </div>
          <div style="line-height:1.6;color:var(--tx-2);font-size:var(--fs-sm)">${esc(i.absences)}</div>
        </div>`;
      }).join('')
    : emptyState('🩹', 'No team news yet', 'Team news appears here as the analyst researches each upcoming match. Open Today or Best Bets to kick that off, or hit "Refresh injuries".');

  panel.innerHTML = legend + filterBar + cards;
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
  const upd = document.getElementById('injuries-updated');
  // Remember the current digest time so we can detect when a genuinely NEW one
  // lands. (Old bug: polled for "any digest exists" — always true — so it
  // "finished" in ~5s showing the stale digest, with no sign work was happening.)
  const prevFetchedAt = (_injuryInfo && _injuryInfo.fetched_at) || 0;
  const spin = `<span class="spinner" style="width:11px;height:11px;display:inline-block;vertical-align:middle;margin-right:6px"></span>`;
  const setStatus = (html) => { if (upd) upd.innerHTML = html; };

  btn.disabled = true; btn.textContent = 'Refreshing…';
  setStatus(`${spin}<span style="color:var(--amber)">Searching the web for the latest injury &amp; suspension news… this usually takes 20–40s.</span>`);

  let r;
  try {
    r = await (await fetch('/api/refresh-injuries')).json();
  } catch {
    btn.disabled = false; btn.textContent = '🩹 Refresh injuries';
    setStatus(`<span style="color:var(--red)">Couldn't start the refresh — check your connection and try again.</span>`);
    return;
  }
  if (r.status === 'cooldown') {
    // Server-side cooldown protects the search budget — the cached digest is current.
    btn.disabled = false; btn.textContent = '🩹 Refresh injuries';
    setStatus(`Already up to date — the news digest refreshes at most once every few minutes. Try again in ~${Math.ceil((r.retry_in_s || 60) / 60)} min.`);
    return;
  }

  // Restart the intel poll so re-analysis banners appear on match cards promptly.
  if (!_intelPollTimer) _intelPollTimer = setInterval(pollIntel, 8000);

  // Poll until the digest's fetched_at ADVANCES — the true "done" signal (the
  // web search completed, whether or not the news actually changed). Up to 90s:
  // the search + SDK retries can run well over 30s.
  let elapsed = 0;
  const pollId = setInterval(async () => {
    elapsed += 5;
    btn.textContent = `Refreshing… (${elapsed}s)`;
    setStatus(`${spin}<span style="color:var(--amber)">Searching for the latest injury &amp; suspension news… (${elapsed}s)</span>`);
    try {
      const info = await (await fetch('/api/injuries')).json();
      if (info.fetched_at && info.fetched_at > prevFetchedAt) {
        clearInterval(pollId);
        _injuriesLoaded = true;
        renderInjuries(info);   // re-renders the digest + writes its "Last refreshed" time
        btn.disabled = false; btn.textContent = '🩹 Refresh injuries';
        setStatus(`<span style="color:var(--green)">✓ Updated just now — analyst cards for affected teams are re-checking in the background.</span>`);
        return;
      }
    } catch { /* transient — keep polling */ }
    if (elapsed >= 90) {
      clearInterval(pollId);
      btn.disabled = false; btn.textContent = '🩹 Refresh injuries';
      setStatus(`<span style="color:var(--tx-3)">Still searching — the news refresh can be slow or rate-limited. It'll update on its own when ready; you can keep using the app.</span>`);
    }
  }, 5000);
}

/* ---------------- team search (header) ---------------- */

function onTeamSearch(q) {
  const resultsEl = document.getElementById('team-search-results');
  const clearEl = document.getElementById('team-search-clear');
  const summaryEl = document.getElementById('team-search-summary');

  q = q.trim();

  // On list views (Best Bets, Markets) the search is scoped to THIS page:
  // filter the page's odds/recommendations in place instead of showing the
  // global cross-section overlay.
  if (searchIsScoped()) {
    pageSearch = q;
    clearEl.style.display = q ? '' : 'none';
    summaryEl.style.display = 'none';
    resultsEl.style.display = 'none';
    rerenderScopedView();
    return;
  }

  if (!q) { clearTeamSearch(); return; }

  clearEl.style.display = '';
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
    html += `<div><div class="search-section-title">Sharp Line (${divMatches.length})</div>`;
    divMatches.forEach(m => {
      const probs = (m.outcomes || []).map(o =>
        `${fmtPick(o.outcome)} ${o.book_fair != null ? o.book_fair.toFixed(0) + '%' : '—'}`).join(' · ');
      html += `<div class="search-hit">
        <strong style="color:var(--tx-1)">${fmtLabel(m.label)}</strong>
        <span style="color:var(--tx-4);margin-left:8px">${esc(m.round?.label || '')}</span>
        <div style="color:var(--tx-3);margin-top:4px">Book fair: ${probs || '—'}${m.has_sharp_data ? ` · sharp gap ${m.max_gap > 0 ? '+' : ''}${m.max_gap}%` : ''}</div>
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
  document.querySelectorAll('.view').forEach(p => p.style.display = '');
  // Drop any page-scoped filter and re-render the current list page.
  if (pageSearch) { pageSearch = ''; rerenderScopedView(); }
}

// Re-render whichever scoped list view is active (so a page filter applies).
function rerenderScopedView() {
  if (currentView === 'best') {
    (bestSubTab === 'picks' ? renderSensible : renderTopPicks)();
  } else if (currentView === 'markets') {
    if (marketsSubTab === 'divergence') renderDivergence();
    else renderBets();   // Value Singles or Accumulators
  }
}

// Reflect the search scope in the box's placeholder: "this page" on scoped
// list views, generic "team" elsewhere.
function updateSearchScopeHint() {
  const el = document.getElementById('team-search');
  if (!el) return;
  el.placeholder = searchIsScoped() ? 'Search this page… (e.g. Brazil)' : 'Search team…';
}
