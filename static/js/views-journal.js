/* ============================================================
   views-journal.js — My Bets journal (localStorage) + log modal.
   Storage key 'wc26_placed_bets' and bet shape are unchanged
   from v1 — existing journals load as-is.
   ============================================================ */

let _betModalData = null;

// fairProb (0-1, may be null): the model's de-vigged fair probability at the
// moment of logging — stored with the bet for closing-line-value tracking.
function openBetModal(match, outcome, market, defaultOdds, defaultBook, fairProb = null) {
  _betModalData = { match, outcome, market, fairProb };
  document.getElementById('bm-desc').textContent = `${titleCase(outcome)} — ${titleCase(match)}`;
  document.getElementById('bm-odds').value = defaultOdds || '';
  document.getElementById('bm-stake').value = sensibleStake();
  document.getElementById('bm-book').value = defaultBook || '';
  document.getElementById('bet-modal').classList.add('open');
  setTimeout(() => document.getElementById('bm-odds').focus(), 50);
}

function closeBetModal() {
  document.getElementById('bet-modal').classList.remove('open');
  _betModalData = null;
}

function confirmLogBet() {
  if (!_betModalData) return;
  const odds = parseFloat(document.getElementById('bm-odds').value);
  const stake = parseFloat(document.getElementById('bm-stake').value);
  const book = document.getElementById('bm-book').value.trim();
  if (!odds || !stake) return;
  const fairAtLog = _betModalData.fairProb;
  const bets = loadPlacedBets();
  bets.push({
    id: Date.now().toString(),
    match: _betModalData.match,
    outcome: _betModalData.outcome,
    market: _betModalData.market,
    odds, stake, bookmaker: book,
    placed_at: Math.floor(Date.now() / 1000),
    result: 'pending',
    // CLV groundwork: the model's fair prob at log time + EV at the odds taken
    fair_at_log: fairAtLog != null ? +fairAtLog : null,
    ev_at_log: fairAtLog != null ? +((fairAtLog * odds - 1) * 100).toFixed(2) : null,
  });
  savePlacedBets(bets);
  closeBetModal();
  renderMyBets();
  renderToday();   // refresh "Log bet" buttons to show ✓ Logged
}

function setPlacedBetResult(id, result) {
  const bets = loadPlacedBets();
  const b = bets.find(b => b.id === id);
  if (b) { b.result = result; savePlacedBets(bets); renderMyBets(); }
}

function deletePlacedBet(id) {
  if (!confirm('Remove this bet from your tracker?')) return;
  savePlacedBets(loadPlacedBets().filter(b => b.id !== id));
  renderMyBets();
}

// Latest model fair probability for a logged bet's outcome (h2h only) —
// CLV proxy: if the fair prob of your pick ROSE after you bet, you beat the move.
function currentFairFor(b) {
  if (b.market !== 'h2h') return null;
  const want = normalizeMatchLabel(b.match);
  const m = allMatches.find(x => x.label === b.match || normalizeMatchLabel(x.label) === want);
  if (!m) return null;
  const oc = normalizeTeam(b.outcome) || (b.outcome || '').toLowerCase();
  const o = (m.outcomes || []).find(o => o.outcome === oc);
  return o && o.book_fair != null ? o.book_fair / 100 : null;
}

