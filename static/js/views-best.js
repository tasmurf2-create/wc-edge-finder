/* ============================================================
   views-best.js — Best Bets (analyst-led picks) + Analyst
   Writeups + the multi-select acca tray.
   Analyst = gate (football reasons). Maths = price quality.
   ============================================================ */

function sensibleScore(s) {
  let score = 0; const reasons = [];

  // 1. Edge — how well priced are the odds for this analyst pick?
  if (s.edge == null) {
    reasons.push({ t: 'muted', x: `— no odds data yet` });
  } else if (edgeReliable(s) && s.edge > 2) {
    score += 4;
    reasons.push({ t: 'good', x: `✅ great price — +${s.edge.toFixed(1)}% above fair value (${esc(s.best_book)})` });
  } else if (edgeReliable(s)) {
    score += 2;
    reasons.push({ t: 'good', x: `✅ fair price — +${s.edge.toFixed(1)}% edge (${esc(s.best_book)})` });
  } else if (s.edge > 0) {
    score += 1;
    reasons.push({ t: 'warn', x: `⚠ marginal value — +${s.edge.toFixed(1)}% edge, treat as fair odds` });
  } else {
    reasons.push({ t: 'warn', x: `⚠ odds below fair value (${s.edge.toFixed(1)}%) — shop around` });
  }

  // 2. Kalshi prediction market — does real money agree with the analyst?
  if (s.pm_gap != null) {
    if (s.pm_gap > 1)       { score += 2; reasons.push({ t: 'good', x: `✅ Kalshi agrees — prediction market also backs this (+${s.pm_gap}%)` }); }
    else if (s.pm_gap < -2) { score -= 1; reasons.push({ t: 'warn', x: `⚠ Kalshi less convinced (${s.pm_gap}%) — analyst and market diverge` }); }
    else                    { reasons.push({ t: 'muted', x: `— Kalshi neutral on this outcome` }); }
  } else {
    reasons.push({ t: 'muted', x: `— no Kalshi data for this match` });
  }

  // 3. Weather / conditions
  const w = s.weather;
  if (w) {
    const o = (s.outcome || '').toLowerCase();
    const fav = (w.favours || '').toLowerCase(), dis = (w.disfavours || '').toLowerCase();
    const hits = n => n && (n.includes(o) || o.includes(n));
    if (hits(fav))                                            { score += 1; reasons.push({ t: 'good', x: `🌡️ conditions favour this — ${esc(fmtAltitudeText(w.headline))}` }); }
    else if (hits(dis))                                       { score -= 1; reasons.push({ t: 'warn', x: `🌡️ conditions work against this — ${esc(fmtAltitudeText(w.headline))}` }); }
    else if (w.goals_lean === 'under' && o.includes('under')) { score += 1; reasons.push({ t: 'good', x: `🌡️ heat suits Under` }); }
    else if (w.goals_lean === 'under' && o.includes('over'))  { score -= 1; reasons.push({ t: 'warn', x: `🌡️ heat works against Over` }); }
    else if (w.goals_lean === 'over'  && o.includes('over'))  { score += 1; reasons.push({ t: 'good', x: `⛰️ altitude suits Over` }); }
  }

  // 4. Analyst confidence (from the intel itself)
  const iconf = s.intel?.intel_confidence;
  if (iconf === 'high')        { score += 2; reasons.push({ t: 'good', x: `★ analyst is highly confident in this pick` }); }
  else if (iconf === 'medium') { score += 1; reasons.push({ t: 'good', x: `analyst is moderately confident` }); }
  else if (iconf === 'low')    { reasons.push({ t: 'warn', x: `⚠ analyst confidence is low — treat carefully` }); }

  const tier = score >= 6 ? 'strong' : score >= 3 ? 'solid' : 'speculative';
  return { score, reasons, tier };
}

function populateSensibleRoundFilter() {
  const sel = document.getElementById('sensible-round-filter');
  if (!sel || !roundsAvailable.length) return;
  const cur = sel.value;
  sel.innerHTML = '<option value="">All rounds</option>'
    + roundsAvailable.map(r => `<option value="${esc(r)}">${esc(r)}</option>`).join('');
  if (!cur) {
    // Default to the first round with an upcoming match — the active round
    const now = new Date();
    const activeRound = roundsAvailable.find(r =>
      allMatches.some(m => m.round?.label === r && new Date(m.commence) > now)
    ) || '';
    sel.value = activeRound;
  } else {
    sel.value = cur;
  }
}

