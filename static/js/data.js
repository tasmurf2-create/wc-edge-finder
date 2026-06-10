/* ============================================================
   data.js — API loading, intel polling, silent auto-refresh
   ============================================================ */

function renderAll() {
  renderToday();
  renderSensible();
  renderTopPicks();
  renderBets();
  renderFixtures();
  renderDivergence();
}

function _setUpdatedStamp(fetchedAt) {
  const el = document.getElementById('fetch-time');
  if (!el || !fetchedAt) return;
  const d = new Date(fetchedAt * 1000);
  el.innerHTML = `<span class="live-dot"></span>Odds ${d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`;
  el.title = 'Odds snapshot fetched at ' + d.toLocaleString();
}

let _lastFetchedAt = 0;

async function loadData(force = false, silent = false) {
  const btn = document.getElementById('refresh-btn');
  if (!silent) {
    btn.disabled = true;
    btn.innerHTML = '↻ <span class="btn-label">Refreshing…</span>';
    // skeletons in the visible panels only — the rest render when data lands
    document.getElementById('today-panel').innerHTML    = skeletonCards(3);
    document.getElementById('sensible-panel').innerHTML = skeletonCards(3);
    document.getElementById('bets-panel').innerHTML     = `<div class="view-body" style="padding-top:0">${skeletonCards(3)}</div>`;
    document.getElementById('matches').innerHTML        = skeletonCards(4);

    if (_intelPollTimer) { clearInterval(_intelPollTimer); _intelPollTimer = null; }
  }

  try {
    const [divRes, betsRes, intelRes] = await Promise.all([
      fetch(force ? '/api/refresh' : '/api/divergence'),
      fetch('/api/bets'),
      fetch('/api/intel'),
    ]);
    const prevIntelCount = Object.keys(allIntel).length;
    try { allIntel = (await intelRes.json()).intel || {}; } catch { allIntel = {}; }
    const divData  = await divRes.json();
    const betsData = await betsRes.json();

    if (divData.error) throw new Error(divData.error);

    const fetchedAt = divData.fetched_at || betsData.fetched_at;
    // Silent background poll: leave the DOM alone unless something changed
    if (silent && fetchedAt === _lastFetchedAt
        && Object.keys(allIntel).length === prevIntelCount) return;
    _lastFetchedAt = fetchedAt;

    _dataLoaded     = true;
    allMatches      = divData.matches || [];
    allSingles      = betsData.bets?.singles || [];
    allParlays      = betsData.bets?.parlays || [];
    allBookmakers   = betsData.bookmakers || [];
    accaMarkets     = betsData.markets_available || [];
    roundsAvailable = betsData.rounds_available || [];
    populateRoundFilter();
    populateSensibleRoundFilter();

    // Populate bookmaker dropdowns once (markets + writeups)
    ['book-select', 'picks-book-select'].forEach(selId => {
      const sel = document.getElementById(selId);
      if (sel && sel.options.length <= 1 && allBookmakers.length) {
        allBookmakers.forEach(bk => {
          const opt = document.createElement('option');
          opt.value = bk; opt.textContent = bk;
          if (bk === 'Paddy Power') opt.selected = true;
          sel.appendChild(opt);
        });
      }
    });

    _setUpdatedStamp(fetchedAt);
    renderAll();

    // If intel is still loading in the background, poll for it
    if (betsData.intel_loading) {
      if (!_intelPollTimer) _intelPollTimer = setInterval(pollIntel, 8000);
    } else if (betsData.intel_ready === 0) {
      _markAnalystUnavailable();
    }
  } catch (e) {
    if (!silent) {
      const err = emptyState('⚠️', 'Could not load data',
        `${esc(e.message)}<br>Check <button class="linklike" onclick="loadData(true)">retry</button> or the server logs.`);
      document.getElementById('today-panel').innerHTML = err;
      document.getElementById('bets-panel').innerHTML  = err;
      document.getElementById('matches').innerHTML     = err;
      document.getElementById('sensible-panel').innerHTML = err;
    }
  } finally {
    if (!silent) {
      btn.disabled = false;
      btn.innerHTML = '↻ <span class="btn-label">Refresh</span>';
    }
  }
}

function _markAnalystUnavailable() {
  document.querySelectorAll('.intel-loading').forEach(el => {
    el.innerHTML = '<span style="color:var(--tx-4);font-size:var(--fs-sm)">Analyst unavailable — check Anthropic API credits at console.anthropic.com</span>';
  });
}

async function pollIntel() {
  try {
    const res  = await fetch('/api/intel');
    const data = await res.json();
    if (!data.intel || !Object.keys(data.intel).length) return;

    allIntel = { ...allIntel, ...data.intel };

    let changed = false;
    allSingles.forEach(s => {
      if (!s.intel && data.intel[s.match]) {
        s.intel = data.intel[s.match];
        s.analyst_confirms = analystConfirms(s, s.intel);
        changed = true;
      }
    });
    allParlays.forEach(p => p.legs.forEach(l => {
      if (!l.intel && data.intel[l.match]) { l.intel = data.intel[l.match]; changed = true; }
    }));

    // Matches being re-analysed after injury news (banner on cards)
    const newReanalysing = new Set(data.reanalysing || []);
    const reanalysisChanged = [...newReanalysing].some(l => !_reanalysing.has(l))
                           || [..._reanalysing].some(l => !newReanalysing.has(l));
    _reanalysing = newReanalysing;

    if (changed || reanalysisChanged) renderAll();

    if (!data.intel_loading && !_reanalysing.size) {
      clearInterval(_intelPollTimer);
      _intelPollTimer = null;
      if (!data.intel_ready) _markAnalystUnavailable();
    }
  } catch { /* ignore poll errors */ }
}

// Rebuild accumulators server-side for the chosen risk/guard/round preset.
async function refetchParlays() {
  _accaBusy = true;
  if (betsSubTab === 'parlays') renderBets();   // reflect busy state immediately
  try {
    const res  = await fetch(`/api/bets?risk=${encodeURIComponent(accaRisk)}&value_guard=${accaGuard}&round=${encodeURIComponent(accaRound)}`);
    const data = await res.json();
    allParlays  = data.bets?.parlays || [];
    accaMarkets = data.markets_available || accaMarkets;
  } catch {
    allParlays = [];
  } finally {
    _accaBusy = false;
    renderBets();
  }
}

// Silent background re-poll: the server refreshes its odds cache every
// ODDS_REFRESH_MINUTES (paid plan); this just picks up the new snapshot —
// it never forces a fetch, so an open tab costs zero API requests.
setInterval(() => loadData(false, true), 5 * 60 * 1000);
