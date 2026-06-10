/* ============================================================
   views-markets.js — Value Singles, Accumulators, Acca Builder
   and Market Divergence (the "Markets" view).
   ============================================================ */

/* ---------------- shared controls ---------------- */

function populateRoundFilter() {
  const sel = document.getElementById('round-filter');
  if (!sel || sel.options.length > 1 || !roundsAvailable.length) return;
  roundsAvailable.forEach(r => {
    const o = document.createElement('option');
    o.value = r; o.textContent = r;
    sel.appendChild(o);
  });
}

// Round dropdown changes BOTH the singles shown and the accas built
// (single-round accas need the server to rebuild from that round's legs).
function onRoundChange() {
  accaRound = document.getElementById('round-filter').value;
  refetchParlays();
}

const ACCA_RISK_INFO = {
  banker:   { label: 'Banker',   blurb: 'nailed-on legs · 2–4 legs · ≥30% chance' },
  balanced: { label: 'Balanced', blurb: 'solid legs · 4–6 legs · ≥12% chance' },
  punchy:   { label: 'Punchy',   blurb: 'long slips · 6–8 legs · ≥4% chance' },
};

function setAccaRisk(risk) {
  if (risk === accaRisk) return;
  accaRisk = risk;
  refetchParlays();
}
function toggleAccaGuard(on) { accaGuard = on; refetchParlays(); }
function setAccaSort(v) { accaSort = v; renderBets(); }

function accaControlsHTML() {
  const riskBtns = Object.entries(ACCA_RISK_INFO).map(([key, info]) =>
    `<button class="pill${accaRisk === key ? ' active' : ''}" onclick="setAccaRisk('${key}')" title="${info.blurb}">${info.label}</button>`
  ).join('');
  return `
    <div class="toolbar" style="padding-left:0;padding-right:0">
      <div class="field"><label>Risk</label></div>
      ${riskBtns}
      <label class="field" style="cursor:pointer;font-size:var(--fs-sm);color:var(--tx-2)" title="Drop legs priced well below fair (after line-shopping all books). Favourite accas are never strictly +EV, so this minimises the bookmaker margin rather than eliminating it.">
        <input type="checkbox" style="accent-color:var(--green);width:16px;height:16px" ${accaGuard ? 'checked' : ''} onchange="toggleAccaGuard(this.checked)">
        Value guard <span style="color:var(--tx-4)">(low-margin legs)</span>
      </label>
      <div class="field"><label>Sort</label>
        <select onchange="setAccaSort(this.value)">
          <option value="chance" ${accaSort === 'chance' ? 'selected' : ''}>Chance to land (high→low)</option>
          <option value="return" ${accaSort === 'return' ? 'selected' : ''}>Return / odds (high→low)</option>
        </select>
      </div>
      <span style="font-size:var(--fs-xs);color:var(--tx-4);margin-left:auto">${ACCA_RISK_INFO[accaRisk].blurb}${_accaBusy ? ' · updating…' : ''}</span>
    </div>`;
}

const MARKET_LABELS = { h2h: 'Match Result', totals: 'Goals Over/Under', spreads: 'Asian Handicap' };

function accaMarketsNote() {
  const have = accaMarkets.length
    ? accaMarkets.map(m => MARKET_LABELS[m] || m).join(' · ')
    : 'Match Result';
  const handicapMissing = !accaMarkets.includes('spreads');
  const note = handicapMissing
    ? `<span style="color:var(--amber)">⚠ Asian handicaps (e.g. +2) aren't posted by the bookmakers this far out — they'll be folded into accas automatically as books publish them closer to kick-off.</span>`
    : `<span style="color:var(--green)">✓ incl. Asian handicaps</span>`;
  return `<div style="font-size:var(--fs-xs);color:var(--tx-3)">
            Markets in current odds feed: <strong style="color:var(--tx-2)">${have}</strong> · ${note}
          </div>`;
}

function accaLegendHTML() {
  return `<div style="font-size:var(--fs-xs);color:var(--tx-4);line-height:1.5">
    💡 Odds are <strong style="color:var(--tx-3)">decimal</strong>: e.g. <strong style="color:var(--tx-3)">1.04</strong> means a €100 bet returns €104
    (just €4 profit) — a very strong favourite, ~96% to win. A leg at 2.00 doubles your money (~50%); 5.00 returns 5× (~20%).
    <em>Hover any underlined figure for a plain-English explanation.</em>
  </div>`;
}

/* ---------------- render: singles + accas ---------------- */

function switchBetsTab(tab) {
  betsSubTab = tab;
  // keep the Markets pills in sync (singles | accas)
  document.querySelectorAll('#tab-markets .subnav .pill').forEach(p => {
    p.classList.toggle('active', (tab === 'singles' && p.dataset.mkt === 'singles') || (tab === 'parlays' && p.dataset.mkt === 'accas'));
  });
  document.querySelectorAll('#markets-toolbar .singles-only').forEach(el => {
    el.style.display = tab === 'singles' ? '' : 'none';
  });
  renderBets();
}