function sensibleCardHTML(s, sc, stake, grouped = false) {
  const price = s.best_price, ret = stake * price;
  const mkt = s.market === 'totals' ? 'Over/Under' : s.market === 'spreads' ? 'Handicap' : '1X2';
  const vBadge = verdictBadge(s);
  const ev = evPct(s.fair_prob, s.best_price);

  // Action note — plain English, keyed to the same EV thresholds as the verdict
  const actionNote = (() => {
    if (ev == null) return '';
    const reliable = s.edge != null && edgeReliable(s);
    if (ev >= 2 && reliable) return `<span style="font-size:var(--fs-xs);color:var(--green)">Price beats fair value — a bet, at sensible stakes</span>`;
    if (ev >= 0)  return `<span style="font-size:var(--fs-xs);color:var(--amber)">Roughly fair odds — small stake only if you back the analyst view</span>`;
    if (ev >= -3) return `<span style="font-size:var(--fs-xs);color:var(--blue)">Analyst likes it but the price is short — wait for ${(s.best_price + 0.05).toFixed(2)}+</span>`;
    return `<span style="font-size:var(--fs-xs);color:var(--red)">Odds well below fair value — pass</span>`;
  })();

  const tags = sc.reasons.map(r => `<span class="tag tag--${r.t === 'good' ? 'good' : r.t === 'muted' ? 'muted' : 'warn'}">${r.x}</span>`).join('');
  const reasoning = s.rb_reasoning
    ? `<div style="font-size:var(--fs-sm);color:var(--tx-3);line-height:1.5;border-left:2px solid var(--line-2);padding-left:10px">${esc(s.rb_reasoning)}</div>`
    : '';
  const legId = `leg_${s.match.replace(/\W/g, '_')}_${s.outcome.replace(/\W/g, '_')}`;
  const checked = _accaLegs.has(legId) ? 'checked' : '';
  // Only what the tray needs — never serialise the whole intel object into the DOM
  const legSlim = {
    match: s.match, outcome: s.outcome, market: s.market,
    fair_prob: s.fair_prob, best_price: s.best_price, best_book: s.best_book,
    per_book: s.per_book || {},
  };
  const titleLine = grouped
    ? `<div class="bet-card__pick">${fmtPick(s.outcome)} <span class="vs">${mkt}</span></div>`
    : `<div class="bet-card__pick">${fmtPick(s.outcome)} <span class="vs">— ${fmtLabel(s.match)}</span></div>
       <div class="bet-card__meta">${kickoffCountdown(s.commence)} · ${mkt}${s.round ? ` · <span style="color:var(--cyan)">${esc(s.round.label)}</span>` : ''}</div>`;
  const confLine = s.rb_confidence
    ? `<div style="font-size:var(--fs-xs);color:var(--tx-4);margin-top:3px">Football view: <span style="color:${s.rb_confidence === 'high' ? 'var(--green)' : s.rb_confidence === 'medium' ? 'var(--amber)' : 'var(--tx-3)'}">${esc(s.rb_confidence)} confidence${s.rb_strength ? ' · ' + esc(s.rb_strength) : ''}</span></div>`
    : '';

  return `<div class="bet-card${sc.tier === 'speculative' ? ' demoted' : ''}${checked ? ' selected' : ''}" id="card_${legId}">
    <div class="bet-card__top">
      <div style="display:flex;align-items:flex-start;gap:10px;min-width:0">
        <input type="checkbox" class="leg-check" ${checked} title="Add to acca tray"
          onchange="toggleAccaLeg(this,'${legId}',${JSON.stringify(legSlim).replace(/"/g, '&quot;')})">
        <div style="min-width:0">${titleLine}${confLine}</div>
      </div>
      <div class="bet-card__right">
        ${vBadge}
        <span class="bet-card__price">@ <b>${price.toFixed(2)}</b> ${esc(s.best_book)}</span>
        ${actionNote}
      </div>
    </div>
    ${reasoning}
    <div style="line-height:1.7">${tags}</div>
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
      <span style="font-size:var(--fs-sm);color:var(--tx-3)">${evMoneyHTML(s.fair_prob, price, stake, '0.9rem')} <span style="color:var(--tx-4)">·</span> €${stake.toFixed(2)} returns €${ret.toFixed(2)} if it wins</span>
      <button class="btn btn--primary btn--sm" onclick="openBetModal('${s.match.replace(/'/g, "\\'")}','${s.outcome}','${s.market}',${price},'${(s.best_book || '').replace(/'/g, "\\'")}',${s.fair_prob != null ? s.fair_prob : 'null'}); this.blur()">+ Log bet</button>
    </div>
  </div>`;
}

