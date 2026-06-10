/* ============================================================
   app.js — navigation (primary nav, sub-tabs, More menu),
   hash routing and boot.

   Information architecture:
     Today        — next matchday, analyst picks, log bets
     Best Bets    — Picks (analyst-led, verdict-first) | Analyst Writeups
     Markets      — Value Singles | Accumulators | Acca Builder | Market Divergence
     My Bets      — journal with expected-vs-actual P&L
     More ▾       — Injuries & Suspensions, Methodology
   ============================================================ */

const VIEWS = ['today', 'best', 'markets', 'mybets', 'injuries', 'method'];
const MORE_VIEWS = ['injuries', 'method'];

let currentView = 'today';
let bestSubTab = 'picks';       // 'picks' | 'writeups'
let marketsSubTab = 'singles';  // 'singles' | 'accas' | 'builder' | 'divergence'

function switchView(view) {
  if (!VIEWS.includes(view)) view = 'today';
  currentView = view;
  closeMoreMenu();

  document.querySelectorAll('.view').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + view)?.classList.add('active');

  // nav highlighting (desktop top nav + mobile bottom bar + More entries)
  const isMore = MORE_VIEWS.includes(view);
  document.querySelectorAll('#primary-nav .nav-btn, #bottom-nav .bb-btn').forEach(b => {
    const v = b.dataset.view;
    b.classList.toggle('active', v === view || (v === 'more' && isMore));
  });
  document.querySelectorAll('.more-item').forEach(b => {
    b.classList.toggle('active', b.dataset.view === view);
  });

  try { history.replaceState(null, '', '#/' + view); } catch {}

  // render-on-entry (cheap — data is already in memory)
  if (view === 'today') renderToday();
  if (view === 'best') (bestSubTab === 'picks' ? renderSensible : renderTopPicks)();
  if (view === 'markets') {
    if (marketsSubTab === 'builder') { renderFixtures(); renderFixtureAcca(); }
    else if (marketsSubTab === 'divergence') renderDivergence();
    else renderBets();
  }
  if (view === 'mybets') renderMyBets();
  if (view === 'injuries' && !_injuriesLoaded) loadInjuries();

  window.scrollTo({ top: 0 });
}

function switchBestTab(tab) {
  bestSubTab = tab;
  document.querySelectorAll('#tab-best .subnav .pill').forEach(p =>
    p.classList.toggle('active', p.dataset.best === tab));
  document.getElementById('best-picks-wrap').style.display = tab === 'picks' ? '' : 'none';
  document.getElementById('best-writeups-wrap').style.display = tab === 'writeups' ? '' : 'none';
  (tab === 'picks' ? renderSensible : renderTopPicks)();
}

function switchMarketsTab(tab) {
  marketsSubTab = tab;
  document.querySelectorAll('#tab-markets .subnav .pill').forEach(p =>
    p.classList.toggle('active', p.dataset.mkt === tab));

  const isBets = tab === 'singles' || tab === 'accas';
  document.getElementById('markets-toolbar').style.display = isBets ? '' : 'none';
  document.getElementById('bets-panel').style.display = isBets ? '' : 'none';
  document.getElementById('builder-wrap').style.display = tab === 'builder' ? '' : 'none';
  document.getElementById('divergence-wrap').style.display = tab === 'divergence' ? '' : 'none';

  if (isBets) {
    betsSubTab = tab === 'accas' ? 'parlays' : 'singles';
    document.querySelectorAll('#markets-toolbar .singles-only').forEach(el => {
      el.style.display = betsSubTab === 'singles' ? '' : 'none';
    });
    renderBets();
  } else if (tab === 'builder') {
    renderFixtures();
    renderFixtureAcca();
  } else {
    renderDivergence();
  }
}

/* ---- "More" dropdown / bottom sheet ---- */
function toggleMoreMenu(event, mobileSheet = false) {
  event.stopPropagation();
  const menu = document.getElementById('more-menu');
  menu.classList.toggle('mobile-sheet', !!mobileSheet);
  menu.classList.toggle('open');
}
function closeMoreMenu() {
  document.getElementById('more-menu')?.classList.remove('open');
}
document.addEventListener('click', e => {
  if (!e.target.closest('#more-btn') && !e.target.closest('#more-menu')
      && !e.target.closest('.bb-btn[data-view="more"]')) closeMoreMenu();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeMoreMenu(); closeBetModal(); }
});

/* ---- legacy aliases (old tab names that may live in saved links) ---- */
function switchTab(tab) {
  const map = {
    today: () => switchView('today'),
    sensible: () => { switchView('best'); switchBestTab('picks'); },
    picks: () => { switchView('best'); switchBestTab('writeups'); },
    bets: () => { switchView('markets'); switchMarketsTab('singles'); },
    fixtures: () => { switchView('markets'); switchMarketsTab('builder'); },
    divergence: () => { switchView('markets'); switchMarketsTab('divergence'); },
    mybets: () => switchView('mybets'),
    injuries: () => switchView('injuries'),
    method: () => switchView('method'),
  };
  (map[tab] || map.today)();
}

/* ---- boot ---- */
(function boot() {
  // skeletons while the first fetch is in flight
  document.getElementById('today-panel').innerHTML = skeletonCards(3);
  document.getElementById('sensible-panel').innerHTML = skeletonCards(3);
  document.getElementById('bets-panel').innerHTML = skeletonCards(3);
  document.getElementById('matches').innerHTML = skeletonCards(4);
  document.getElementById('picks-panel').innerHTML = skeletonCards(2);

  // deep link: #/view
  const hashView = (location.hash.match(/^#\/(\w+)/) || [])[1];
  if (hashView && VIEWS.includes(hashView) && hashView !== 'today') switchView(hashView);

  loadData();
})();