function renderMyBets() {
  const panel = document.getElementById('mybets-panel');
  if (!panel) return;
  const bets = loadPlacedBets();

  if (!bets.length) {
    panel.innerHTML = emptyState('📒', 'No bets logged yet',
      `Hit <strong style="color:var(--green)">+ Log bet</strong> on any card in <button class="linklike" onclick="switchView('today')">Today</button> or <button class="linklike" onclick="switchView('best')">Best Bets</button> to track it here — the journal records the model's fair price at log time so you can prove (or disprove) the edge over time.`);
    return;
  }

  const won = bets.filter(b => b.result === 'won');
  const lost = bets.filter(b => b.result === 'lost');
  const pending = bets.filter(b => b.result === 'pending');
  const settled = bets.filter(b => b.result !== 'pending' && b.result !== 'void');
  const totalStaked = settled.reduce((s, b) => s + b.stake, 0);
  const actualPnl = won.reduce((s, b) => s + b.stake * (b.odds - 1), 0)
                  - lost.reduce((s, b) => s + b.stake, 0);
  const potentialRet = pending.reduce((s, b) => s + b.stake * b.odds, 0);
  const pnlCol = actualPnl > 0 ? 'var(--green)' : actualPnl < 0 ? 'var(--red)' : 'var(--tx-3)';

  // Model-expected P/L vs actual — the honest scoreboard.
  const evBets = bets.filter(b => b.ev_at_log != null && b.result !== 'void');
  const expectedPnl = evBets.reduce((s, b) => s + b.stake * b.ev_at_log / 100, 0);
  const expCol = expectedPnl > 0 ? 'var(--green)' : expectedPnl < 0 ? 'var(--red)' : 'var(--tx-3)';
  const expCell = evBets.length
    ? `<div class="money-cell"><div class="money-lbl help" title="Sum of (stake × EV at log time) over the ${evBets.length} bet(s) logged with a model fair price. Compare with actual P&L over a meaningful sample — convergence is the proof the model works.">Model-expected P&L</div><div class="money-val" style="color:${expCol}">${expectedPnl >= 0 ? '+' : ''}€${expectedPnl.toFixed(2)}</div></div>`
    : '';

  const summary = `<div class="money-strip" style="background:var(--bg-1);border:1px solid var(--line-2)">
    <div class="money-cell"><div class="money-lbl">Settled staked</div><div class="money-val" style="color:var(--tx-1)">€${totalStaked.toFixed(2)}</div></div>
    <div class="money-cell"><div class="money-lbl">P&L</div><div class="money-val" style="color:${pnlCol}">${actualPnl >= 0 ? '+' : ''}€${actualPnl.toFixed(2)}</div></div>
    ${expCell}
    ${pending.length ? `<div class="money-cell"><div class="money-lbl">Pending return</div><div class="money-val" style="color:var(--amber)">€${potentialRet.toFixed(2)}</div></div>` : ''}
    <div class="money-cell"><div class="money-lbl">Record</div>
      <div class="money-val"><span style="color:var(--green)">${won.length}W</span> <span style="color:var(--red)">${lost.length}L</span> <span style="color:var(--amber)">${pending.length}P</span></div>
    </div>
  </div>`;

  const rows = [...bets].reverse().map(b => {
    const ret = b.stake * b.odds;
    const placed = new Date(b.placed_at * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });

    // EV at log + market movement since (CLV proxy)
    let clvLine = '';
    if (b.fair_at_log != null) {
      const evCol = b.ev_at_log >= 0 ? 'var(--green)' : 'var(--red)';
      let movement = '';
      const nowFair = b.result === 'pending' ? currentFairFor(b) : null;
      if (nowFair != null && Math.abs(nowFair - b.fair_at_log) >= 0.001) {
        const up = nowFair > b.fair_at_log;
        movement = ` · fair ${(b.fair_at_log * 100).toFixed(1)}% → ${(nowFair * 100).toFixed(1)}% now `
          + (up ? `<span style="color:var(--green)" title="The market moved towards your pick after you logged it — you beat the move (positive closing-line value so far).">📈 you beat the move</span>`
                : `<span style="color:var(--red)" title="The market moved against your pick after you logged it.">📉 market moved against you</span>`);
      }
      clvLine = `<div style="font-size:var(--fs-xs);color:var(--tx-3);margin-top:4px">
        <span class="help" style="color:${evCol}" title="Expected value at the odds and model fair price when you logged this bet.">EV at log ${b.ev_at_log >= 0 ? '+' : ''}${b.ev_at_log}%</span>${movement}
      </div>`;
    }
    const rBtns = ['pending', 'won', 'lost', 'void'].map(r => {
      const on = b.result === r;
      const col = r === 'won' ? 'var(--green)' : r === 'lost' ? 'var(--red)' : r === 'void' ? 'var(--tx-3)' : 'var(--amber)';
      const lbl = r === 'pending' ? 'Pending' : r === 'won' ? '✓ Won' : r === 'lost' ? '✗ Lost' : 'Void';
      return `<button class="btn btn--sm" onclick="setPlacedBetResult('${b.id}','${r}')"
        style="${on ? `color:${col};border-color:${col}` : ''}">${lbl}</button>`;
    }).join('');

    return `<div class="bet-card">
      <div class="bet-card__top">
        <div style="min-width:0">
          <div class="bet-card__pick" style="font-size:var(--fs-md)">${fmtPick(b.outcome)} <span class="vs">— ${fmtLabel(b.match)}</span></div>
          <div class="bet-card__meta">${esc(b.bookmaker || '—')} · ${b.odds.toFixed(2)} · ${placed}</div>
          ${clvLine}
        </div>
        <div style="text-align:right;flex-shrink:0">
          <div style="font-size:var(--fs-md);color:var(--tx-1);font-weight:650">€${b.stake.toFixed(2)}</div>
          <div style="font-size:var(--fs-xs);color:var(--green)">→ €${ret.toFixed(2)}</div>
        </div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        ${rBtns}
        <button class="btn btn--quiet btn--sm" style="margin-left:auto" title="Remove from tracker" onclick="deletePlacedBet('${b.id}')">🗑</button>
      </div>
    </div>`;
  }).join('');

  panel.innerHTML = summary + rows;
}