function renderSensible() {
  const panel = document.getElementById('sensible-panel');
  if (!panel) return;
  if (!allMatches.length && !allSingles.length) {
    panel.innerHTML = _dataLoaded ? noOddsState() : skeletonCards(3);
    return;
  }

  const stake = sensibleStake();
  const tierFilter = document.getElementById('sensible-tier-filter')?.value || 'all';
  const hasIntel = Object.keys(allIntel).length > 0;

  // Build picks from analyst recommendations + live prices from divergence data.
  const sensibleBets = [];
  const seen = new Set();

  for (const match of allMatches) {
    const label = match.label;
    const intel = allIntel[label] || allIntel[normalizeMatchLabel(label)];
    if (!intel || !intel.recommended_bets || !intel.recommended_bets.length) continue;

    const parts = label.split(' vs ');
    if (parts.length !== 2) continue;
    const homeNorm = normalizeTeam(parts[0]);
    const awayNorm = normalizeTeam(parts[1]);

    for (const rb of intel.recommended_bets) {
      const ao = (rb.outcome || '').toLowerCase().replace(/ /g, '_');
      const key = label + '|' + ao;
      if (seen.has(key)) continue;
      seen.add(key);

      let targetOutcome = null;
      if (ao === 'home_win') targetOutcome = homeNorm;
      else if (ao === 'away_win') targetOutcome = awayNorm;
      else if (ao === 'draw') targetOutcome = 'draw';
      else continue; // totals/spreads tokens have no price in divergence outcomes

      const priceData = (match.outcomes || []).find(o => o.outcome === targetOutcome);
      if (!priceData || !priceData.best_price) continue;

      const pmGap = priceData.diff != null ? -priceData.diff : null;

      sensibleBets.push({
        match: label,
        commence: match.commence,
        market: 'h2h',
        outcome: targetOutcome,
        fair_prob: (priceData.book_fair || 0) / 100,
        best_price: priceData.best_price,
        best_book: priceData.best_book,
        paddy: priceData.paddy,
        per_book: priceData.per_book || {},
        edge: priceData.edge,
        pm_gap: pmGap,
        kalshi: priceData.kalshi,
        poly: priceData.poly,
        confidence: priceData.confidence || 'low',
        round: match.round,
        weather: match.weather,
        intel: intel,
        analyst_confirms: true,
        rb_reasoning: rb.reasoning || '',
        rb_confidence: rb.confidence || '',
        rb_strength: rb.strength || '',
      });
    }
  }

  const scored = sensibleBets
    .map(s => ({ s, sc: sensibleScore(s) }))
    .sort((a, b) => (a.s.commence || '').localeCompare(b.s.commence || '') || b.sc.score - a.sc.score);

  const roundFilter = document.getElementById('sensible-round-filter')?.value || '';
  let list = scored;
  if (roundFilter) list = list.filter(x => x.s.round?.label === roundFilter);
  if (tierFilter === 'strong')      list = list.filter(x => x.sc.tier === 'strong');
  else if (tierFilter === 'solid')  list = list.filter(x => x.sc.tier !== 'speculative');

  const nStrong = scored.filter(x => x.sc.tier === 'strong').length;
  const nTotal  = scored.length;
  const intelCoverage = intelEntries().length;

  const statsLine = `<div class="note--mini note">${intelCoverage} matches analysed · ${nTotal} analyst-backed bet${nTotal !== 1 ? 's' : ''}${nStrong ? ` · <span style="color:var(--green)">${nStrong} ★ Strong</span>` : ''} · analyst runs in background, more appear as it completes</div>`;
  const intro = collapsibleBanner('sensible-bets-intro',
    '🎯 Best Bets — analyst picks, odds quality scored.',
    `🎯 <strong>Best Bets — analyst-recommended picks with the odds quality scored.</strong><div style="margin-top:8px;font-size:var(--fs-sm);color:var(--tx-2);line-height:1.6">Every bet here passed two gates:<br><span style="color:var(--green)">①</span> The <strong>AI analyst</strong> studied the match — squad, form, injuries, conditions — and explicitly recommended this outcome.<br><span style="color:var(--green)">②</span> The <strong>bookmaker odds</strong> were checked: are you getting fair or better value for that pick?<br>Tiers: <strong style="color:var(--green)">★ Strong</strong> = great price + Kalshi agrees · <strong>Solid</strong> = fair price · <em style="color:var(--tx-4)">Speculative</em> = analyst backed it but odds tight.</div>`);

  if (!hasIntel) {
    panel.innerHTML = intro + statsLine + emptyState('🧠', 'Analyst is researching matches',
      'Best Bets appear as the analyst finishes each match — usually within a couple of minutes. Check back shortly.');
    return;
  }
  if (!list.length) {
    panel.innerHTML = intro + statsLine + emptyState('🔍', 'No analyst-backed bets match the current filters',
      `${tierFilter !== 'all' ? 'Try loosening the tier filter, or ' : 'Try '}switching Round to <b>All rounds</b>.`);
    return;
  }

  // Group by match so multiple recs for the same game appear together
  const byMatch = new Map();
  for (const x of list) {
    if (!byMatch.has(x.s.match)) byMatch.set(x.s.match, []);
    byMatch.get(x.s.match).push(x);
  }
  const groupsHTML = [...byMatch.entries()].map(([label, items]) => {
    const s0 = items[0].s;
    const age = intelAge(s0.intel);
    const updating = _reanalysing.has(label)
      ? `<span class="badge badge--amber"><span class="spinner" style="width:10px;height:10px;border-top-color:var(--amber)"></span> updating analysis</span>` : '';
    return `<div class="group-card">
      <div class="group-card__head">
        <strong style="flex:1;color:var(--tx-1)">${fmtLabel(label)}</strong>
        <span style="color:var(--tx-3);font-size:var(--fs-sm)">${kickoffCountdown(s0.commence)}</span>
        ${s0.round ? `<span class="badge badge--cyan badge--ghost">${esc(s0.round.label)}</span>` : ''}
        ${updating}
        ${age ? `<span style="color:var(--tx-4);font-size:var(--fs-xs)">${age}</span>` : ''}
      </div>
      <div class="group-card__body">
        ${items.map(x => sensibleCardHTML(x.s, x.sc, stake, true)).join('')}
      </div>
    </div>`;
  }).join('');
  panel.innerHTML = intro + statsLine + groupsHTML;
}