function renderBets() {
  const panel = document.getElementById('bets-panel');
  if (!panel) return;
  if (!allSingles.length && !allParlays.length && !allMatches.length) {
    panel.innerHTML = _dataLoaded ? noOddsState() : skeletonCards(3);
    return;
  }

  const book  = chosenBook();
  const stake = chosenStake();
  const confFilter   = document.getElementById('conf-filter').value;
  const marketFilter = document.getElementById('market-filter').value;
  const allowedConf  = confFilter === 'all' ? ['high', 'medium', 'low'] : confFilter.split(',');

  const singles = allSingles.filter(s =>
    allowedConf.includes(s.confidence) &&
    (marketFilter === 'all' || s.market === marketFilter) &&
    (accaRound === '' || (s.round && s.round.label === accaRound))
  );
  const parlays = [...allParlays].sort((a, b) =>
    accaSort === 'return' ? b.combined_price - a.combined_price
                          : b.combined_fair - a.combined_fair);

  if (betsSubTab === 'parlays') {
    const body = !parlays.length
      ? emptyState('🎰', `No accumulators clear the ${accaRisk} threshold${accaGuard ? ' with the value guard on' : ''}`,
          'Try a punchier risk level, turn the value guard off, or refresh for more data.')
      : parlays.map(p => parlayHTML(p, book, stake)).join('');
    panel.innerHTML = `
      <div class="section-title">High-Probability Accumulators
        <small>${parlays.length} slip${parlays.length !== 1 ? 's' : ''}, ranked by chance of landing · ${book === 'best' ? 'best available price' : esc(book)}</small>
      </div>
      ${recommendedAccaHTML(allParlays, book, stake)}
      ${collapsibleBanner('acca-ev-warn',
        '⚠ Accumulators are −EV — expected to lose money long-term.',
        `⚠ <strong>Accumulators are −EV — expected to lose money long-term.</strong> Combining legs multiplies the bookmaker's margin, so every slip here carries negative expected value (see the red EV on each card). These are for entertainment — stake small. Priced on <strong>sportsbooks only</strong> (you can't place an acca on the Betfair Exchange) — pick a single book above rather than "Best available". The genuine edge is in <button class="linklike" onclick="switchMarketsTab('singles')">Value Singles →</button>`,
        'note--warn')}
      ${accaControlsHTML()}
      ${accaMarketsNote()}
      ${accaLegendHTML()}
      ${body}`;
  } else {
    if (!singles.length) {
      panel.innerHTML = emptyState('📈', 'No value singles under the current filters',
        `Loosen the confidence filter, switch Market to <b>All markets</b>, or <button class="linklike" onclick="loadData(true)">refresh the odds</button>.`);
      return;
    }
    // Reliable edges first; speculative longshots demoted to the bottom.
    const ranked = [...singles].sort((a, b) => {
      const da = edgeReliable(a) ? 0 : 1, db = edgeReliable(b) ? 0 : 1;
      return da !== db ? da - db : b.edge - a.edge;
    });
    const solid = ranked.filter(edgeReliable).length;
    panel.innerHTML = `
      <div class="section-title">Value Singles — positive-edge candidates
        <small>${ranked.length} where the price beats fair (${solid} solid, ${ranked.length - solid} speculative) · ${book === 'best' ? 'best available price' : esc(book)}</small>
      </div>
      ${collapsibleBanner('singles-maths-info',
        '✅ What the numbers say — candidates, not endorsements.',
        `✅ <strong>What the numbers say — candidates, not endorsements.</strong> Each one's best price beats the de-vigged fair probability (positive edge). Small edges on long-odds outcomes are greyed out as <em>speculative</em> (within the model's margin of error). For the football view, see <button class="linklike" onclick="switchView('best'); switchBestTab('writeups')">Analyst Writeups →</button>; bets marked <span style="color:var(--green)">★ Both agree</span> are the strongest.`,
        'note--good')}
      ${ranked.map(s => singleHTML(s, book, stake)).join('')}`;
  }
}

function singleHTML(s, book, stake, opts = {}) {
  const context = opts.context || 'maths';   // 'maths' | 'analyst'
  const { price, bookLabel, fallback } = priceForBook(s, book);
  const grossReturn = stake * price;
  const profit = grossReturn - stake;
  const mktLabel = s.market === 'totals' ? 'Over/Under' : s.market === 'spreads' ? 'Handicap' : '1X2';

  // Intel may arrive after the odds payload — fall back to the intel map.
  const intel = s.intel || allIntel[s.match] || allIntel[normalizeMatchLabel(s.match)] || null;
  let confirmed = s.analyst_confirms;
  if (confirmed === undefined || confirmed === null) confirmed = analystConfirms(s, intel);

  const reliable = edgeReliable(s);
  const speculative = !reliable;

  const overlapBadge = confirmed === true
    ? `<span class="badge badge--green" title="The maths and the analyst both like this — the strongest signal.">★ Both agree</span>` : '';
  const analystBadge = confirmed === true
    ? `<span class="badge badge--green">✓ Analyst backed</span>`
    : confirmed === false
    ? `<span class="badge badge--amber">⚠ Analyst prefers other outcome</span>`
    : '';

  const confBadge = speculative
    ? `<span class="badge" title="Edge (+${s.edge.toFixed(1)}%) is small relative to the long price (${(s.best_price || 0).toFixed(2)}) — within the model's margin of error, so treat as noise, not value.">Speculative · longshot</span>`
    : `<span class="badge badge--${s.confidence === 'high' ? 'green' : s.confidence === 'medium' ? 'amber' : 'ghost'}">${s.confidence.charAt(0).toUpperCase() + s.confidence.slice(1)}</span>`;

  const edgeBadge = `<span class="badge ${reliable || context === 'analyst' ? 'badge--green badge--ghost' : 'badge--ghost'}">edge +${s.edge.toFixed(1)}%</span>`;
  const topRight = context === 'analyst'
    ? `${analystBadge}${edgeBadge}`
    : `${confBadge}${edgeBadge}${overlapBadge}`;

  const fallbackNote = fallback
    ? `<span style="color:var(--amber);font-size:var(--fs-xs)"> ⚠ not at ${esc(book)}, using ${esc(bookLabel)}</span>` : '';

  const kalLine  = s.kalshi != null ? `<span style="color:var(--tx-3)">Kalshi <b style="color:var(--blue)">${s.kalshi}%</b></span>` : '';
  const polyLine = s.poly   != null ? `<span style="color:var(--tx-3)">Poly <b style="color:var(--blue)">${s.poly}%</b></span>` : '';

  return `<div class="bet-card${speculative && context !== 'analyst' ? ' demoted' : ''}">
    <div class="bet-card__top">
      <div style="min-width:0">
        <div class="bet-card__pick">${fmtPick(s.outcome)} <span class="vs">— ${fmtLabel(s.match)}</span></div>
        <div class="bet-card__meta">${fmt(s.commence)} · ${mktLabel}${s.round ? ` · <span style="color:var(--cyan)">${esc(s.round.label)}</span>` : ''}</div>
        ${weatherFlagHTML(s)}
      </div>
      <div class="bet-card__right">${topRight}</div>
    </div>
    <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:var(--fs-sm);color:var(--tx-2)">
      <span>Price <b style="color:var(--green)">${price.toFixed(2)}</b> <span style="color:var(--tx-4);font-size:var(--fs-xs)">(${esc(bookLabel)})</span>${fallbackNote}</span>
      <span>Book fair <b>${(s.fair_prob * 100).toFixed(1)}%</b></span>
      ${kalLine}${polyLine}
    </div>
    <div class="money-strip">
      <div class="money-cell">
        <div class="money-lbl">Expected value (the number that matters)</div>
        ${evMoneyHTML(s.fair_prob, price, stake)}
      </div>
      <div class="money-cell">
        <div class="money-lbl">Stake</div>
        <div class="money-val">${eur(stake)}</div>
      </div>
      <div class="money-cell">
        <div class="money-lbl">Returns if it wins</div>
        <div class="money-val" style="color:var(--tx-3)">${eur(grossReturn)} <span style="font-size:var(--fs-xs)">(+${eur(profit)})</span></div>
      </div>
    </div>
    <div style="font-size:var(--fs-xs);color:var(--tx-3);background:var(--bg-2);border-radius:var(--radius-sm);padding:8px 12px;line-height:1.5">${buildWhy(s)}</div>
    ${intelHTML(intel)}
  </div>`;
}

