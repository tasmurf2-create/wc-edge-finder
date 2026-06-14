/* ============================================================
   views-admin.js — owner-only visitor stats tab.

   The app is open to everyone; this tab is gated by ADMIN_KEY.
   Security model: the *data* is protected server-side. The key is
   never embedded in the page — you enter it once (at #/admin) and it
   is kept in localStorage on your device. /admin/stats returns 403
   without a valid key, so nothing leaks even though the tab markup
   exists for everyone.
   ============================================================ */

const ADMIN_KEY_LS = 'wcef_admin_key';

function adminKey() { return localStorage.getItem(ADMIN_KEY_LS) || ''; }

// Reveal the Admin entry in the More menu only on devices holding a key.
function refreshAdminNav() {
  const item = document.getElementById('admin-nav-item');
  if (item) item.style.display = adminKey() ? '' : 'none';
}

function keyFormHTML(err = '') {
  return `<div class="prose">
    <h2>Admin</h2>
    <p class="prose-sub">Enter your admin key to view visitor stats. The key is set in the
    <code>ADMIN_KEY</code> environment variable on the server and stored only in this browser.</p>
    ${err ? `<p style="color:var(--red)">${esc(err)}</p>` : ''}
    <div style="display:flex;gap:8px;max-width:360px">
      <input id="admin-key-input" type="password" autocomplete="off" placeholder="Admin key"
        onkeydown="if(event.key==='Enter')submitAdminKey()"
        style="flex:1;padding:8px 10px;background:var(--bg-2);border:1px solid var(--line-1);border-radius:var(--radius-sm);color:var(--tx-1)">
      <button class="btn btn--sm" onclick="submitAdminKey()">Unlock</button>
    </div>
  </div>`;
}

async function submitAdminKey() {
  const input = document.getElementById('admin-key-input');
  const key = (input?.value || '').trim();
  if (!key) return;
  try {
    const res = await fetch('/admin/stats?key=' + encodeURIComponent(key));
    if (!res.ok) {
      document.getElementById('admin-panel').innerHTML = keyFormHTML('That key was rejected.');
      return;
    }
    localStorage.setItem(ADMIN_KEY_LS, key);
    refreshAdminNav();
    renderAdminStats(await res.json());
  } catch (e) {
    document.getElementById('admin-panel').innerHTML = keyFormHTML('Could not reach the server.');
  }
}

function adminLogout() {
  localStorage.removeItem(ADMIN_KEY_LS);
  refreshAdminNav();
  switchView('today');
}

async function renderAdmin() {
  const panel = document.getElementById('admin-panel');
  if (!panel) return;
  const key = adminKey();
  if (!key) { panel.innerHTML = keyFormHTML(); return; }

  panel.innerHTML = skeletonCards(2);
  try {
    const res = await fetch('/admin/stats?key=' + encodeURIComponent(key));
    if (res.status === 403) {            // key changed/expired on the server
      localStorage.removeItem(ADMIN_KEY_LS);
      refreshAdminNav();
      panel.innerHTML = keyFormHTML('Your saved key was rejected — enter it again.');
      return;
    }
    if (!res.ok) throw new Error('HTTP ' + res.status);
    renderAdminStats(await res.json());
  } catch (e) {
    panel.innerHTML = emptyState('⚠️', 'Could not load visitor stats',
      `${esc(String(e))} · <button class="linklike" onclick="renderAdmin()">retry</button>`);
  }
}

function statCard(label, value) {
  return `<div style="flex:1;min-width:140px;background:var(--bg-2);border:1px solid var(--line-1);border-radius:var(--radius);padding:14px 16px">
    <div style="font-size:var(--fs-xl);font-weight:700;color:var(--tx-1)">${value}</div>
    <div style="font-size:var(--fs-sm);color:var(--tx-3)">${esc(label)}</div>
  </div>`;
}

function renderAdminStats(data) {
  const panel = document.getElementById('admin-panel');
  if (!panel) return;
  const visitors = data.visitors || [];

  const fmtLoc = r => {
    const place = [r.city, r.country_code || r.country].filter(Boolean).join(', ');
    return place || '—';
  };

  const rows = visitors.map(r => `<tr style="border-top:1px solid var(--line-1)">
    <td style="padding:6px 10px;color:var(--tx-1);font-family:monospace">${esc(r.ip)}</td>
    <td style="padding:6px 10px;color:var(--tx-2);white-space:nowrap" title="${esc([r.city, r.region, r.country].filter(Boolean).join(', '))}">${esc(fmtLoc(r))}</td>
    <td style="padding:6px 10px;color:var(--tx-3)">${esc(r.isp || r.org || '—')}</td>
    <td style="padding:6px 10px;text-align:right;color:var(--tx-2)">${r.hits}</td>
    <td style="padding:6px 10px;color:var(--tx-3);white-space:nowrap">${esc(r.first_seen)}</td>
    <td style="padding:6px 10px;color:var(--tx-3);white-space:nowrap">${esc(r.last_seen)}</td>
    <td style="padding:6px 10px;color:var(--tx-3);font-family:monospace">${esc(r.last_path)}</td>
  </tr>`).join('');

  const table = visitors.length ? `
    <div style="overflow-x:auto;border:1px solid var(--line-1);border-radius:var(--radius);margin-top:14px">
      <table style="width:100%;border-collapse:collapse;font-size:var(--fs-sm)">
        <thead><tr style="text-align:left;color:var(--tx-4);font-size:var(--fs-xs);text-transform:uppercase">
          <th style="padding:8px 10px">IP address</th>
          <th style="padding:8px 10px">Location</th>
          <th style="padding:8px 10px">ISP / Org</th>
          <th style="padding:8px 10px;text-align:right">Hits</th>
          <th style="padding:8px 10px">First seen</th>
          <th style="padding:8px 10px">Last seen</th>
          <th style="padding:8px 10px">Last page</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>` : emptyState('👀', 'No visitors recorded yet', 'Stats begin from the server\'s last restart.');

  panel.innerHTML = `<div class="prose">
    <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
      <h2 style="margin:0">Visitor stats</h2>
      <div style="display:flex;gap:8px">
        <button class="btn btn--sm" onclick="renderAdmin()">↻ Refresh</button>
        <button class="btn btn--sm btn--quiet" onclick="adminLogout()">Sign out</button>
      </div>
    </div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:12px">
      ${statCard('Unique visitors (distinct IPs)', data.unique_visitors ?? visitors.length)}
      ${statCard('Total requests', data.total_requests ?? '—')}
    </div>
    <p class="note note--mini" style="margin-top:12px">Counts are distinct IP addresses since the server last
    restarted or redeployed — in-memory only, not persisted across deploys. Location &amp; ISP are looked up
    per IP via ip-api.com (cached). The <strong>ISP / Org</strong> column is the best VPN hint: a hosting
    name like M247, DigitalOcean, OVH or Mullvad usually means a VPN/proxy; a consumer ISP (e.g. Vodafone,
    Eir) usually means a real visitor. Distinct IP ≈ distinct network, not a precise person or VPN count.</p>
    ${table}
  </div>`;
}