/* ---------------- acca tray (multi-select on Best Bets) ---------------- */
const _accaLegs = new Map();  // legId -> single object

function toggleAccaLeg(cb, legId, s) {
  if (cb.checked) _accaLegs.set(legId, s);
  else            _accaLegs.delete(legId);
  const card = document.getElementById('card_' + legId);
  if (card) card.classList.toggle('selected', cb.checked);
  renderAccaTray();
}

function clearAccaBuilder() {
  _accaLegs.clear();
  document.querySelectorAll('#sensible-panel input[type=checkbox]').forEach(cb => {
    cb.checked = false;
    cb.closest('.bet-card')?.classList.remove('selected');
  });
  renderAccaTray();
}

function renderAccaTray() {
  const tray = document.getElementById('acca-tray');
  const legs = [..._accaLegs.values()];
  if (legs.length < 2) { tray.classList.remove('open'); return; }
  tray.classList.add('open');

  const stake = sensibleStake();

  // Same-match warning
  const matches = legs.map(s => s.match);
  const dupes = matches.filter((m, i) => matches.indexOf(m) !== i);
  document.getElementById('tray-warning').textContent = dupes.length
    ? `⚠ Same-match legs detected (${[...new Set(dupes)].map(titleCase).join(', ')}) — most books won't allow this`
    : '';

  // Best single bookmaker covering all legs
  const bookSets = legs.map(s => new Set(Object.keys(s.per_book || {})));
  const common = bookSets.reduce((a, b) => new Set([...a].filter(x => b.has(x))));

  let bestBook = null, bestCombined = 0;
  common.forEach(bk => {
    const combined = legs.reduce((p, s) => p * (s.per_book[bk] || 0), 1);
    if (combined > bestCombined) { bestCombined = combined; bestBook = bk; }
  });

  const fairCombined = legs.reduce((p, s) => p * (s.fair_prob || 0), 1);
  const ev = (fairCombined > 0 && bestCombined > 0)
    ? ((fairCombined * bestCombined - 1) * 100).toFixed(1) : null;
  const grossReturn = stake * bestCombined;

  document.getElementById('tray-legs-summary').textContent =
    `${legs.length}-leg acca · fair chance: ${(fairCombined * 100).toFixed(1)}%`;

  if (bestBook) {
    document.getElementById('tray-book').textContent = `Best book: ${bestBook}`;
    document.getElementById('tray-price').textContent = bestCombined.toFixed(2);
    const evColor = parseFloat(ev) >= 0 ? 'var(--green)' : 'var(--red)';
    const evAmt = ev != null ? (parseFloat(ev) / 100 * stake) : null;
    document.getElementById('tray-ev').innerHTML =
      `<span style="color:${evColor};font-weight:700">EV ${parseFloat(ev) >= 0 ? '+' : '−'}€${Math.abs(evAmt).toFixed(2)} (${parseFloat(ev) >= 0 ? '+' : ''}${ev}%)</span>` +
      `<span style="color:var(--tx-3);font-size:var(--fs-xs);margin-left:8px">€${stake.toFixed(2)} → €${grossReturn.toFixed(2)} if it lands</span>`;
  } else {
    document.getElementById('tray-book').textContent = 'No single book covers all legs';
    document.getElementById('tray-price').textContent = '';
    document.getElementById('tray-ev').textContent = '';
  }

  document.getElementById('tray-leg-list').innerHTML = legs.map(s => {
    const bookPrice = bestBook && s.per_book?.[bestBook] ? s.per_book[bestBook].toFixed(2) : '—';
    return `<span class="tray-chip">
      ${fmtPick(s.outcome)} <span style="color:var(--tx-4)">${fmtLabel(s.match)}</span>
      <strong style="color:var(--tx-1);margin-left:4px">${bookPrice}</strong>
    </span>`;
  }).join('');
}