function buildWhy(s) {
  const parts = [];
  parts.push(`De-vigged consensus fair prob <strong>${(s.fair_prob * 100).toFixed(1)}%</strong> vs best price implied <strong>${(1 / s.best_price * 100).toFixed(1)}%</strong> — <strong>+${s.edge.toFixed(1)}% price edge</strong>.`);
  if (s.pm_gap !== null && s.pm_gap !== undefined) {
    if (s.pm_gap < -2)
      parts.push(`Kalshi/Polymarket price this side <strong>${Math.abs(s.pm_gap).toFixed(1)}%</strong> higher than the books — prediction markets confirm the value.`);
    else if (s.pm_gap > 2)
      parts.push(`<strong>Warning:</strong> Prediction markets price this side <strong>${s.pm_gap.toFixed(1)}%</strong> <em>lower</em> than the books — the price edge may be misleading.`);
    else
      parts.push(`Prediction markets broadly agree with bookmaker consensus.`);
  } else {
    parts.push(`No prediction market data — price signal from bookmaker consensus only.`);
  }
  return parts.join(' ');
}

/* ---------------- recommended acca (analyst-backed headline slip) ---------------- */

function recommendedAccaHTML(parlays, book, stake) {
  // Analyst-confirmed singles pool (ignores EV — analyst signal is the gate)
  const confirmedSingles = allSingles.filter(s => {
    const intel = s.intel || allIntel[s.match] || allIntel[s.match.split(' vs ').reverse().join(' vs ')];
    if (!intel) return false;
    return analystConfirms(s, intel) === true;
  });

  // Top 2-4 legs: earliest round first, then by fair_prob, no duplicate matches
  const seen = new Set();
  const legs = [];
  [...confirmedSingles]
    .sort((a, b) => {
      const rA = (a.round || {}).order || 99;
      const rB = (b.round || {}).order || 99;
      if (rA !== rB) return rA - rB;
      return (b.fair_prob || 0) - (a.fair_prob || 0);
    })
    .forEach(s => {
      if (legs.length >= 4 || seen.has(s.match)) return;
      seen.add(s.match);
      legs.push(s);
    });

  if (legs.length < 2) {
    const hasIntel = Object.keys(allIntel).length > 0;
    return `<div class="card"><div class="card__body" style="font-size:var(--fs-sm);color:var(--tx-3)">
      <div style="font-size:var(--fs-xs);font-weight:700;color:var(--tx-1);letter-spacing:.04em;margin-bottom:6px">⭐ RECOMMENDED ACCA</div>
      ${hasIntel ? 'No acca found where the analyst backs multiple legs — check back as more intel loads.' : '⏳ Analyst intel loading — recommended acca will appear shortly.'}
    </div></div>`;
  }

  const slipBook = book === 'best' ? 'best' : book;
  let combinedPrice = 1;
  const legData = legs.map(s => {
    const { price, bookLabel } = priceForBook(s, slipBook);
    combinedPrice *= price;
    return { match: s.match, outcome: s.outcome, commence: s.commence, round: s.round, usedPrice: price, usedBook: bookLabel };
  });

  // Best single book that prices all legs
  const allBooksList = [...new Set(legs.flatMap(s => Object.keys(s.per_book || {})))];
  let bestBook = slipBook !== 'best' ? slipBook : (legData[0]?.usedBook || 'your bookmaker');
  if (slipBook === 'best') {
    const bookTotals = allBooksList.map(bk => {
      const prices = legs.map(s => (s.per_book || {})[bk]);
      if (!prices.every(p => p > 0)) return null;
      return { bk, combined: prices.reduce((a, b) => a * b, 1) };
    }).filter(Boolean);
    if (bookTotals.length) bestBook = bookTotals.sort((a, b) => b.combined - a.combined)[0].bk;
  }

  const grossReturn = stake * combinedPrice;
  const fairProb = legs.reduce((p, s) => p * (s.fair_prob != null ? s.fair_prob : 0.5), 1);
  // True EV per unit stake = fair prob × price − 1
  const evRaw = (fairProb * combinedPrice - 1) * 100;

  const pickLabel = (l) => {
    const teams = l.match.split(' vs ');
    const home = teams[0], away = teams[1] || '';
    return l.outcome === 'draw' ? 'Draw'
      : l.outcome === home?.toLowerCase() ? titleCase(home)
      : l.outcome === away?.toLowerCase() ? titleCase(away)
      : titleCase(l.outcome);
  };

  const whyHTML = legData.map(l => {
    const intel = allIntel[l.match] || allIntel[l.match.split(' vs ').reverse().join(' vs ')];
    const outcome = pickLabel(l);
    if (!intel) return `<div style="margin-bottom:4px;color:var(--tx-2);font-size:var(--fs-sm)">★ ${esc(outcome)} (${fmtLabel(l.match)})</div>`;
    const teams = l.match.split(' vs ');
    const home = teams[0], away = teams[1] || '';
    const recs = (intel.recommended_bets || []);
    const matchingRec = recs.find(r => {
      const ro = (r.outcome || '').toLowerCase();
      return ro === 'home_win' ? l.outcome === home?.toLowerCase()
           : ro === 'away_win' ? l.outcome === away?.toLowerCase()
           : ro === 'draw'     ? l.outcome === 'draw'
           : false;
    });
    const reason = matchingRec?.rationale || matchingRec?.reasoning || intel.overall_summary || '';
    const shortReason = reason.split('.')[0];
    return `<div style="margin-bottom:4px;color:var(--tx-2);font-size:var(--fs-sm)">★ <strong>${esc(outcome)}</strong> (${fmtLabel(l.match)}): ${esc(shortReason)}.</div>`;
  }).join('');

  const legsHTML = legData.map(l => `
    <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid var(--line-1)">
      <div>
        <div style="font-weight:700;color:var(--tx-1)">${esc(pickLabel(l))}</div>
        <div style="font-size:var(--fs-xs);color:var(--tx-3)">${fmtLabel(l.match)}${l.round ? ' · ' + esc(l.round.label.replace('Group Stage ', '')) : ''} · ${fmt(l.commence)}</div>
      </div>
      <div style="text-align:right">
        <div style="font-weight:700;color:var(--green);font-size:1.05rem">${l.usedPrice.toFixed(2)}</div>
        <div style="font-size:var(--fs-xs);color:var(--tx-3)">${esc(l.usedBook)}</div>
      </div>
    </div>`).join('');

  const bookUrl = BOOK_URLS[bestBook] || 'https://www.paddypower.com';

  const legLines = legData.map(l => `${pickLabel(l)} @ ${l.usedPrice.toFixed(2)} (${titleCase(l.match)})`).join('\n');
  const waMsg = `⭐ WC 2026 Recommended Acca\n\n${legLines}\n\nCombined: ${combinedPrice.toFixed(2)}\nStake €${stake} → Returns €${grossReturn.toFixed(2)}\n\nBuilt with WC Edge Finder`;

  return `<div class="card" style="border-color:#1d5733">
    <div class="card__body">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
        <span style="font-size:var(--fs-xs);font-weight:700;color:var(--green);letter-spacing:.04em">⭐ RECOMMENDED ACCA</span>
        <span class="badge">${legData.length}-leg · ${(fairProb * 100).toFixed(1)}% chance · ${combinedPrice.toFixed(2)} odds</span>
        <span class="badge ${evRaw >= 0 ? 'badge--green' : 'badge--red'}">EV ${evRaw >= 0 ? '+' : ''}${evRaw.toFixed(1)}%</span>
      </div>
      <div style="font-size:var(--fs-sm);color:var(--tx-3);margin-bottom:10px">Every leg is backed by the analyst. Here's why:</div>
      ${whyHTML}
      ${legsHTML}
    </div>
    <div class="card__foot">
      <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:12px;align-items:center">
        <div class="money-cell"><div class="money-lbl">Expected value</div>${evMoneyHTML(fairProb, combinedPrice, stake, '0.95rem')}</div>
        <div class="money-cell"><div class="money-lbl">Stake</div><div class="money-val" style="color:var(--tx-1)">${eur(stake)}</div></div>
        <div class="money-cell"><div class="money-lbl">Combined odds</div><div class="money-val" style="color:var(--tx-1)">${combinedPrice.toFixed(2)}</div></div>
        <div class="money-cell"><div class="money-lbl">Returns if wins</div><div class="money-val">${eur(grossReturn)}</div></div>
      </div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <a class="btn btn--primary" href="${esc(bookUrl)}" target="_blank" rel="noopener">🏦 Place at ${esc(bestBook)}</a>
        <a class="btn btn--wa" href="https://wa.me/?text=${encodeURIComponent(waMsg)}" target="_blank" rel="noopener">📲 Share on WhatsApp</a>
      </div>
    </div>
  </div>`;
}