/* ---------------- Analyst Writeups (full match reads) ---------------- */

function fmtAnalystOutcome(rb, home, away) {
  const o = (rb.outcome || '').toLowerCase();
  if (o === 'home_win') return `${home} to win`;
  if (o === 'away_win') return `${away} to win`;
  if (o === 'draw')     return 'Draw';
  if (o.startsWith('over_'))  return `Over ${o.split('_')[1]} goals`;
  if (o.startsWith('under_')) return `Under ${o.split('_')[1]} goals`;
  if (o.startsWith('home_'))  return `${home} (${o.split('home_')[1]}) handicap`;
  if (o.startsWith('away_'))  return `${away} (${o.split('away_')[1]}) handicap`;
  return rb.outcome || '';
}

function analystMatchHTML(label, intel) {
  const parts = label.includes(' vs ') ? label.split(' vs ') : [label, ''];
  const home = titleCase(parts[0]), away = titleCase(parts[1]);
  const cc = c => c === 'high' ? 'var(--green)' : c === 'medium' ? 'var(--amber)' : 'var(--tx-3)';
  const updatingBanner = _reanalysing.has(label)
    ? `<div style="display:flex;align-items:center;gap:8px;margin:8px 0 4px;padding:8px 10px;background:var(--amber-bg);border:1px solid #5d4715;border-radius:var(--radius-sm);font-size:var(--fs-sm);color:var(--amber)">
         <div class="spinner" style="width:12px;height:12px;border-top-color:var(--amber)"></div>
         🩹 Injury news detected — updating analysis, check back in a moment
       </div>`
    : '';
  const recs = intel.recommended_bets || [];
  const book = picksChosenBook();
  const recsHTML = recs.length
    ? recs.map(rb => {
        const { price, bookLabel, fallback } = rb.best_price ? priceForBook(rb, book) : { price: null };
        const oddsHTML = price
          ? `<span class="badge help" style="color:var(--tx-1)" title="Best available decimal odds for this selection${fallback ? ' — not posted at ' + esc(book) + ', best price shown' : ''}.">${price.toFixed(2)} @ ${esc(bookLabel)}${fallback ? ' ⚠' : ''}</span>`
            + (rb.edge != null && rb.edge > 0
                ? `<span class="badge badge--green help" title="The price beats the de-vigged fair value by this much — the analyst pick is also +EV on the maths.">+${rb.edge.toFixed(1)}% edge</span>`
                : '')
          : `<span style="font-size:var(--fs-xs);color:var(--tx-4)">no price posted yet</span>`;
        return `<div class="rec-row" style="border-left-color:${cc(rb.confidence)}">
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <strong style="color:var(--tx-1)">${esc(fmtAnalystOutcome(rb, home, away))}</strong>
            <span class="badge" style="color:${cc(rb.confidence)}">${esc(rb.confidence || '')}${rb.strength ? ' · ' + esc(rb.strength) : ''}</span>
            ${oddsHTML}
          </div>
          <div style="font-size:var(--fs-sm);color:var(--tx-3);margin-top:4px;line-height:1.45">${esc(rb.reasoning || '')}</div>
        </div>`;
      }).join('')
    : `<div style="color:var(--tx-3);font-size:var(--fs-sm);margin-top:6px">Analyst sees no clear edge — no bet recommended.</div>`;
  const cond = intel.conditions;
  const condNote = cond && cond.stadium
    ? `<div style="font-size:var(--fs-xs);color:var(--tx-4);margin-top:2px">${esc(cond.stadium)}${cond.altitude_m > 800 ? ' · ' + Math.round(cond.altitude_m).toLocaleString() + 'm venue altitude' : ''}</div>`
    : '';
  const ageNote = intelAge(intel) ? `<span style="color:var(--tx-4);font-size:var(--fs-xs);margin-left:8px">${intelAge(intel)}</span>` : '';
  return `<div class="bet-card">
    <div class="bet-card__pick" style="font-size:var(--fs-md)">${fmtLabel(label)}${ageNote}</div>
    ${updatingBanner}
    ${condNote}
    ${intel.overall_summary ? `<div style="font-size:var(--fs-sm);color:var(--tx-2);line-height:1.55">${esc(intel.overall_summary)}</div>` : ''}
    ${recsHTML}
  </div>`;
}