/* ---------------- parlay cards ---------------- */

function parlayHTML(p, book, stake) {
  let combinedPrice = 1;
  let anyFallback = false;

  // An acca is placed on ONE book. In "best" mode use the single best book for
  // the whole slip (server-computed acca_book), not a different book per leg.
  const slipBook = (book === 'best') ? (p.acca_book || 'best') : book;
  const legData = p.legs.map(l => {
    const { price, bookLabel, fallback } = priceForBook(l, slipBook);
    combinedPrice *= price;
    if (fallback) anyFallback = true;
    return { ...l, usedPrice: price, usedBook: bookLabel, fallback };
  });

  const grossReturn = stake * combinedPrice;
  const profit = grossReturn - stake;
  const fairProb = p.combined_fair / 100;
  const impliedProb = 1 / combinedPrice;
  // True EV per unit stake (recomputed — the price depends on the chosen book)
  const evRaw = (fairProb * combinedPrice - 1) * 100;
  const evTxt = Math.abs(evRaw) < 0.1 ? evRaw.toFixed(2) : evRaw.toFixed(1);

  const legs = legData.map(l => {
    const fallNote = l.fallback ? `<span style="color:var(--amber);font-size:var(--fs-xs)">⚠ ${esc(l.usedBook)}</span>` : '';
    const impl = (100 / l.usedPrice).toFixed(0);
    const ret = eur(stake * l.usedPrice);
    const priceTip = `Decimal odds at ${l.usedBook}: ${l.usedPrice.toFixed(2)}.\n`
      + `• Implied chance ≈ ${impl}% (= 1 ÷ ${l.usedPrice.toFixed(2)}).\n`
      + `• A winning ${l.usedPrice.toFixed(2)} leg multiplies your stake by ${l.usedPrice.toFixed(2)} (on its own, ${eur(stake)} → ${ret}).\n`
      + `The lower the number, the bigger the favourite.`;
    return `<div class="parlay-leg">
      <div style="min-width:0">
        <div><strong title="Your selection for this match">${fmtPick(l.outcome)}</strong></div>
        <div style="font-size:var(--fs-xs);color:var(--tx-3)">${fmtLabel(l.match)} · ${fmt(l.commence)}${l.round ? ` · <span style="color:var(--cyan);font-weight:600">${esc(l.round.label.replace('Group Stage ', ''))}</span>` : ''}</div>
        ${weatherFlagHTML(l)}
      </div>
      <div style="display:flex;align-items:center;gap:10px;flex-shrink:0">
        ${fallNote}
        <span style="font-size:var(--fs-xs);color:var(--tx-3)" title="Bookmaker offering this price (best of your accounts, unless you picked a specific book above)">${esc(l.usedBook)}</span>
        <span class="parlay-leg__price help" title="${esc(priceTip)}">${l.usedPrice.toFixed(2)}</span>
      </div>
    </div>`;
  }).join('');

  const fallbackWarning = anyFallback
    ? `<div style="font-size:var(--fs-xs);color:var(--amber);padding:8px 16px;border-top:1px solid var(--line-1)">⚠ One or more legs not available at ${esc(book === 'best' ? 'chosen book' : book)} — best price used instead.</div>`
    : '';
  const mixedWarning = (book === 'best' && p.mixed_books)
    ? `<div style="font-size:var(--fs-xs);color:var(--red);padding:8px 16px;border-top:1px solid var(--line-1)">⚠ No single bookmaker prices all ${p.legs.length} legs — this can't be placed as one acca. Prices shown are best-available per leg.</div>`
    : '';
  const slipBookBadge = (book === 'best' && p.acca_book)
    ? `<span class="badge help" title="The single bookmaker that prices every leg at the best combined odds — place the whole acca here.">@ ${esc(p.acca_book)}</span>`
    : '';

  const evAmt = Math.abs(evRaw / 100 * stake);
  const evLine = evRaw >= 0
    ? `<span class="ev-num pos help" title="Long-run average result per €${stake} staked = (fair chance × combined price − 1) × stake.">Expected gain: +€${evAmt.toFixed(2)} per €${stake}</span>`
    : `<span class="ev-num neg help" title="Long-run average result per €${stake} staked = (fair chance × combined price − 1) × stake. Negative: the bookmaker margin compounds across legs.">Expected cost: −€${evAmt.toFixed(2)} per €${stake}</span>`;

  return `<div class="card">
    <div class="card__head" style="display:block">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
        ${evLine}
        <span class="badge help" title="Accumulator: all ${p.legs.length} selections must win.">${p.legs.length}-leg acca</span>
        ${slipBookBadge}
        ${p.round_label ? `<span class="badge badge--cyan">${esc(p.round_label)}</span>` : ''}
      </div>
      <div style="font-size:var(--fs-xs);color:var(--tx-3);margin-top:6px">
        <span class="help" title="The model's probability that every leg wins.">Model: ${p.combined_fair.toFixed(1)}% to land</span>
        · <span class="help" title="= 1 ÷ combined price">Price implies: ${(impliedProb * 100).toFixed(1)}%</span>
        · <span class="help" title="Expected value per stake = fair chance × combined price − 1.">EV ${evRaw >= 0 ? '+' : ''}${evTxt}%</span>
      </div>
      <div class="money-strip" style="margin-top:10px;background:var(--bg-1)">
        <div class="money-cell"><div class="money-lbl help" title="The amount you'd put on this acca. Change it in the Stake box above.">Stake</div><div class="money-val" style="color:var(--tx-1)">${eur(stake)}</div></div>
        <div class="money-cell"><div class="money-lbl help" title="All the leg odds multiplied together (${legData.map(l => l.usedPrice.toFixed(2)).join(' × ')}).">Combined price</div><div class="money-val" style="color:var(--tx-1)">${combinedPrice.toFixed(2)}</div></div>
        <div class="money-cell"><div class="money-lbl help" title="What you get back if every leg wins = stake × combined price (includes your stake).">Gross return</div><div class="money-val" style="color:var(--tx-1)">${eur(grossReturn)}</div></div>
        <div class="money-cell"><div class="money-lbl help" title="Your winnings = gross return minus your stake.">Profit if wins</div><div class="money-val" style="color:var(--green)">+${eur(profit)}</div></div>
      </div>
    </div>
    <div>${legs}</div>
    ${mixedWarning}
    ${fallbackWarning}
  </div>`;
}

/* ---------------- acca builder (fixtures) ---------------- */

let _fixtureRound = 'R1';
const _fixtureLeg = new Map();  // matchId -> {legId, ocKey, single}

function setFixtureRound(r) {
  _fixtureRound = r;
  document.querySelectorAll('#builder-wrap .pill[data-round]').forEach(b => b.classList.toggle('active', b.dataset.round === r));
  renderFixtures();
}

function toggleFixtureLeg(matchId, ocKey, singleObj) {
  const existing = _fixtureLeg.get(matchId);
  if (existing && existing.ocKey === ocKey) {
    _fixtureLeg.delete(matchId);   // clicking same button again = deselect
  } else {
    _fixtureLeg.set(matchId, { legId: matchId + '|' + ocKey, ocKey, single: singleObj });
  }
  renderFixtures();
  renderFixtureAcca();
}

function clearFixtureAcca() {
  _fixtureLeg.clear();
  renderFixtures();
  renderFixtureAcca();
}

function renderFixtures() {
  const grid = document.getElementById('fixtures-grid');
  if (!grid) return;
  if (!allMatches.length) { grid.innerHTML = _dataLoaded ? noOddsState() : skeletonCards(4); return; }

  const rLabel = 'Group Stage ' + _fixtureRound;
  const now = Date.now();
  const filtered = allMatches
    .filter(m => m.round && m.round.label === rLabel)
    .sort((a, b) => (a.commence || '').localeCompare(b.commence || ''));

  if (!filtered.length) {
    grid.innerHTML = emptyState('🎰', `No matches found for ${_fixtureRound}`, 'Books may not have priced this round yet.');
    return;
  }

  grid.innerHTML = filtered.map(m => {
    const matchId = m.label;
    const [mHome, mAway] = m.label.includes(' vs ') ? m.label.split(' vs ') : [m.label, ''];
    const isPast = m.commence && (new Date(m.commence).getTime() < now);
    const sel = _fixtureLeg.get(matchId);

    const homeKey = mHome.toLowerCase();
    const awayKey = mAway.toLowerCase();
    const cols = [
      { ocKey: homeKey, label: mHome },
      { ocKey: 'draw',  label: 'Draw' },
      { ocKey: awayKey, label: mAway },
    ];

    const btns = cols.map(({ ocKey, label }) => {
      const od = (m.outcomes || []).find(o => o.outcome === ocKey);
      const price = od?.best_price ? od.best_price.toFixed(2) : '—';
      const isSel = sel?.ocKey === ocKey;
      if (!od?.best_price) {
        return `<div style="min-width:60px;padding:7px 10px;text-align:center;opacity:0.35">
          <span style="display:block;font-size:0.66rem;color:var(--tx-3)">${esc(titleCase(label))}</span>
          <span style="display:block;font-size:var(--fs-xs);color:var(--tx-4)">No market</span>
        </div>`;
      }
      const single = {
        match: matchId, outcome: label, market: 'h2h',
        fair_prob: od ? (od.book_fair || 0) / 100 : 0,
        best_price: od?.best_price ?? null,
        best_book: od?.best_book ?? null,
        per_book: od?.per_book ?? {},
      };
      const enc = JSON.stringify(single).replace(/"/g, '&quot;');
      const click = isPast ? '' : ` onclick="toggleFixtureLeg('${matchId.replace(/'/g, "\\'")}','${ocKey}',${enc})"`;
      return `<button class="fix-outcome-btn${isSel ? ' selected' : ''}"${isPast ? ' disabled' : ''}${click}>
        <span class="fix-label">${esc(titleCase(label))}</span>
        <span class="fix-price">${price}</span>
      </button>`;
    }).join('');

    const kick = (() => {
      if (!m.commence) return '';
      const d = new Date(m.commence);
      const h = (d.getTime() - now) / 36e5;
      if (h < -1) return '<span style="color:var(--tx-4)">FT</span>';
      if (h < 0)  return '<span style="color:var(--red)">Live</span>';
      const t = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      const day = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(new Date().getFullYear(), new Date().getMonth(), new Date().getDate())) / 86400000);
      if (day === 0) return `<span style="color:var(--amber)">Today ${t}</span>`;
      if (day === 1) return `<span style="color:var(--tx-3)">Tomorrow ${t}</span>`;
      return `<span style="color:var(--tx-4)">${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${t}</span>`;
    })();

    return `<div class="fix-row${isPast ? ' past' : ''}${sel ? ' selected-row' : ''}">
      <div class="fix-match-info">
        <div class="fix-match-name">${esc(titleCase(mHome))} <span style="color:var(--tx-4);font-weight:400">v</span> ${esc(titleCase(mAway))}</div>
        <div class="fix-match-time">${kick}</div>
      </div>
      <div class="fix-btns">${btns}</div>
    </div>`;
  }).join('');
}