function renderTopPicks() {
  const panel = document.getElementById('picks-panel');
  if (!panel) return;

  const intro = collapsibleBanner('btrs-analysis-intro',
    '⚖️ Analyst Writeups — the football view on each covered match.',
    `⚖️ <strong>The football view — a professional second opinion, not fact.</strong> The analyst's read on each game it has covered (squad, form, conditions, injuries), with its specific recommended bets and reasoning. Cross-check against <button class="linklike" onclick="switchView('markets')">Markets → Value Singles</button> — agreement between the two is the strongest signal.`);

  const entries = intelEntries();
  if (!entries.length) {
    const loading = _intelPollTimer || !allMatches.length;
    panel.innerHTML = intro + emptyState('🧠',
      loading ? 'Analyst is still researching matches…' : 'No analyst coverage yet',
      `Analysis is rate-limited (a few matches per refresh) — coverage grows as it runs. Meanwhile see <button class="linklike" onclick="switchView('markets')">Markets →</button>`);
    return;
  }

  // Sort analysed matches by kick-off (looked up from the divergence list)
  const commenceBy = {};
  allMatches.forEach(m => { commenceBy[m.label] = m.commence; commenceBy[normalizeMatchLabel(m.label)] = m.commence; });
  const items = entries
    .map(([l, intel]) => ({ label: l, intel, commence: commenceBy[l] || commenceBy[normalizeMatchLabel(l)] || '' }))
    .sort((a, b) => String(a.commence).localeCompare(String(b.commence)));

  panel.innerHTML = intro + items.map(it => analystMatchHTML(it.label, it.intel)).join('');
}