function renderFixtureAcca() {
  const legs = [..._fixtureLeg.values()];
  const legsEl = document.getElementById('fix-acca-legs');
  const summary = document.getElementById('fix-acca-summary');
  const countEl = document.getElementById('fix-leg-count');
  if (!legsEl) return;

  if (countEl) countEl.textContent = legs.length || '0';

  if (!legs.length) {
    legsEl.innerHTML = '<div style="font-size:var(--fs-xs);color:var(--tx-4);text-align:center;padding:28px 16px;line-height:1.6">Tap any odds button<br>to add it to your betslip</div>';
    if (summary) summary.style.display = 'none';
    document.getElementById('fix-acca-odds-header').textContent = '';
    return;
  }

  legsEl.innerHTML = legs.map(({ ocKey, single }) => {
    const price = single.best_price ? single.best_price.toFixed(2) : '—';
    const enc = JSON.stringify(single).replace(/"/g, '&quot;');
    const safeMatch = single.match.replace(/\\/g, '\\\\').replace(/'/g, "\\'");

    // Analyst verdict for this leg
    const intel = allIntel[single.match] || allIntel[single.match.split(' vs ').reverse().join(' vs ')];
    const confirms = intel ? analystConfirms(single, intel) : null;
    let analystLine = '';
    if (!intel) {
      analystLine = `<div style="font-size:var(--fs-xs);color:var(--tx-4);margin-top:4px">⏳ Analyst not yet run for this match</div>`;
    } else if (confirms === true) {
      const snippet = intel.overall_summary ? intel.overall_summary.split('.')[0] + '.' : '';
      analystLine = `<div style="font-size:var(--fs-xs);color:var(--green);margin-top:4px">★ Analyst backs this pick${snippet ? ' — ' + esc(snippet) : ''}</div>`;
    } else if (confirms === false) {
      const recs = (intel.recommended_bets || []).map(r => r.outcome).filter(Boolean).join(', ');
      analystLine = `<div style="font-size:var(--fs-xs);color:var(--amber);margin-top:4px">⚠ Analyst prefers: ${esc(recs) || 'a different outcome'}</div>`;
    } else {
      const snippet = intel.overall_summary ? intel.overall_summary.split('.')[0] + '.' : '';
      analystLine = `<div style="font-size:var(--fs-xs);color:var(--tx-4);margin-top:4px">${esc(snippet) || 'Analyst has no 1X2 recommendation for this match'}</div>`;
    }

    return `<div class="slip__leg">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:6px">
        <div style="flex:1;min-width:0">
          <div style="display:flex;align-items:center;gap:5px;margin-bottom:2px">
            <span style="color:var(--green);font-size:var(--fs-xs)">✓</span>
            <span style="font-size:var(--fs-md);font-weight:700;color:var(--tx-1)">${esc(titleCase(single.outcome))}</span>
          </div>
          <div style="font-size:var(--fs-xs);color:var(--tx-4)">${fmtLabel(single.match)}</div>
          ${analystLine}
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
          <span style="font-size:0.95rem;font-weight:700;color:var(--tx-2)">${price}</span>
          <button class="btn btn--quiet btn--sm" onclick="toggleFixtureLeg('${safeMatch}','${ocKey}',${enc})" title="Remove leg">✕</button>
        </div>
      </div>
    </div>`;
  }).join('');

  if (summary) summary.style.display = 'block';

  const singles = legs.map(l => l.single);
  const stake = parseFloat(document.getElementById('fix-stake')?.value) || 10;
  const fairCombo = singles.reduce((p, s) => p * (s.fair_prob || 0), 1);

  // Per-bookmaker combined odds (only books that price ALL legs)
  const allBooksSet = new Set(singles.flatMap(s => Object.keys(s.per_book || {})));
  const bookOdds = [];
  allBooksSet.forEach(bk => {
    const prices = singles.map(s => s.per_book?.[bk]);
    if (prices.every(p => p > 0)) bookOdds.push({ bk, combined: prices.reduce((a, b) => a * b, 1) });
  });
  bookOdds.sort((a, b) => b.combined - a.combined);

  const best = bookOdds[0] || null;
  const bestOdds = best?.combined || 0;
  const bestBook = best?.bk || null;

  const oddsStr = bestOdds > 0 ? bestOdds.toFixed(2) : '—';
  document.getElementById('fix-acca-odds-header').textContent = bestOdds > 0 ? `· Acca ${oddsStr}` : '';
  document.getElementById('fix-acca-odds').textContent = oddsStr;
  document.getElementById('fix-acca-return').textContent = bestOdds > 0 ? `€${(stake * bestOdds).toFixed(2)}` : '—';

  // True EV per stake = fair combined prob × combined price − 1
  const ev = (fairCombo > 0 && bestOdds > 0) ? ((fairCombo * bestOdds - 1) * 100).toFixed(1) : null;
  const evEl = document.getElementById('fix-acca-ev');
  if (ev !== null) {
    const c = parseFloat(ev) >= 0 ? 'var(--green)' : 'var(--red)';
    const evAmt = parseFloat(ev) / 100 * stake;
    evEl.innerHTML = `<span style="color:${c};font-weight:700">EV ${evAmt >= 0 ? '+' : '−'}€${Math.abs(evAmt).toFixed(2)} (${parseFloat(ev) >= 0 ? '+' : ''}${ev}%)</span> <span style="color:var(--tx-4)">· fair chance ${(fairCombo * 100).toFixed(1)}%</span>`;
  } else { evEl.textContent = ''; }

  // Bookmaker comparison
  const bookEl = document.getElementById('fix-acca-book');
  if (!bookOdds.length) {
    bookEl.innerHTML = legs.length > 1
      ? '<span style="color:var(--amber)">No single bookmaker prices all your selections — try removing a leg</span>'
      : '';
  } else {
    bookEl.innerHTML = `
      <div style="font-size:var(--fs-xs);color:var(--tx-4);margin-bottom:6px;text-transform:uppercase;letter-spacing:.05em">Where to place it</div>
      ${bookOdds.map((b, i) => {
        const ret = (stake * b.combined).toFixed(2);
        const isBest = i === 0;
        return `<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 9px;border-radius:6px;margin-bottom:3px;background:${isBest ? 'var(--green-bg)' : 'var(--bg-2)'};border:1px solid ${isBest ? '#1d5733' : 'var(--line-1)'}">
          <span style="font-size:var(--fs-xs);color:${isBest ? 'var(--green)' : 'var(--tx-3)'};font-weight:${isBest ? '600' : '400'}">${isBest ? '★ ' : ''}${esc(b.bk)}</span>
          <div style="text-align:right">
            <span style="font-size:var(--fs-sm);font-weight:700;color:${isBest ? 'var(--tx-1)' : 'var(--tx-2)'}">${b.combined.toFixed(2)}</span>
            <span style="font-size:var(--fs-xs);color:var(--tx-4);margin-left:5px">→ €${ret}</span>
          </div>
        </div>`;
      }).join('')}`;
  }

  document.getElementById('fix-acca-nobook').textContent = '';

  const actionsEl = document.getElementById('fix-acca-actions');
  if (actionsEl) actionsEl.style.display = legs.length >= 2 ? 'flex' : 'none';

  // WhatsApp share
  const waBtn = document.getElementById('fix-whatsapp-btn');
  if (waBtn && legs.length >= 2) {
    const legLines = legs.map(({ single }) => {
      const price = single.best_price ? single.best_price.toFixed(2) : '—';
      return `✓ ${titleCase(single.outcome)} — ${titleCase(single.match)} @ ${price}`;
    }).join('\n');
    const ret = bestOdds > 0 ? (stake * bestOdds).toFixed(2) : '—';
    const msg = `🏆 WC 2026 Acca${bestBook ? ` (${bestBook})` : ''}\n\n${legLines}\n\nCombined: ${oddsStr}\nStake €${stake} → Returns €${ret}\n\nBuilt with WC Edge Finder`;
    waBtn.href = `https://wa.me/?text=${encodeURIComponent(msg)}`;
  }

  // Bookmaker link
  const bookBtn = document.getElementById('fix-bookie-btn');
  const bookLabel = document.getElementById('fix-bookie-label');
  if (bookBtn && bestBook) {
    bookBtn.href = BOOK_URLS[bestBook] || 'https://www.google.com/search?q=' + encodeURIComponent(bestBook);
    if (bookLabel) bookLabel.textContent = `Open ${bestBook}`;
  }
}

/* ---------------- market divergence ---------------- */

function onThreshold() {
  threshold = parseFloat(document.getElementById('threshold').value);
  document.getElementById('threshold-val').textContent = threshold + '%';
  renderDivergence();
}

function renderDivergence() {
  const container = document.getElementById('matches');
  if (!container) return;
  if (!allMatches.length) { container.innerHTML = _dataLoaded ? noOddsState() : skeletonCards(4); return; }

  const sortBy = document.getElementById('sort-select').value;
  const pmOnly = document.getElementById('pm-filter').value === 'pm';

  let list = allMatches.filter(m => {
    if (pmOnly && !m.has_pm_data) return false;
    if (Math.abs(m.max_gap) < threshold) return false;
    return true;
  });

  if (sortBy === 'time') list.sort((a, b) => a.commence.localeCompare(b.commence));
  else list.sort((a, b) => Math.abs(b.max_gap) - Math.abs(a.max_gap));

  if (!list.length) {
    container.innerHTML = emptyState('🔍', 'No matches meet the current filters', 'Lower the minimum gap or show all matches.');
    return;
  }
  container.innerHTML = list.map(m => matchCardHTML(m)).join('');
}

function matchCardHTML(m) {
  const gap = m.max_gap;
  const isLong = gap > 2;
  const isShort = gap < -2;

  const cardCls = 'card' + (isLong ? ' flag-long' : isShort ? ' flag-short' : '');
  const badgeCls = isLong ? 'badge badge--red' : isShort ? 'badge badge--green' : 'badge';
  const badgeTxt = Math.abs(gap) > 0
    ? (gap > 0 ? '+' : '') + gap.toFixed(1) + '% gap'
    : 'no PM data';

  const rows = m.outcomes.map(o => {
    const diff = o.diff;
    const hasDiff = diff !== null;
    const diffCls = !hasDiff ? 'diff-neutral' : diff > 2 ? 'diff-long' : diff < -2 ? 'diff-short' : 'diff-neutral';
    const barCls = !hasDiff ? 'bar-neutral' : diff > 2 ? 'bar-long' : diff < -2 ? 'bar-short' : 'bar-neutral';
    const barW = hasDiff ? Math.min(Math.abs(diff) / 10 * 100, 100) : 0;
    const diffTxt = hasDiff ? (diff > 0 ? '+' : '') + diff.toFixed(1) + '%' : '—';
    const polyTxt = o.poly != null ? o.poly.toFixed(1) + '%' : '<span class="pm-missing">—</span>';
    const kalTxt = o.kalshi != null ? o.kalshi.toFixed(1) + '%' : '<span class="pm-missing">—</span>';
    const bestTxt = o.best_price ? o.best_price.toFixed(2) + ' <span style="color:var(--tx-4);font-size:var(--fs-xs)">(' + esc(o.best_book) + ')</span>' : '—';
    const paddyTxt = o.paddy != null ? '<span class="paddy-price">PP ' + o.paddy.toFixed(2) + '</span>' : '';
    const edgeTxt = o.edge != null ? `<span class="${o.edge > 0 ? 'edge-pos' : 'edge-neg'}">${o.edge > 0 ? '+' : ''}${o.edge.toFixed(1)}%</span>` : '<span style="color:var(--tx-4)">—</span>';

    return `<tr>
      <td>${fmtPick(o.outcome)}</td>
      <td>${o.book_fair.toFixed(1)}%</td>
      <td>${polyTxt}</td>
      <td>${kalTxt}</td>
      <td class="diff-cell ${diffCls}">${diffTxt}</td>
      <td class="bar-cell"><div class="bar-wrap"><div class="bar-fill ${barCls}" style="width:${barW}%"></div></div></td>
      <td>${bestTxt} ${paddyTxt}</td>
      <td>${edgeTxt}</td>
    </tr>`;
  }).join('');

  let totalsHTML = '';
  if (m.totals && m.totals.length) {
    const id = 'tot-' + m.label.replace(/\W/g, '');
    const totRows = m.totals.map(t =>
      Object.entries(t.outcomes).map(([name, od]) => {
        const eCls = od.edge > 0 ? 'edge-pos' : 'edge-neg';
        return `<tr>
          <td>${esc(name)} ${t.line}</td>
          <td>${od.fair}%</td>
          <td colspan="3" style="color:var(--tx-4)">no PM data</td>
          <td class="bar-cell"></td>
          <td>${od.best_price ? od.best_price.toFixed(2) + ' <span style="color:var(--tx-4);font-size:var(--fs-xs)">(' + esc(od.best_book) + ')</span>' : '—'}</td>
          <td><span class="${eCls}">${od.edge != null ? (od.edge > 0 ? '+' : '') + od.edge.toFixed(1) + '%' : '—'}</span></td>
        </tr>`;
      }).join('')
    ).join('');
    totalsHTML = `
      <div class="totals-toggle" onclick="toggleTotals('${id}')">
        ▶ Over / Under <span style="color:var(--tx-4)">(tap to expand)</span>
      </div>
      <div class="totals-body" id="${id}">
        <table><thead><tr>
          <th>Outcome</th><th>Book fair</th><th>Poly</th><th>Kalshi</th><th>Diff</th><th></th><th>Best price</th><th>Edge</th>
        </tr></thead><tbody>${totRows}</tbody></table>
      </div>`;
  }

  return `<div class="${cardCls}">
    <div class="card__head">
      <div>
        <div class="match-title">${fmtLabel(m.label)}</div>
        <div class="match-sub">${fmt(m.commence)}</div>
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
        <span class="${badgeCls}">${badgeTxt}</span>
        <span class="badge badge--ghost">margin ${m.margin}%</span>
      </div>
    </div>
    <table>
      <thead><tr>
        <th>Outcome</th><th>Book fair</th><th>Poly</th><th>Kalshi</th><th>Diff</th><th></th><th>Best price</th><th>Edge</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
    ${totalsHTML}
  </div>`;
}

function toggleTotals(id) {
  const el = document.getElementById(id);
  el.classList.toggle('open');
  el.previousElementSibling.innerHTML = el.classList.contains('open')
    ? '▼ Over / Under'
    : '▶ Over / Under <span style="color:var(--tx-4)">(tap to expand)</span>';
}
