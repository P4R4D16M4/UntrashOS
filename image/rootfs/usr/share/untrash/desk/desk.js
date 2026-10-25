/* Untrash Desk frontend (backend: /usr/lib/untrash/untrash-desk).
   Window manager after design/desk.html; every value from the API is
   escaped with esc() before it goes into HTML. */
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const gb = b => b >= 1e12 ? (b / 1e12).toFixed(1) + ' TB' : b >= 1e9 ? (b / 1e9).toFixed(1) + ' GB' : (b / 1e6).toFixed(0) + ' MB';
const size = b => b < 1024 ? b + ' B' : b < 1048576 ? (b / 1024).toFixed(0) + ' KB' : gb(b);
const ICON = n => /^(mesh|settings|logs|packages)$/.test(n) ? `/ut/assets/icons/${n}.svg` : `/ut/assets/icons/${n}-128.png`;
let ME = null;

/* busy feedback: while requests a click started are running, the pointer
   shows "progress", a thin bar runs at the top and that button spins and is
   disabled (no double submit).  Background polls (status, activity) stay quiet. */
let BUSY = 0, LASTBTN = null, LASTT = 0;
const QUIET = /^(live|activity|overview|job|update|transfers)\b/;
document.addEventListener('click', e => { const b = e.target.closest('button, .ut-btn, [data-nav], .ut-dock__item, .fileline'); if (b) { LASTBTN = b; LASTT = performance.now(); } }, true);
function busy(on, btn) {
  BUSY = Math.max(0, BUSY + (on ? 1 : -1));
  document.documentElement.classList.toggle('ut-busy', BUSY > 0);
  if (btn) { if (on) { btn.setAttribute('aria-busy', 'true'); if (btn.tagName === 'BUTTON') btn.disabled = true; } else { btn.removeAttribute('aria-busy'); if (btn.tagName === 'BUTTON') btn.disabled = false; } }
}
async function api(path, body, raw) {
  const user = performance.now() - LASTT < 400 && !QUIET.test(path);
  const btn = user && LASTBTN && LASTBTN.isConnected ? LASTBTN : null;
  if (user) busy(true, btn);
  try { return await apiRaw(path, body, raw); } finally { if (user) busy(false, btn); }
}
async function apiRaw(path, body, raw) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'X-UT': '1', 'Content-Type': raw ? 'application/octet-stream' : 'application/json' }, body: raw ? body : JSON.stringify(body) };
  const r = await fetch('/api/' + path, opt);
  let j = {};
  try { j = await r.json(); } catch (e) { }
  if (r.status === 401 && path !== 'login') { boot(); throw new Error(j.error || 'Please sign in'); }
  // users with sign-in "password and app" confirm some actions in the UntrashApp
  if (r.status === 428 && j.confirm && !raw) {
    await appWait({ title: j.action, code: j.code, poll: () => apiRaw('confirm?id=' + encodeURIComponent(j.confirm)) });
    return apiRaw(path, Object.assign({}, body, { confirm: j.confirm }));
  }
  if (!r.ok) throw new Error(j.error || ('Error ' + r.status));
  return j;
}
/* waits until the UntrashApp answers a request: shows the number to choose
   in the app; resolves on approval, throws on denial or timeout */
function appWait({ title, code, poll, into }) {
  return new Promise((resolve, reject) => {
    const html = `<div class="ut-appwait"><img src="${ICON('mesh')}" alt=""><p>${esc(UTI18N.tr('Open the UntrashApp and choose this number:'))}</p>
      <div class="ut-appwait__code" translate="no">${esc(String(code))}</div><p class="ut-faint" id="awt"></p></div>`;
    let box, s;
    if (into) { box = into; box.innerHTML = html + '<button class="ut-btn ut-btn--ghost" data-x type="button">Cancel</button>'; }
    else {
      s = document.createElement('div'); s.className = 'ut-scrim';
      s.innerHTML = `<div class="ut-dialog" role="dialog" aria-modal="true"><div class="ut-dialog__head"><h2>${esc(UTI18N.tr(title || 'Confirm in the UntrashApp'))}</h2></div>
        <div class="ut-dialog__body">${html}</div><div class="ut-dialog__foot"><button class="ut-btn" data-x>Cancel</button></div></div>`;
      document.body.append(s); box = s;
    }
    const t0 = Date.now(), stop = (fn, x) => { clearInterval(iv); if (s) s.remove(); fn(x); };
    box.querySelector('[data-x]').onclick = () => stop(reject, new Error(UTI18N.tr('Cancelled.')));
    const iv = setInterval(async () => {
      const left = Math.max(0, 120 - Math.round((Date.now() - t0) / 1000)), t = box.querySelector('#awt');
      if (t) t.textContent = UTI18N.tr('%s s left').replace('%s', left);
      try {
        const r = await poll();
        if (r.state === 'approved') stop(resolve, r);
        else if (r.state === 'denied') stop(reject, new Error(UTI18N.tr('Declined in the UntrashApp.')));
        else if (r.state !== 'pending') stop(reject, new Error(UTI18N.tr('No answer from the UntrashApp.')));
      } catch (e) { stop(reject, e); }
    }, 1500);
  });
}
function toast(title, text = '', kind = '') {
  const t = document.createElement('div');
  t.className = 'ut-toast ' + (kind ? 'ut-toast--' + kind : '');
  t.innerHTML = `<div class="ut-toast__body"><div class="ut-toast__title">${esc(title)}</div><div class="ut-toast__text">${esc(text)}</div></div>`;
  ($('#toasts') || document.body).append(t);
  setTimeout(() => t.remove(), kind === 'danger' ? 9000 : 4500);
}
const fail = e => toast('Error', e.message, 'danger');
function dialog({ kind = '', title, body, ok = 'OK', okCls = 'ut-btn--primary', onOk }) {
  const s = document.createElement('div'); s.className = 'ut-scrim';
  s.innerHTML = `<div class="ut-dialog ${kind ? 'ut-dialog--' + kind : ''}" role="dialog" aria-modal="true"><div class="ut-dialog__head"><h2>${esc(title)}</h2></div>
    <div class="ut-dialog__body">${body}</div><div class="ut-dialog__foot"><button class="ut-btn" data-x>Cancel</button><button class="ut-btn ${okCls}" data-ok>${esc(ok)}</button></div></div>`;
  s.onclick = e => { if (e.target === s || e.target.closest('[data-x]')) s.remove(); };
  s.querySelector('[data-ok]').onclick = async () => {
    try { if (onOk && (await onOk(s)) === false) return; s.remove(); } catch (e) { fail(e); }
  };
  document.body.append(s);
  (s.querySelector('input,select') || s.querySelector('[data-ok]')).focus();
  return s;
}

/* ---------------------------------------------------------------- start */
async function boot() {
  const st = await (await fetch('/api/state')).json();
  document.title = st.hostname + ' · Untrash Desk';
  if (!st.initialized) return setupScreen(st);
  if (!st.user) return loginScreen(st);
  ME = await api('me');
  if (ME.prefs && window.UTTHEME) UTTHEME.set(ME.prefs);    // the user's appearance follows them to every browser
  desk(st);
}
function resetScreen(st) {
  $('#app').innerHTML = `<main class="ut-login"><form class="ut-login__card" id="rf">
    <img class="ut-login__logo" src="/ut/assets/logo-mark-192.png" alt=""><div class="ut-login__host">${esc(st.hostname)} · RESET button</div>
    <p>New password for <b>admin</b> set (still ${Math.ceil(st.reset_window / 60)} minutes possible).</p>
    ${field('r1', 'New password (at least 8 characters)', '', 'type=password autocomplete=new-password')}${field('r2', 'Repeat', '', 'type=password autocomplete=new-password')}
    <div id="rerr" class="ut-callout ut-callout--danger" hidden></div><button class="ut-btn ut-btn--primary ut-btn--lg" style="width:100%">Set password</button></form></main>`;
  $('#r1').focus();
  $('#rf').onsubmit = async e => {
    e.preventDefault();
    try { if ($('#r1').value !== $('#r2').value) throw new Error('The passwords do not match.');
      await api('reset-admin', { password: $('#r1').value }); boot(); }
    catch (err) { $('#rerr').hidden = false; $('#rerr').textContent = err.message; }
  };
}
function loginScreen(st) {
  if (st.reset_window) return resetScreen(st);
  setTimeout(() => { const l = $('#lang'); if (l) l.onchange = () => UTI18N.set(l.value); });
  $('#app').innerHTML = `<main class="ut-login"><form class="ut-login__card" id="lf">
    <img class="ut-login__logo" src="/ut/assets/logo-mark-192.png" alt=""><img class="ut-login__word" src="/ut/assets/wordmark-300.png" alt="UntrashOS">
    <div class="ut-login__host">${esc(st.hostname)} · NAS542</div>
    <div class="ut-login__lang">${langSel('lang', UTI18N.lang)}</div>
    <div class="ut-field"><label for="u">User name</label><input class="ut-input" id="u" autocomplete="username" value="admin"></div>
    <div class="ut-field"><label for="p">Password</label><input class="ut-input" id="p" type="password" autocomplete="current-password"></div>
    <div id="lerr" class="ut-callout ut-callout--danger" hidden></div>
    <button class="ut-btn ut-btn--primary ut-btn--lg" style="width:100%">Sign in</button>
    <button class="ut-btn ut-btn--ghost" id="lapp" type="button" style="width:100%;margin-top:8px">Sign in with the UntrashApp</button>
    <div id="lwait"></div>
    <div class="ut-login__foot">Sign in with your existing password (as on the Zyxel firmware)<br><a href="/manual/" target="_blank" rel="noopener">User guide</a></div></form></main>`;
  $('#p').focus();
  $('#lf').onsubmit = async e => {
    e.preventDefault();
    try {
      const r = await api('login', { user: $('#u').value.trim(), password: $('#p').value });
      if (r.second) await loginWait(r.second, r.code);       // second factor
      boot();
    } catch (err) { $('#lerr').hidden = false; $('#lerr').textContent = err.message; }
  };
  $('#lapp').onclick = async () => {
    $('#lerr').hidden = true;
    try { const r = await api('login/app', { user: $('#u').value.trim() }); await loginWait(r.id, r.code); boot(); }
    catch (err) { $('#lerr').hidden = false; $('#lerr').textContent = err.message; }
  };
}
async function loginWait(id, code) {
  const w = $('#lwait'), hide = $$('#lf > .ut-field, #lf > .ut-btn');
  hide.forEach(x => x.hidden = true);
  try { await appWait({ code, into: w, poll: () => apiRaw('login/app?id=' + encodeURIComponent(id)) }); }
  finally { w.innerHTML = ''; hide.forEach(x => x.hidden = false); }
}
function setupScreen(st) {
  $('#app').innerHTML = `<main class="ut-login"><form class="ut-login__card" id="sf">
    <img class="ut-login__logo" src="/ut/assets/logo-mark-192.png" alt=""><img class="ut-login__word" src="/ut/assets/wordmark-300.png" alt="UntrashOS">
    <div class="ut-login__host">First setup</div>
    <div class="ut-field"><label for="n">Network name</label><input class="ut-input" id="n" maxlength="15" value="${esc(st.hostname || 'untrash')}"></div>
    <div class="ut-field"><label for="p1">Password for admin (at least 8 characters)</label><input class="ut-input" id="p1" type="password" autocomplete="new-password"></div>
    <div class="ut-field"><label for="p2">Repeat password</label><input class="ut-input" id="p2" type="password" autocomplete="new-password"></div>
    <div id="lerr" class="ut-callout ut-callout--danger" hidden></div>
    <button class="ut-btn ut-btn--primary ut-btn--lg" style="width:100%">Set up</button></form></main>`;
  $('#sf').onsubmit = async e => {
    e.preventDefault();
    const err = m => { $('#lerr').hidden = false; $('#lerr').textContent = m; };
    if ($('#p1').value !== $('#p2').value) return err('The passwords do not match.');
    try { await api('setup', { name: $('#n').value.trim(), password: $('#p1').value }); toast('Configured', 'Now sign in as admin.'); boot(); }
    catch (x) { err(x.message); }
  };
}

/* ---------------------------------------------------------------- desk */
const APPS = {
  overview: { name: 'Overview', icon: 'monitor', w: 760, h: 520 },
  files: { name: 'Files', icon: 'files', w: 820, h: 540, user: true },
  shares: { name: 'Shares', icon: 'shares', w: 860, h: 560 },
  storage: { name: 'Storage', icon: 'storage', w: 860, h: 560 },
  users: { name: 'Users', icon: 'users', w: 820, h: 540 },
  network: { name: 'Network', icon: 'network', w: 700, h: 560 },
  settings: { name: 'Settings', icon: 'settings', w: 820, h: 580 },
  cloud: { name: 'Cloud', icon: 'backup', w: 820, h: 560 },
  downloads: { name: 'Downloads', icon: 'apps', w: 820, h: 560 },
  transfers: { name: 'Transfers', icon: 'files', w: 880, h: 540, user: true },
  backup: { name: 'Backup', icon: 'raid', w: 860, h: 580 },
  updates: { name: 'Updates', icon: 'updates', w: 640, h: 460 },
  logs: { name: 'Logs', icon: 'logs', w: 860, h: 520 },
  status: { name: 'Status', icon: 'status', w: 760, h: 540 },
  terminal: { name: 'Terminal', icon: 'terminal', w: 860, h: 520 },
  mesh: { name: 'UntrashMesh', icon: 'mesh', w: 860, h: 600 },
  sound: { name: 'Sounds', icon: 'synth', w: 1040, h: 700 },
  feedback: { name: 'Feedback', icon: 'feedback', w: 720, h: 600 },
  manual: { name: 'Manual', icon: 'manual', w: 940, h: 640, user: true },
  media: { name: 'Media server', icon: 'mediaserver', w: 860, h: 580 },
  adblock: { name: 'Ad filter', icon: 'adblock', w: 900, h: 600 },
  tv: { name: 'Channels', icon: 'tv', w: 960, h: 600, user: true },
  player: { name: 'Player', icon: 'player', w: 900, h: 560, user: true, hidden: true },
  account: { name: 'My account', icon: 'users', w: 480, h: 360, user: true },
};
/* the admin dock: two apps direct, the rest in categories that open a popup */
const DOCK_ADMIN = ['overview', 'files',
  { g: 'data', name: 'Data', apps: ['shares', 'storage', 'transfers', 'backup', 'cloud', 'downloads'] },
  { g: 'net', name: 'Network', apps: ['network', 'mesh', 'adblock'] },
  { g: 'media', name: 'Media', apps: ['media', 'tv', 'sound'] },
  { g: 'system', name: 'System', apps: ['status', 'users', 'settings', 'updates', 'logs', 'terminal'] },
  { g: 'help', name: 'Help', apps: ['manual', 'feedback'] }];
const dockItem = k => `<button class="ut-dock__item" data-app="${k}" aria-label="${APPS[k].name}"><img src="${ICON(APPS[k].icon)}" alt=""><span class="ut-tip">${APPS[k].name}</span></button>`;
const dockGroup = g => `<button class="ut-dock__item ut-dock__group" data-group="${g.g}" aria-label="${g.name}" aria-haspopup="menu" aria-expanded="false">
  <span class="ut-dock__stack">${g.apps.slice(0, 4).map(k => `<img src="${ICON(APPS[k].icon)}" alt="">`).join('')}</span><span class="ut-tip">${g.name}</span></button>`;
function dockPopup(btn) {
  const open = $('.ut-dock-pop'), g = DOCK_ADMIN.find(x => x.g === btn.dataset.group);
  closeDockPopup();
  if (open && open.dataset.group === g.g) return;            // a second click closes it
  const p = document.createElement('div');
  p.className = 'ut-menu ut-dock-pop'; p.dataset.group = g.g; p.setAttribute('role', 'menu'); p.setAttribute('aria-label', UTI18N.tr(g.name));
  p.innerHTML = `<div class="ut-menu__label">${esc(UTI18N.tr(g.name))}</div><div class="ut-dock-pop__grid">${g.apps.map(k =>
    `<button class="ut-launcher__app" role="menuitem" data-app="${k}"><img src="${ICON(APPS[k].icon)}" alt=""><span>${esc(UTI18N.tr(APPS[k].name))}</span></button>`).join('')}</div>`;
  document.body.append(p);
  const r = btn.getBoundingClientRect(), w = p.offsetWidth;
  p.style.left = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2)) + 'px';
  p.style.bottom = (innerHeight - r.top + 14) + 'px';
  btn.setAttribute('aria-expanded', 'true');
  const items = $$('[data-app]', p);
  items[0].focus();
  p.addEventListener('keydown', e => {
    const i = items.indexOf(document.activeElement);
    if (e.key === 'Escape') { closeDockPopup(); btn.focus(); }
    else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
  });
  p.addEventListener('click', e => { const a = e.target.closest('[data-app]'); if (a) { closeDockPopup(); openApp(a.dataset.app); } });
}
function closeDockPopup() {
  $$('.ut-dock-pop').forEach(x => x.remove());
  $$('.ut-dock__group[aria-expanded=true]').forEach(x => x.setAttribute('aria-expanded', 'false'));
}
document.addEventListener('pointerdown', e => { if (!e.target.closest('.ut-dock-pop, .ut-dock__group')) closeDockPopup(); });
addEventListener('resize', closeDockPopup);

function desk(st) {
  const apps = Object.keys(APPS).filter(k => (ME.admin || APPS[k].user) && !APPS[k].hidden);
  const dock = ME.admin ? DOCK_ADMIN : ['files', 'transfers', 'tv', 'manual', 'account'];
  $('#app').innerHTML = `<div class="ut-desk" id="desk">
    <header class="ut-topbar"><span class="ut-topbar__item"><img src="/ut/assets/logo-mark-48.png" alt=""><span class="ut-topbar__title">Untrash<span style="color:var(--ut-teal)">OS</span></span></span>
      <span class="ut-topbar__item" id="active-title">${esc(st.hostname)}</span><div class="ut-topbar__spacer"></div>
      <span class="ut-topbar__item ut-activity" id="activity" aria-live="polite"></span>
      <button class="ut-topbar__item ut-ops-btn" id="ops-btn" hidden></button>
      <span class="ut-topbar__item" id="raid-pill"></span>
      <button class="ut-topbar__item" id="user-btn" translate="no">${esc(ME.user)}</button><span class="ut-topbar__item" id="clock"></span></header>
    <nav class="ut-desktop-icons">${apps.filter(k => k !== 'account').slice(0, 6).map(k => `<button class="ut-desk-icon" data-app="${k}"><img src="${ICON(APPS[k].icon)}" alt="">${APPS[k].name}</button>`).join('')}</nav>
    <div id="windows"></div><div class="ut-toasts" id="toasts" aria-live="polite"></div>
    <nav class="ut-dock" aria-label="Dock" style="--dock-n:${dock.length + (ME.admin ? 1 : 0)}">${dock.map(k => typeof k === 'string' ? dockItem(k) : dockGroup(k)).join('')}
      ${ME.admin ? '<span class="ut-dock__sep"></span><button class="ut-dock__item" data-power aria-label="Switch off"><img src="' + ICON('power') + '" alt=""><span class="ut-tip">Switch off</span></button>' : ''}</nav></div>`;
  $('#desk').addEventListener('click', e => {
    const b = e.target.closest('[data-app]'); if (b && !b.closest('.ut-window')) openApp(b.dataset.app);
    if (e.target.closest('[data-power]')) powerDialog();
    const g = e.target.closest('[data-group]'); if (g) dockPopup(g);
  });
  $('#desk').addEventListener('dblclick', e => { const b = e.target.closest('.ut-desk-icon'); if (b) openApp(b.dataset.app); });
  $('#user-btn').onclick = () => {
    const d = dialog({ title: 'Account', body: `<p>Signed in as <b translate="no">${esc(ME.user)}</b>.</p>
      <div class="ut-field"><label for="ulang">Language of this browser</label>${langSel('ulang', UTI18N.own, true)}</div>
      ${signinFields()}<div class="ut-section-title">Appearance</div>${appearanceFields()}`, ok: 'Sign out',
      onOk: async () => { await api('logout', {}); location.reload(); } });
    $('#ulang', d).onchange = e => UTI18N.set(e.target.value);
    appearanceBind(d); signinBind(d);
  };
  const tick = () => $('#clock') && ($('#clock').textContent = new Date().toLocaleString(UTI18N.locale, { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }));
  tick(); setInterval(tick, 15000);
  $('#ops-btn').onclick = () => openApp('transfers');
  const ob = single(opsBadge); ob(); setInterval(ob, 4000);
  if (ME.admin) { const rp = single(raidPill), ab = single(activityBar); rp(); setInterval(rp, 60000); ab(); setInterval(ab, 5000); openApp('overview'); 
    api('update').then(u => { const r = u.release || {}; if (r.available && (r.download || {}).state === 'ready') toast('Update', UTI18N.tr('UntrashOS %s is downloaded and checked; install it under Updates.').replace('%s', r.available.version)); }).catch(() => { }); } else openApp('files');
}
// polling: never a second request while the first is still open.  Browsers
// allow 6 connections per server; slow answers that piled up blocked every
// other request, also uploads.
function single(fn) { let busy = false; return async (...a) => { if (busy) return; busy = true; try { return await fn(...a); } finally { busy = false; } }; }
async function raidPill() {
  try {
    const o = await api('overview');
    const deg = o.arrays.filter(a => a.degraded).length;
    $('#raid-pill').innerHTML = o.arrays.length ? `<span class="ut-pill ${deg ? 'ut-pill--danger' : 'ut-pill--ok'}" style="height:18px">${deg ? 'RAID incomplete' : 'RAID ok'}</span>` : '';
  } catch (e) { }
}

/* status bar: what the NAS is doing right now (DLNA indexing, streams, SMB, RAID, jobs) */
const ACT_ICON = { adblock: '🛡', tv: '📡', index: '⟳', stream: '▶', smb: '⇄', raid: '◎', job: '⧗', download: '↓', encode: '⚙', update: '⬆' };
async function activityBar() {
  const el = $('#activity'); if (!el || document.hidden) return;
  try {
    const a = (await api('activity')).activities;
    el.innerHTML = a.length ? a.map(x => `<span class="ut-act ut-act--${esc(x.kind)}" title="${esc(x.text)}"><i>${ACT_ICON[x.kind] || '•'}</i>${esc(x.text)}</span>`).join('')
      : '<span class="ut-act ut-act--idle"><i>●</i>Idle</span>';
  } catch (e) { }
}

/* top bar: running transfers (copy/move, uploads, downloads) of this user, of all for admins */
async function opsBadge() {
  const el = $('#ops-btn'); if (!el || document.hidden) return;
  try {
    const run = (await apiRaw('transfers')).ops.filter(o => o.state === 'running' || o.state === 'paused');
    el.hidden = !run.length;
    if (!run.length) return;
    const tot = run.reduce((a, o) => a + (o.total || 0), 0), done = run.reduce((a, o) => a + (o.total ? o.done : 0), 0);
    const txt = UTI18N.tr(run.length === 1 ? '1 transfer' : '%s transfers').replace('%s', run.length) + (tot ? ' · ' + Math.floor(100 * done / tot) + ' %' : '');
    el.innerHTML = `<i>⇅</i>${esc(txt)}`;
    el.title = run.map(o => o.name).join('\n');
  } catch (e) { }
}

let Z = 10, N = 0;
const CLEANUP = {};   // per window: stop polling, close sockets
const wins = {};
function openApp(k) {
  if (wins[k]) { wins[k].hidden = false; return focusWin(wins[k]); }
  const a = APPS[k], w = document.createElement('section');
  let sz = null; try { sz = JSON.parse(localStorage.getItem('ut-win-' + k)); } catch (e) { }   // last size of this window, per browser
  const W = Math.min((sz && sz.w) || a.w || 720, innerWidth - 16), H = Math.min((sz && sz.h) || a.h || 480, innerHeight - 130);
  w.className = 'ut-window'; w.dataset.app = k;
  w.style.cssText = `width:${W}px;height:${H}px;left:${Math.max(8, (innerWidth - W) / 2 - 40 + (N % 5) * 30)}px;top:${50 + (N++ % 5) * 26}px`;
  w.innerHTML = `<div class="ut-window__bar"><img src="${ICON(a.icon)}" alt=""><span class="ut-window__title">${a.name}</span>
    <div class="ut-window__ctl"><button data-act="max" aria-label="Maximise">▢</button><button data-act="close" aria-label="Close">✕</button></div></div>
    <div class="ut-window__body"><div class="ut-window__main"><span class="ut-spinner"></span></div></div>
    ${['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'].map(d => `<i class="ut-rz ut-rz--${d}" data-rz="${d}"></i>`).join('')}`;
  $('#windows').append(w); wins[k] = w;
  w.addEventListener('mousedown', () => focusWin(w));
  w.querySelector('[data-act=close]').onclick = () => { if (CLEANUP[k]) { CLEANUP[k](); delete CLEANUP[k]; } w.remove(); delete wins[k]; };
  const max = () => {
    if (w.dataset.max) { const z = w.style.zIndex; w.style.cssText = w.dataset.max; w.style.zIndex = z; delete w.dataset.max; }
    else { w.dataset.max = w.style.cssText; Object.assign(w.style, { left: '4px', top: 'calc(var(--ut-topbar-h) + 4px)', width: 'calc(100% - 8px)', height: 'calc(100% - var(--ut-topbar-h) - 86px)' }); }
  };
  w.querySelector('[data-act=max]').onclick = max;
  w.querySelector('.ut-window__bar').addEventListener('dblclick', e => { if (!e.target.closest('button')) max(); });
  drag(w, w.querySelector('.ut-window__bar'));
  resizable(w, k);
  focusWin(w);
  render(k);
}
function focusWin(w) {
  Object.values(wins).forEach(x => x.removeAttribute('data-active'));
  w.setAttribute('data-active', ''); w.style.zIndex = ++Z;
  $('#active-title').textContent = APPS[w.dataset.app].name;
}
function drag(w, handle) {
  handle.addEventListener('pointerdown', e => {
    if (e.target.closest('button') || w.dataset.max) return;
    const sx = e.clientX - w.offsetLeft, sy = e.clientY - w.offsetTop;
    const mv = e => { w.style.left = (e.clientX - sx) + 'px'; w.style.top = Math.max(34, e.clientY - sy) + 'px'; };
    const up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); };
    addEventListener('pointermove', mv); addEventListener('pointerup', up);
  });
}
// edges and corners resize the window; the size is remembered per app in this browser
function resizable(w, k) {
  const MW = 320, MH = 200;
  w.querySelectorAll('[data-rz]').forEach(h => h.addEventListener('pointerdown', e => {
    if (w.dataset.max) return;
    e.preventDefault(); e.stopPropagation(); focusWin(w);
    const d = h.dataset.rz, x0 = e.clientX, y0 = e.clientY;
    const r = { l: w.offsetLeft, t: w.offsetTop, w: w.offsetWidth, h: w.offsetHeight };
    document.body.classList.add('ut-resizing'); document.body.dataset.rz = d;
    const mv = e => {
      const dx = e.clientX - x0, dy = e.clientY - y0;
      if (d.includes('e')) w.style.width = Math.max(MW, Math.min(r.w + dx, innerWidth - r.l - 4)) + 'px';
      if (d.includes('s')) w.style.height = Math.max(MH, Math.min(r.h + dy, innerHeight - r.t - 4)) + 'px';
      if (d.includes('w')) { const nw = Math.max(MW, Math.min(r.w - dx, r.l + r.w - 4)); w.style.width = nw + 'px'; w.style.left = (r.l + r.w - nw) + 'px'; }
      if (d.includes('n')) { const nh = Math.max(MH, Math.min(r.h - dy, r.t + r.h - 34)); w.style.height = nh + 'px'; w.style.top = (r.t + r.h - nh) + 'px'; }
    };
    const up = () => {
      removeEventListener('pointermove', mv); removeEventListener('pointerup', up);
      document.body.classList.remove('ut-resizing'); delete document.body.dataset.rz;
      try { localStorage.setItem('ut-win-' + k, JSON.stringify({ w: w.offsetWidth, h: w.offsetHeight })); } catch (e) { }
    };
    addEventListener('pointermove', mv); addEventListener('pointerup', up);
  }));
}
const body = k => wins[k] && wins[k].querySelector('.ut-window__body');
async function render(k, arg) {
  const b = body(k); if (!b) return;
  try { await VIEWS[k](b, arg); } catch (e) { b.innerHTML = `<div class="ut-window__main"><div class="ut-callout ut-callout--danger">${esc(e.message)}</div></div>`; }
}
// names of shares, users and groups are data: never translated (i18n.js skips translate="no")
// language choice: native names, never translated
const langSel = (id, cur, withSystem) => `<select class="ut-select" id="${id}" translate="no">${withSystem ? `<option value=""${cur ? '' : ' selected'}>— ${esc(UTI18N.tr('as system'))} —</option>` : ''}
  ${Object.entries(UTI18N.langs).map(([k, n]) => `<option value="${k}"${k === cur ? ' selected' : ''}>${n}</option>`).join('')}</select>`;
const sidebar = (k, items, cur) => `<aside class="ut-sidebar">${items.map(([id, label, data]) => id[0] === '#' ? `<div class="ut-sidebar__group">${esc(label)}</div>`
  : `<button class="ut-nav" data-nav="${id}"${id === cur ? ' aria-current="page"' : ''}><span${data || /^[sugx]:/.test(id) ? ' translate="no"' : ''}>${esc(label)}</span></button>`).join('')}</aside>`;
function navBind(b, k) { $$('[data-nav]', b).forEach(n => n.onclick = () => render(k, n.dataset.nav)); }
/* appearance per user (design/theme.js; stored on the NAS, /api/prefs) */
const THEMES = [['auto', 'Automatic (as the system)'], ['dark', 'Dark'], ['light', 'Light'], ['contrast', 'High contrast']];
const CVDS = [['none', 'Normal colour vision'], ['protan', 'Red-weak (protanopia)'], ['deutan', 'Green-weak (deuteranopia)'],
  ['tritan', 'Blue-weak (tritanopia)'], ['achroma', 'No colour vision (achromatopsia)']];
const opts = (list, cur) => list.map(([k, n]) => `<option value="${k}"${k === cur ? ' selected' : ''}>${esc(n)}</option>`).join('');
function appearanceFields() {
  const p = window.UTTHEME ? UTTHEME.prefs : { theme: 'dark', cvd: 'none', motion: 'auto' };
  return `<div class="ut-field"><label for="ap-theme">Theme</label><select class="ut-select" id="ap-theme">${opts(THEMES, p.theme)}</select></div>
    <div class="ut-field"><label for="ap-cvd">Colour vision</label><select class="ut-select" id="ap-cvd">${opts(CVDS, p.cvd)}</select>
    <span class="ut-hint">Other colours for states, plus a symbol on each, so that no state depends on colour alone.</span></div>
    ${sw('ap-motion', p.motion === 'reduce', 'Reduce motion')}`;
}
function appearanceBind(root) {
  const go = () => {
    const p = { theme: $('#ap-theme', root).value, cvd: $('#ap-cvd', root).value, motion: $('#ap-motion', root).checked ? 'reduce' : 'auto' };
    UTTHEME.set(p);
    api('prefs', p).catch(fail);
  };
  ['#ap-theme', '#ap-cvd', '#ap-motion'].forEach(q => { $(q, root).onchange = go; });
}
const sw = (id, on, label) => `<label class="ut-switch"><input type="checkbox" id="${id}"${on ? ' checked' : ''}><i></i>${esc(label)}</label>`;
const field = (id, label, val = '', extra = '') => `<div class="ut-field"><label for="${id}">${esc(label)}</label><input class="ut-input" id="${id}" value="${esc(val)}" ${extra}></div>`;
async function save(what, req, k, arg) {
  try { await api(what, req); toast('Saved'); if (k) render(k, arg); } catch (e) { fail(e); }
}

/* ---------------------------------------------------------------- views */
const VIEWS = {};
VIEWS.overview = async b => {
  const o = await api('overview');
  const up = o.uptime > 86400 ? Math.floor(o.uptime / 86400) + ' d' : Math.floor(o.uptime / 3600) + ' h';
  const memUsed = o.mem_total - o.mem_avail;
  const svc = Object.entries(o.services).map(([u, s]) => `<span class="ut-pill ${s === 'active' ? 'ut-pill--ok' : 'ut-pill--plain'}">${esc(u)}: ${s === 'active' ? 'running' : 'off'}</span>`).join(' ');
  b.innerHTML = `<div class="ut-window__main">
    <div class="grid-3"><div class="ut-stat"><div class="ut-stat__label">UntrashOS</div><div class="ut-stat__value" style="font-size:16px">${esc(o.version)}</div></div>
      <div class="ut-stat"><div class="ut-stat__label">Uptime · load</div><div class="ut-stat__value">${up}<small> · ${esc(o.load.join(' '))}</small></div></div>
      <div class="ut-stat"><div class="ut-stat__label">Memory (RAM)</div><div class="ut-stat__value">${(memUsed / 1048576).toFixed(0)}<small>/ ${(o.mem_total / 1048576).toFixed(0)} MB</small></div></div></div>
    ${o.unsupported.length ? `<div class="ut-callout ut-callout--warn" style="margin-bottom:12px"><div><b>Active on stock, not taken over in UntrashOS:</b><ul>${o.unsupported.map(x => `<li>${esc(x)}</li>`).join('')}</ul></div></div>` : ''}
    <div class="ut-section-title">Volumes</div><div class="ut-card">${o.volumes.length ? o.volumes.map(v => {
      const used = v.size ? Math.round(100 * (v.size - v.free) / v.size) : 0;
      return `<div class="vol"><div><b>${esc(v.label)}</b> <span class="ut-faint">· ${esc(v.path)}${v.kind === 'usb' ? ' · USB' : v.kind === 'partner' ? ' · ' + esc(UTI18N.tr('partner volume')) : ''}</span></div><span class="ut-pill ut-pill--ok">ready</span>
        <div class="ut-progress ${used > 90 ? 'ut-progress--danger' : used > 75 ? 'ut-progress--warn' : ''}" style="--v:${used}%"><i></i></div><span class="ut-faint">${gb(v.size - v.free)} of ${gb(v.size)} used</span></div>`;
    }).join('') : '<div class="empty">No data volume mounted.</div>'}</div>
    ${o.arrays.length ? `<div class="ut-section-title">RAID</div><div class="ut-card">${o.arrays.map(a => `<div class="row"><b>${esc(a.name)}</b> ${esc(a.level)} [${esc(a.health)}] <span class="ut-pill ${a.degraded ? 'ut-pill--danger' : 'ut-pill--ok'}">${a.degraded ? 'incomplete' : 'healthy'}</span></div>`).join('')}</div>` : ''}
    <div class="ut-section-title">Network</div><div class="ut-card mono">${o.addresses.map(a => esc(a.if + '  ' + a.addr)).join('<br>') || '–'}</div>
    <div class="ut-section-title">Services</div><div class="row">${svc}</div></div>`;
};

/* files ---------------------------------------------------------------- */
const FS = { share: null, path: '', sel: new Set(), last: null, sort: 'name', dir: 1, filter: '', search: null, entries: [], recycle: false };
let CLIP = null;                                  // { op: 'cut' | 'copy', share, from, items: [names] }
const XFER = [];                                  // uploads and copy/move jobs shown in the Files window
/* opens a document in the office server's editor (WOPI) in a new tab: the
   tab frames the editor (iframe), the token goes as a form POST, never in
   an address bar.  The frame answers the editor's postMessages: Save As /
   Export ask for a name and save a copy on the NAS (PutRelativeFile),
   Close closes the tab. */
async function officeOpen(share, path) {
  const w = window.open('', '_blank');
  if (!w) return fail(new Error(UTI18N.tr('The browser blocked the new tab.')));
  try {
    const r = await api('office/open', { share, path, lang: UTI18N.lang, origin: location.origin });
    const name = path.split('/').pop(), office = new URL(r.url).origin, d = w.document;
    d.open();
    d.write(`<!doctype html><meta charset="utf-8"><title>${esc(name)}</title><style>html,body{margin:0;height:100%;background:#0d1115}iframe{border:0;width:100%;height:100%;display:block}</style>
      <iframe name="ed" title="${esc(name)}" allow="clipboard-read *; clipboard-write *; fullscreen"></iframe>`);
    d.close();
    const f = d.createElement('form');
    f.method = 'POST'; f.action = r.url; f.target = 'ed';
    for (const [k, v] of [['access_token', r.access_token], ['access_token_ttl', r.access_token_ttl]]) {
      const i = d.createElement('input'); i.type = 'hidden'; i.name = k; i.value = v; f.append(i);
    }
    d.body.append(f); f.submit();
    const send = (id, values) => d.querySelector('iframe').contentWindow.postMessage(JSON.stringify({ MessageId: id, SendTime: Date.now(), Values: values || {} }), office);
    w.addEventListener('message', e => {
      if (e.origin !== office) return;
      let m;
      try { m = typeof e.data === 'string' ? JSON.parse(e.data) : e.data; } catch (x) { return; }
      const v = (m && m.Values) || {};
      if (m.MessageId === 'App_LoadingStatus' && v.Status === 'Frame_Ready') send('Host_PostmessageReady');
      else if (m.MessageId === 'UI_SaveAs') {
        const ext = v.format || name.split('.').pop();
        d.querySelectorAll('.sa').forEach(x => x.remove());
        const bar = d.createElement('form');
        bar.className = 'sa';
        bar.style.cssText = 'position:fixed;left:50%;top:12px;transform:translateX(-50%);z-index:9;display:flex;gap:8px;align-items:center;padding:10px 12px;'
          + 'background:#161c22;color:#e6edf3;border:1px solid #2c3640;border-radius:10px;font:14px system-ui,sans-serif;box-shadow:0 8px 30px #000a';
        bar.innerHTML = `<label for="san">${esc(UTI18N.tr('Save a copy in the same folder on the NAS as:'))}</label>
          <input id="san" style="width:260px;padding:6px 8px;border-radius:6px;border:1px solid #2c3640;background:#0d1115;color:inherit" value="${esc(name.replace(/\.[^.]+$/, '') + '.' + ext)}">
          <button style="padding:6px 12px;border:0;border-radius:6px;background:#2ee6a6;color:#04120d;font-weight:600">${esc(UTI18N.tr('Save'))}</button>
          <button type="button" data-x style="padding:6px 12px;border:1px solid #2c3640;border-radius:6px;background:none;color:inherit">${esc(UTI18N.tr('Cancel'))}</button>`;
        d.body.append(bar);
        const inp = bar.querySelector('#san'); inp.focus(); inp.setSelectionRange(0, inp.value.lastIndexOf('.') > 0 ? inp.value.lastIndexOf('.') : inp.value.length);
        bar.querySelector('[data-x]').onclick = () => bar.remove();
        bar.onsubmit = ev => { ev.preventDefault(); const n = inp.value.trim(); bar.remove(); if (n) send('Action_SaveAs', { Filename: n, Notify: true }); };
      } else if (m.MessageId === 'UI_Close') w.close();
    });
  } catch (e) { w.close(); fail(e); }
}
/* context menu at x, y: items [{ label, fn, danger, disabled }] or 'sep' */
function ctxMenu(x, y, items) {
  $$('.ut-ctx').forEach(m => m.remove());
  const m = document.createElement('div');
  m.className = 'ut-menu ut-ctx'; m.setAttribute('role', 'menu');
  m.innerHTML = items.map((it, i) => it === 'sep' ? '<div class="ut-menu__sep"></div>'
    : `<button class="ut-menu__item${it.danger ? ' ut-menu__item--danger' : ''}" role="menuitem" data-i="${i}"${it.disabled ? ' disabled' : ''}>${esc(it.label)}${it.key ? `<kbd>${esc(it.key)}</kbd>` : ''}</button>`).join('');
  document.body.append(m);
  m.style.left = Math.max(4, Math.min(innerWidth - m.offsetWidth - 4, x)) + 'px';
  m.style.top = Math.max(4, Math.min(innerHeight - m.offsetHeight - 4, y)) + 'px';
  const close = () => { m.remove(); document.removeEventListener('pointerdown', out, true); document.removeEventListener('keydown', esck, true); };
  const out = e => { if (!m.contains(e.target)) close(); };
  const esck = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  setTimeout(() => { document.addEventListener('pointerdown', out, true); document.addEventListener('keydown', esck, true); });
  m.onclick = e => { const b = e.target.closest('[data-i]'); if (b && !b.disabled) { close(); items[+b.dataset.i].fn(); } };
  const first = m.querySelector('button:enabled'); if (first) first.focus();
}
const fpath = n => (FS.path ? FS.path + '/' : '') + n;
const nItems = n => n === 1 ? UTI18N.tr('1 item') : UTI18N.tr('%s items').replace('%s', n);
const fsel = () => FS.entries.filter(e => FS.sel.has(e.name));

/* transfers (uploads with progress, copy/move jobs of the NAS) */
function xferPanel() {
  const b = body('files'), box = b && $('#fxfer', b);
  if (!box) return;
  const live = XFER.filter(x => !x.gone);
  box.hidden = !live.length;
  box.innerHTML = `<div class="ut-xfer__head"><button class="ut-btn ut-btn--sm ut-btn--ghost" data-xall>All transfers …</button></div>` + live.map((x, i) => {
    const pct = x.total ? Math.min(100, Math.round(100 * x.done / x.total)) : (x.state === 'running' ? 0 : 100);
    const label = x.kind === 'up' ? UTI18N.tr('Upload') : UTI18N.tr(x.op === 'move' ? 'Move' : 'Copy');
    const st = x.state === 'running' ? `${pct} %` : esc(UTI18N.tr({ done: 'done', errors: 'with errors', cancelled: 'cancelled', paused: 'paused' }[x.state] || x.state));
    return `<div class="ut-xfer"><span class="ut-xfer__name"><b>${esc(label)}</b> <span translate="no">${esc(x.name || '')}</span></span>
      <div class="ut-progress" style="--v:${pct}%"><i></i></div><span class="ut-faint">${st}</span>
      ${x.state === 'running' || x.state === 'paused' ? `<button class="ut-btn ut-btn--sm ut-btn--ghost" data-xc="${i}">Cancel</button>` : `<button class="ut-btn ut-btn--sm ut-btn--ghost" data-xd="${i}" aria-label="Close">✕</button>`}
      ${(x.errors || []).length ? `<div class="ut-faint ut-xfer__err" translate="no">${x.errors.map(esc).join('<br>')}</div>` : ''}</div>`;
  }).join('');
  $$('[data-xc]', box).forEach(btn => btn.onclick = () => { const x = live[+btn.dataset.xc]; x.cancel && x.cancel(); });
  $$('[data-xd]', box).forEach(btn => btn.onclick = () => { live[+btn.dataset.xd].gone = true; xferPanel(); });
  $('[data-xall]', box).onclick = () => openApp('transfers');
}
function uploadFile(share, path, file, dirs) {
  return new Promise((resolve, reject) => {
    const x = { kind: 'up', name: (dirs ? dirs + '/' : '') + file.name, total: file.size, done: 0, state: 'running' };
    XFER.push(x); xferPanel();
    const r = new XMLHttpRequest();
    r.open('POST', '/api/files/upload?' + new URLSearchParams(Object.assign({ share, path, name: file.name }, dirs ? { dirs } : {})));
    r.setRequestHeader('X-UT', '1'); r.setRequestHeader('Content-Type', 'application/octet-stream');
    r.upload.onprogress = e => { x.done = e.loaded; xferPanel(); };
    const end = (state, err) => { x.state = state; if (err) x.errors = [err]; xferPanel(); if (state === 'done') setTimeout(() => { x.gone = true; xferPanel(); }, 4000); };
    r.onload = () => { if (r.status === 200) { end('done'); resolve(); } else { let m = 'Error ' + r.status; try { m = JSON.parse(r.responseText).error || m; } catch (e) { } end('errors', m); reject(new Error(m)); } };
    r.onerror = () => { end('errors', UTI18N.tr('Transfer aborted.')); reject(new Error('Transfer aborted.')); };
    r.onabort = () => { end('cancelled'); reject(new Error('Cancelled.')); };
    x.cancel = () => r.abort();
    r.send(file);
  });
}
/* files dropped or picked: [{ file, dirs }] (dirs = subfolder path for folder uploads) */
async function uploadAll(share, path, list) {
  for (const it of list) { try { await uploadFile(share, path, it.file, it.dirs); } catch (e) { if (e.message !== 'Cancelled.') toast(it.file.name, e.message, 'danger'); } }
  if (FS.share === share && body('files')) render('files');
}
/* the files of a drop, folders read recursively (webkitGetAsEntry) */
async function droppedFiles(dt) {
  const out = [], walk = (entry, dirs) => new Promise(res => {
    if (entry.isFile) entry.file(f => { out.push({ file: f, dirs }); res(); }, () => res());
    else if (entry.isDirectory) {
      const rd = entry.createReader(), all = [];
      const more = () => rd.readEntries(async es => { if (es.length) { all.push(...es); more(); } else { for (const e of all) await walk(e, (dirs ? dirs + '/' : '') + entry.name); res(); } }, () => res());
      more();
    } else res();
  });
  const entries = [...(dt.items || [])].map(i => i.webkitGetAsEntry && i.webkitGetAsEntry()).filter(Boolean);
  if (entries.length) { for (const e of entries) await walk(e, ''); return out; }
  return [...dt.files].map(f => ({ file: f, dirs: '' }));
}
async function startTransfer(op, share, from, names, dst, conflict = 'rename') {
  const r = await api('files/transfer', { op, conflict, items: names.map(n => ({ share, path: (from ? from + '/' : '') + n })), dst });
  const x = { kind: 'job', id: r.job, op, name: names.length === 1 ? names[0] : nItems(names.length), total: 0, done: 0, state: 'running',
    cancel: () => api('files/jobs/cancel', { job: r.job }).catch(fail) };
  XFER.push(x); xferPanel(); pollJobs();
}
const pollJobs = single(async () => {
  const live = x => x.kind === 'job' && (x.state === 'running' || x.state === 'paused');
  while (XFER.some(live)) {
    try {
      const js = (await apiRaw('files/jobs')).jobs;
      for (const x of XFER.filter(live)) {
        const j = js.find(j => j.id === x.id); if (!j) { x.state = 'errors'; continue; }
        Object.assign(x, { total: j.total, done: j.done, state: j.state, errors: j.errors });
        if (j.state !== 'running' && j.state !== 'paused') {
          if (body('files')) render('files');
          if (j.state === 'done') setTimeout(() => { x.gone = true; xferPanel(); }, 4000);
        }
      }
      xferPanel();
    } catch (e) { break; }
    await new Promise(r => setTimeout(r, 900));
  }
});

function fileOpen(b, e) {
  const n = e.name, rel = fpath;
  if (e.dir) { FS.path = rel(n); FS.sel.clear(); FS.search = null; return render('files'); }
  const files = FS.entries.filter(x => !x.dir);
  if (/^(audio|video)$/.test(mediaKind(n))) openPlayer(files.filter(x => /^(audio|video)$/.test(mediaKind(x.name))).map(x => x.name), n, rel);
  else if (mediaKind(n) === 'img') viewer(files.filter(x => mediaKind(x.name) === 'img').map(x => x.name), n, rel);
  else if (/^(pdf|text)$/.test(mediaKind(n))) docViewer(n, rel(n), e.size || 0);
  else location.href = '/api/files/download?' + new URLSearchParams({ share: FS.share, path: rel(n) });
}
function fileDownload(items) {
  if (items.length === 1 && !items[0].dir) location.href = '/api/files/download?' + new URLSearchParams({ share: FS.share, path: fpath(items[0].name) });
  else location.href = '/api/files/zip?' + new URLSearchParams({ share: FS.share, path: FS.path, names: JSON.stringify(items.map(e => e.name)) });
}
function fileCut(op, items) {
  if (!items.length) return;
  CLIP = { op, share: FS.share, from: FS.path, items: items.map(e => e.name) };
  toast(UTI18N.tr(op === 'cut' ? 'Cut' : 'Copied'), nItems(items.length) + ' · ' + UTI18N.tr('Paste in the target folder'));
  render('files');
}
async function filePaste(dstPath = FS.path) {
  if (!CLIP) return;
  const same = CLIP.share === FS.share && CLIP.from === dstPath;
  if (CLIP.op === 'cut' && same) return;
  const there = dstPath === FS.path ? FS.entries.map(e => e.name) : [];
  const clash = !same && CLIP.items.filter(n => there.includes(n));
  const go = async conflict => {
    const c = CLIP;
    try { await startTransfer(c.op === 'cut' ? 'move' : 'copy', c.share, c.from, c.items, { share: FS.share, path: dstPath }, conflict); if (c.op === 'cut') CLIP = null; }
    catch (e) { fail(e); }
  };
  if (clash && clash.length) {
    const d = dialog({ title: 'Names already exist', ok: 'Keep both',
      body: `<p>${esc(UTI18N.tr('Already in this folder:'))} <b translate="no">${clash.slice(0, 5).map(esc).join(', ')}${clash.length > 5 ? ' …' : ''}</b></p>
        <p class="ut-faint">Keep both: the new ones get a number, e.g. “name (2)”.</p>
        <div class="row"><button class="ut-btn ut-btn--danger" data-cf="overwrite">Replace</button><button class="ut-btn" data-cf="skip">Skip these</button></div>`,
      onOk: () => go('rename') });
    $$('[data-cf]', d).forEach(x => x.onclick = () => { d.remove(); go(x.dataset.cf); });
  } else go('rename');
}
function fileDelete(items) {
  if (!items.length) return;
  dialog({ kind: 'danger', title: items.length === 1 ? 'Delete?' : UTI18N.tr('Delete %s items?').replace('%s', items.length), ok: 'Delete', okCls: 'ut-btn--danger',
    body: `<p translate="no"><b>${items.slice(0, 6).map(e => esc(e.name)).join(', ')}${items.length > 6 ? ' …' : ''}</b></p>
      <p>${FS.recycle && !/^recycle(\/|$)/.test(FS.path) ? esc(UTI18N.tr('They go to the recycle bin of the share (folder “recycle”).')) : esc(UTI18N.tr('They will be deleted permanently.'))}</p>`,
    onOk: async () => { await api('files/op', { op: 'delete', share: FS.share, paths: items.map(e => fpath(e.name)) }); FS.sel.clear(); render('files'); } });
}
function fileRename(e) {
  dialog({ title: 'Rename', body: field('rn', 'New name', e.name), ok: 'Rename',
    onOk: s => api('files/op', { op: 'rename', share: FS.share, path: fpath(e.name), name: $('#rn', s).value }).then(() => { FS.sel = new Set([$('#rn', s).value]); render('files'); }) });
  setTimeout(() => { const i = $('#rn'); if (i) { const dot = e.dir ? -1 : e.name.lastIndexOf('.'); i.setSelectionRange(0, dot > 0 ? dot : e.name.length); } });
}
async function fileProps(e) {
  const d = dialog({ title: 'Properties', ok: 'Close', body: `<p><b translate="no">${esc(e.name)}</b></p><p class="ut-faint mono" translate="no">${esc(FS.share + '/' + fpath(e.name))}</p>
    <p>${esc(UTI18N.tr('Modified'))}: ${new Date(e.mtime * 1000).toLocaleString(UTI18N.locale)}</p><p id="psz">${e.dir ? '<span class="ut-spinner"></span>' : esc(UTI18N.tr('Size')) + ': ' + size(e.size)}</p>` });
  if (e.dir) {
    try { const r = await api('files/size?' + new URLSearchParams({ share: FS.share, path: fpath(e.name) }));
      const p = $('#psz', d); if (p) p.textContent = `${UTI18N.tr('Size')}: ${size(r.size)} · ${UTI18N.tr('%s files').replace('%s', r.files)} · ${UTI18N.tr('%s folders').replace('%s', r.dirs)}${r.partial ? ' (' + UTI18N.tr('counting stopped after 10 s') + ')' : ''}`; }
    catch (x) { const p = $('#psz', d); if (p) p.textContent = x.message; }
  }
}
function fileMenu(b, x, y, e) {
  const items = fsel(), one = items.length === 1 ? items[0] : null;
  const M = [];
  if (e) {
    M.push({ label: 'Open', key: 'Enter', fn: () => fileOpen(b, e), disabled: !one });
    if (one && !one.dir && OFFICE.exts.includes((one.name.split('.').pop() || '').toLowerCase())) M.push({ label: 'Open in Office', fn: () => officeOpen(FS.share, fpath(one.name)) });
    M.push({ label: one && !one.dir ? 'Download' : 'Download as ZIP', fn: () => fileDownload(items) }, 'sep',
      { label: 'Cut', key: 'Ctrl+X', fn: () => fileCut('cut', items) }, { label: 'Copy', key: 'Ctrl+C', fn: () => fileCut('copy', items) });
    if (one && one.dir && CLIP) M.push({ label: 'Paste into this folder', fn: () => filePaste(fpath(one.name)) });
    M.push({ label: 'Rename', key: 'F2', fn: () => fileRename(one), disabled: !one }, 'sep',
      { label: 'Share link…', fn: () => linkDialog(FS.share, fpath(one.name), one.name), disabled: !one },
      { label: 'Export…', fn: () => exportDialog(FS.share, fpath(one.name), one.name, !!one.dir), disabled: !one });
    if (one && one.dir && ME.admin) M.push({ label: 'As share…', fn: () => shareFromFolder(FS.share, fpath(one.name), one.name) });
    M.push({ label: 'Properties', fn: () => fileProps(one), disabled: !one }, 'sep', { label: 'Delete', key: 'Del', danger: true, fn: () => fileDelete(items) });
  } else {
    M.push({ label: 'New folder', fn: () => $('#mk', b).click() }, { label: 'Upload files', fn: () => $('#up', b).click() }, { label: 'Upload a folder', fn: () => $('#upd', b).click() },
      { label: CLIP ? 'Paste (' + CLIP.items.length + ')' : 'Paste', key: 'Ctrl+V', disabled: !CLIP, fn: () => filePaste() }, 'sep',
      { label: 'Select all', key: 'Ctrl+A', fn: () => { FS.sel = new Set(FS.entries.map(x => x.name)); render('files'); } },
      { label: 'Download this folder as ZIP', fn: () => fileDownload([]) });
  }
  ctxMenu(x, y, M);
}
let OFFICE = { exts: [] };

VIEWS.files = async b => {
  const [sh, office] = await Promise.all([api('shares'), api('office').catch(() => ({ exts: [] }))]);
  OFFICE = office;
  const isDoc = n => (office.exts || []).includes((n.split('.').pop() || '').toLowerCase()) && n.includes('.');
  const all = (sh.shares || []).filter(s => s.enabled !== false);
  // UntrashMesh partner volumes (admins): opened like a share, "mesh:<partner>-<share>"
  const partners = (sh.volumes || []).filter(v => v.kind === 'partner').map(v => ({ name: 'mesh:' + v.id.slice(2), label: v.label }));
  FS.labels = Object.fromEntries(partners.map(p => [p.name, p.label]));
  // shares whose folder is missing (stock volume not present) are listed but not opened
  const list = all.filter(s => s.present !== false).concat(partners), gone = all.filter(s => s.present === false);
  if (!list.some(s => s.name === FS.share)) { FS.share = list.length ? list[0].name : null; FS.path = ''; FS.sel.clear(); }
  const side = sidebar('files', [['#', 'Shares']].concat(list.filter(s => !FS.labels[s.name]).map(s => ['s:' + s.name, s.name]),
    partners.length ? [['#', 'Partner volumes']].concat(partners.map(p => ['s:' + p.name, p.label])) : [],
    gone.length ? [['#', 'Volume missing']].concat(gone.map(s => ['x:' + s.name, s.name])) : []), 's:' + FS.share);
  let main = '<div class="empty">No share available.</div>';
  let r = null;
  if (FS.share) {
    // an error (folder gone meanwhile, no access) stays in the main area: the
    // share list remains usable
    try {
      r = FS.search ? await api('files/search?' + new URLSearchParams({ share: FS.share, path: FS.path, q: FS.search }))
        : await api('files?' + new URLSearchParams({ share: FS.share, path: FS.path }));
    } catch (e) { main = `<div class="ut-callout ut-callout--danger">${esc(FS.share)}: ${esc(e.message)}</div>`; FS.search = null; }
  }
  if (r) {
    FS.recycle = !!r.recycle;
    const res = FS.search ? r.results.map(x => Object.assign({}, x, { name: x.path, label: x.path })) : r.entries;
    const cmp = { name: (a, c) => a.name.localeCompare(c.name, undefined, { numeric: true, sensitivity: 'base' }), size: (a, c) => (a.size || 0) - (c.size || 0), mtime: (a, c) => a.mtime - c.mtime }[FS.sort];
    const flt = FS.filter.toLowerCase();
    FS.entries = res.filter(e => !flt || FS.search || e.name.toLowerCase().includes(flt))
      .sort((a, c) => (c.dir - a.dir) || FS.dir * cmp(a, c));
    for (const n of [...FS.sel]) if (!FS.entries.some(e => e.name === n)) FS.sel.delete(n);
    const parts = FS.path ? FS.path.split('/') : [];
    const crumbs = `<span class="crumbs" translate="no"><button data-p="" data-drop="">${esc((FS.labels || {})[FS.share] || FS.share)}</button>${parts.map((p, i) => ` / <button data-p="${esc(parts.slice(0, i + 1).join('/'))}" data-drop="${esc(parts.slice(0, i + 1).join('/'))}">${esc(p)}</button>`).join('')}</span>`;
    const n = FS.sel.size, arrow = k => FS.sort === k ? (FS.dir > 0 ? ' ▲' : ' ▼') : '';
    const cut = CLIP && CLIP.op === 'cut' && CLIP.share === FS.share && CLIP.from === FS.path ? new Set(CLIP.items) : new Set();
    main = `<div class="row ut-files__bar">${crumbs}<span class="ut-spacer"></span>
        <input class="ut-input ut-files__search" id="fq" type="search" placeholder="${esc(UTI18N.tr('Filter, Enter = search subfolders'))}" value="${esc(FS.search || FS.filter)}" aria-label="Search"></div>
      <div class="row ut-files__bar">
        <button class="ut-btn ut-btn--sm" id="mk">New folder</button>
        <label class="ut-btn ut-btn--sm ut-btn--primary">Upload<input type="file" id="up" multiple hidden></label>
        <label class="ut-btn ut-btn--sm">Upload a folder<input type="file" id="upd" webkitdirectory hidden></label>
        <span class="ut-files__sep"></span>
        <button class="ut-btn ut-btn--sm ut-btn--ghost" data-fa="dl"${n ? '' : ' disabled'}>Download</button>
        <button class="ut-btn ut-btn--sm ut-btn--ghost" data-fa="cut"${n ? '' : ' disabled'}>Cut</button>
        <button class="ut-btn ut-btn--sm ut-btn--ghost" data-fa="copy"${n ? '' : ' disabled'}>Copy</button>
        <button class="ut-btn ut-btn--sm ${CLIP ? '' : 'ut-btn--ghost'}" data-fa="paste"${CLIP ? '' : ' disabled'}>${CLIP ? esc(UTI18N.tr('Paste (%s)').replace('%s', CLIP.items.length)) : 'Paste'}</button>
        <button class="ut-btn ut-btn--sm ut-btn--ghost" data-fa="ren"${n === 1 ? '' : ' disabled'}>Rename</button>
        <button class="ut-btn ut-btn--sm ut-btn--ghost ut-btn--danger" data-fa="del"${n ? '' : ' disabled'}>Delete</button>
        <span class="ut-spacer"></span><button class="ut-btn ut-btn--sm ut-btn--ghost" id="exps">Exports</button><button class="ut-btn ut-btn--sm ut-btn--ghost" id="lnks">Shared links</button></div>
      ${FS.search ? `<div class="ut-callout ut-files__info"><div>${esc(UTI18N.tr('Search results for “%s”').replace('%s', FS.search))} · ${r.results.length}${r.partial ? ' (' + esc(UTI18N.tr('stopped early, narrow the search')) + ')' : ''} <button class="ut-btn ut-btn--sm ut-btn--ghost" id="fqx">Back to the folder</button></div></div>` : ''}
      <div class="ut-table-wrap ut-files" id="flist" tabindex="0"><table class="ut-table"><thead><tr>
        <th class="ut-files__ck"><input type="checkbox" id="fall" aria-label="Select all"${n && n === FS.entries.length ? ' checked' : ''}></th>
        <th><button class="ut-th" data-sort="name">Name${arrow('name')}</button></th><th class="num"><button class="ut-th" data-sort="size">Size${arrow('size')}</button></th>
        <th><button class="ut-th" data-sort="mtime">Modified${arrow('mtime')}</button></th><th></th></tr></thead><tbody>
      ${FS.entries.map((e, i) => `<tr class="fileline${FS.sel.has(e.name) ? ' is-sel' : ''}${cut.has(e.name) ? ' is-cut' : ''}" data-i="${i}" draggable="${FS.search ? 'false' : 'true'}"${e.dir ? ` data-drop="${esc(fpath(e.name))}"` : ''}>
        <td class="ut-files__ck">${FS.search ? '' : `<input type="checkbox" data-ck${FS.sel.has(e.name) ? ' checked' : ''} aria-label="${esc(UTI18N.tr('Select'))}">`}</td>
        <td translate="no"><button class="ut-files__name" data-open>${e.dir ? '📁 ' : ''}${esc(e.name)}</button></td><td class="num">${e.dir ? '' : size(e.size)}</td>
        <td>${new Date(e.mtime * 1000).toLocaleString(UTI18N.locale)}</td>
        <td class="ut-rowbtns">${!e.dir && isDoc(e.name) && !FS.search ? '<button class="ut-btn ut-btn--sm" data-office>Open in Office</button>' : ''}${FS.search ? '' : `<button class="ut-btn ut-btn--ghost ut-btn--sm" data-more aria-label="${esc(UTI18N.tr('More'))}">⋯</button>`}</td></tr>`).join('')}
      </tbody></table>${FS.entries.length ? '' : `<div class="empty">${FS.search ? esc(UTI18N.tr('Nothing found.')) : esc(UTI18N.tr('Empty. Drop files here to upload them.'))}</div>`}</div>
      <div class="ut-files__foot ut-faint">${n ? esc(UTI18N.tr('%s selected').replace('%s', n)) + ' · ' : ''}${esc(nItems(FS.entries.length))}</div>
      <div id="fxfer" class="ut-files__xfer" hidden></div>`;
  }
  b.innerHTML = side + `<div class="ut-window__main">${main}</div>`;
  xferPanel();
  $$('[data-nav]', b).forEach(nv => nv.onclick = () => {
    if (nv.dataset.nav.startsWith('x:')) { toast(nv.dataset.nav.slice(2), 'This share\'s folder is on a volume that is not present.', 'warn'); return; }
    FS.share = nv.dataset.nav.slice(2); FS.path = ''; FS.sel.clear(); FS.search = null; FS.filter = ''; render('files');
  });
  if (!r) return;
  const list_ = $('#flist', b);
  $$('.crumbs button', b).forEach(c => c.onclick = () => { FS.path = c.dataset.p; FS.sel.clear(); FS.search = null; render('files'); });
  const entry = tr => FS.entries[+tr.dataset.i];
  const select = (tr, ev) => {
    const e = entry(tr), names = FS.entries.map(x => x.name);
    if (ev.shiftKey && FS.last && names.includes(FS.last)) {
      const [a, c] = [names.indexOf(FS.last), names.indexOf(e.name)].sort((x, y) => x - y);
      if (!(ev.ctrlKey || ev.metaKey)) FS.sel.clear();
      names.slice(a, c + 1).forEach(x => FS.sel.add(x));
    } else if (ev.ctrlKey || ev.metaKey) { FS.sel.has(e.name) ? FS.sel.delete(e.name) : FS.sel.add(e.name); FS.last = e.name; }
    else { FS.sel = new Set([e.name]); FS.last = e.name; }
    render('files');
  };
  $$('.fileline', b).forEach(tr => {
    tr.onclick = ev => {
      const e = entry(tr);
      if (FS.search) {             // a search hit: go to its folder, the file selected
        const pp = e.path.split('/'), nm = pp.pop();
        FS.search = null; FS.filter = ''; FS.path = e.dir ? e.path : pp.join('/'); FS.sel = new Set(e.dir ? [] : [nm]); FS.last = nm;
        return render('files');
      }
      if (ev.target.closest('[data-office]')) return officeOpen(FS.share, fpath(e.name));
      if (ev.target.closest('[data-more]')) { if (!FS.sel.has(e.name)) { FS.sel = new Set([e.name]); FS.last = e.name; } const rc = ev.target.getBoundingClientRect(); return fileMenu(b, rc.left, rc.bottom + 4, e); }
      if (ev.target.closest('[data-ck]')) { FS.sel.has(e.name) ? FS.sel.delete(e.name) : FS.sel.add(e.name); FS.last = e.name; return render('files'); }
      if (ev.target.closest('[data-open]') && !ev.ctrlKey && !ev.metaKey && !ev.shiftKey) return fileOpen(b, e);
      select(tr, ev);
    };
    tr.ondblclick = ev => { if (!FS.search && !ev.target.closest('button') && !ev.target.closest('input')) fileOpen(b, entry(tr)); };
    tr.oncontextmenu = ev => { ev.preventDefault(); if (FS.search) return; const e = entry(tr); if (!FS.sel.has(e.name)) { FS.sel = new Set([e.name]); FS.last = e.name; render('files'); } fileMenu(body('files'), ev.clientX, ev.clientY, e); };
    tr.ondragstart = ev => {
      const e = entry(tr);
      if (!FS.sel.has(e.name)) { FS.sel = new Set([e.name]); FS.last = e.name; tr.classList.add('is-sel'); }
      ev.dataTransfer.setData('application/x-untrash-files', JSON.stringify({ share: FS.share, from: FS.path, items: [...FS.sel] }));
      ev.dataTransfer.effectAllowed = 'copyMove';
    };
  });
  list_.oncontextmenu = ev => { if (!ev.target.closest('.fileline')) { ev.preventDefault(); fileMenu(b, ev.clientX, ev.clientY, null); } };
  // drop: files from the computer upload, entries of this window move (Ctrl: copy)
  const dropTarget = ev => ev.target.closest('[data-drop]');
  b.ondragover = ev => {
    if (!ev.target.closest('#flist, .crumbs')) return;
    ev.preventDefault();
    const internal = [...ev.dataTransfer.types].includes('application/x-untrash-files');
    ev.dataTransfer.dropEffect = internal ? (ev.ctrlKey || ev.altKey ? 'copy' : 'move') : 'copy';
    $$('.is-drop', b).forEach(x => x.classList.remove('is-drop'));
    (dropTarget(ev) || list_).classList.add('is-drop');
  };
  b.ondragleave = ev => { if (!b.contains(ev.relatedTarget)) $$('.is-drop', b).forEach(x => x.classList.remove('is-drop')); };
  b.ondrop = async ev => {
    if (!ev.target.closest('#flist, .crumbs')) return;
    ev.preventDefault();
    $$('.is-drop', b).forEach(x => x.classList.remove('is-drop'));
    const t = dropTarget(ev), dst = t ? t.dataset.drop : FS.path;
    const raw = ev.dataTransfer.getData('application/x-untrash-files');
    if (raw) {
      const d = JSON.parse(raw);
      if (d.share === FS.share && d.from === dst) return;
      if (d.items.some(nm => dst === (d.from ? d.from + '/' : '') + nm)) return;      // onto itself
      try { await startTransfer(ev.ctrlKey || ev.altKey ? 'copy' : 'move', d.share, d.from, d.items, { share: FS.share, path: dst }); } catch (x) { fail(x); }
      return;
    }
    const files = await droppedFiles(ev.dataTransfer);
    if (files.length) uploadAll(FS.share, dst, files);
  };
  // keyboard
  list_.onkeydown = ev => {
    const k = ev.key.toLowerCase(), ctl = ev.ctrlKey || ev.metaKey, items = fsel();
    if (ctl && k === 'a') { ev.preventDefault(); FS.sel = new Set(FS.entries.map(x => x.name)); render('files'); }
    else if (ctl && k === 'c') { ev.preventDefault(); fileCut('copy', items); }
    else if (ctl && k === 'x') { ev.preventDefault(); fileCut('cut', items); }
    else if (ctl && k === 'v') { ev.preventDefault(); filePaste(); }
    else if (k === 'delete') { ev.preventDefault(); fileDelete(items); }
    else if (k === 'f2' && items.length === 1) { ev.preventDefault(); fileRename(items[0]); }
    else if (k === 'enter' && items.length === 1) { ev.preventDefault(); fileOpen(b, items[0]); }
    else if (k === 'backspace' && FS.path && !FS.search) { ev.preventDefault(); FS.path = FS.path.split('/').slice(0, -1).join('/'); FS.sel.clear(); render('files'); }
    else if (k === 'escape') { FS.sel.clear(); render('files'); }
    else if (k === 'arrowdown' || k === 'arrowup') {
      ev.preventDefault();
      const names = FS.entries.map(x => x.name), i = names.indexOf(FS.last), j = Math.max(0, Math.min(names.length - 1, i + (k === 'arrowdown' ? 1 : -1)));
      if (names[j]) { if (ev.shiftKey) FS.sel.add(names[j]); else FS.sel = new Set([names[j]]); FS.last = names[j]; render('files'); }
    }
  };
  if (!document.activeElement || document.activeElement === document.body || b.contains(document.activeElement) && !document.activeElement.matches('input, textarea, select'))
    list_.focus({ preventScroll: true });
  const fall = $('#fall', b); if (fall) fall.onchange = () => { FS.sel = fall.checked ? new Set(FS.entries.map(x => x.name)) : new Set(); render('files'); };
  $$('[data-sort]', b).forEach(x => x.onclick = () => { FS.dir = FS.sort === x.dataset.sort ? -FS.dir : 1; FS.sort = x.dataset.sort; render('files'); });
  $$('[data-fa]', b).forEach(x => x.onclick = () => {
    const items = fsel();
    ({ dl: () => fileDownload(items), cut: () => fileCut('cut', items), copy: () => fileCut('copy', items), paste: () => filePaste(),
       ren: () => fileRename(items[0]), del: () => fileDelete(items) })[x.dataset.fa]();
  });
  const fq = $('#fq', b);
  fq.oninput = () => {
    if (FS.search) return;
    FS.filter = fq.value;
    const flt = fq.value.toLowerCase();
    $$('.fileline', b).forEach(tr => { tr.hidden = !!flt && !entry(tr).name.toLowerCase().includes(flt); });
  };
  fq.onkeydown = ev => {
    if (ev.key === 'Enter' && fq.value.trim().length >= 2) { FS.search = fq.value.trim(); FS.filter = ''; FS.sel.clear(); render('files'); }
    if (ev.key === 'Escape') { fq.value = ''; FS.filter = ''; FS.search = null; render('files'); }
  };
  const fqx = $('#fqx', b); if (fqx) fqx.onclick = () => { FS.search = null; render('files'); };
  const lk = $('#lnks', b); if (lk) lk.onclick = () => linksDialog();
  const ex = $('#exps', b); if (ex) ex.onclick = () => exportsDialog();
  $('#mk', b).onclick = () => dialog({ title: 'New folder', body: field('nd', 'Name'), ok: 'Create',
    onOk: s => api('files/op', { op: 'mkdir', share: FS.share, path: FS.path, name: $('#nd', s).value }).then(() => { FS.sel = new Set([$('#nd', s).value]); render('files'); }) });
  $('#up', b).onchange = e => uploadAll(FS.share, FS.path, [...e.target.files].map(f => ({ file: f, dirs: '' })));
  $('#upd', b).onchange = e => uploadAll(FS.share, FS.path, [...e.target.files].map(f => ({ file: f, dirs: (f.webkitRelativePath || '').split('/').slice(0, -1).join('/') })));
};

/* photo / music / video viewer (stock Photo, Music and Video apps) */
const mediaKind = n => /\.(jpe?g|png|gif|webp|bmp)$/i.test(n) ? 'img' : /\.(mp3|m4a|aac|ogg|oga|opus|flac|wav|wma|ac3|dts|mka)$/i.test(n) ? 'audio'
  : /\.(mp4|m4v|webm|ogv|mov|mkv|avi|ts|mts|m2ts|wmv|flv|mpe?g|vob|3gp)$/i.test(n) ? 'video' : /\.pdf$/i.test(n) ? 'pdf'
  : /\.(txt|md|markdown|log|csv|tsv|json|xml|ya?ml|ini|conf|cfg|nfo|srt|vtt|sh|py|js|css|html?)$/i.test(n) ? 'text' : '';
function viewer(names, cur, rel) {
  let i = Math.max(0, names.indexOf(cur));
  const s = document.createElement('div'); s.className = 'ut-scrim';
  const show = () => {
    const n = names[i], k = mediaKind(n), src = '/api/files/download?' + new URLSearchParams({ share: FS.share, path: rel(n), inline: '1' });
    const dl = '/api/files/download?' + new URLSearchParams({ share: FS.share, path: rel(n) });
    s.innerHTML = `<div class="ut-dialog" style="max-width:min(96vw,1100px);width:auto"><div class="ut-dialog__head"><h2 translate="no">${esc(n)}</h2></div>
      <div class="ut-dialog__body" style="text-align:center">${k === 'img' ? `<img src="${src}" alt="" style="max-width:90vw;max-height:72vh">`
        : k === 'audio' ? `<audio src="${src}" controls autoplay style="width:min(80vw,520px)"></audio>`
        : k === 'video' ? `<video src="${src}" controls autoplay style="max-width:90vw;max-height:72vh"></video>`
        : `<iframe src="${src}" sandbox="" style="width:80vw;height:72vh;border:0"></iframe>`}</div>
      <div class="ut-dialog__foot"><span class="ut-faint">${i + 1} / ${names.length}</span><button class="ut-btn" data-v="-1">‹ Back</button><button class="ut-btn" data-v="1">Next ›</button>
        <a class="ut-btn" href="${dl}">Download</a><button class="ut-btn ut-btn--primary" data-x>Close</button></div></div>`;
    $$('[data-v]', s).forEach(x => x.onclick = () => { i = (i + +x.dataset.v + names.length) % names.length; show(); });
  };
  s.onclick = e => { if (e.target === s || e.target.closest('[data-x]')) { s.remove(); document.removeEventListener('keydown', key); } };
  const key = e => { if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { i = (i + (e.key === 'ArrowRight' ? 1 : -1) + names.length) % names.length; show(); } else if (e.key === 'Escape') s.click(); };
  document.addEventListener('keydown', key);
  document.body.append(s); show();
}

/* shares ---------------------------------------------------------------- */
let SHARE_PREFILL = null, SHARE_PICK = null;   // set by Files → "Set up as share"
const MEDIA = [[1, 'Video'], [2, 'Photos'], [4, 'Music']];
VIEWS.shares = async (b, sel) => {
  const [sh, us] = await Promise.all([api('shares'), api('users')]);
  const s = sh.shares.find(x => x.name === sel);
  const side = sidebar('shares', [['#', 'Shares']].concat(sh.shares.map(x => [x.name, x.name + (x.enabled ? '' : ' (off)'), true])).concat([['#', ''], ['_new', '+ New share']]), sel || '');
  let main;
  if (sel === '_new' || !s) {
    const pre = SHARE_PREFILL || {}; SHARE_PREFILL = null;
    main = sel === '_new' ? `<h2>New share</h2><div class="form">
      <div class="ut-field"><label for="sv">Volume</label><select class="ut-select" id="sv">${sh.volumes.filter(v => v.kind === 'intern' || v.kind === 'partner').map(v => `<option value="${esc(v.id)}"${v.id === pre.volume ? ' selected' : ''} translate="no">${esc(v.label)} – ${gb(v.free)} ${esc(UTI18N.tr('free'))}${v.kind === 'partner' ? ' · ' + esc(UTI18N.tr(v.mode === 'ro' ? 'partner volume, read only' : 'partner volume')) : ''}</option>`).join('')}</select></div>
      <div class="row" style="gap:16px"><label><input type="radio" name="sk" value="new"${pre.folder ? '' : ' checked'}> New folder</label>
        <label><input type="radio" name="sk" value="dir"${pre.folder ? ' checked' : ''}> Choose an existing folder</label></div>
      <div class="ut-picker" id="spick" hidden><div class="crumbs" id="spc" translate="no"></div><div class="ut-picker__list" id="spl"></div>
        <div class="row"><span class="muted">Chosen:</span> <b id="spsel" translate="no">–</b></div></div>
      ${field('sn', 'Share name', pre.name || '')}
      <button class="ut-btn ut-btn--primary" id="mkshare">Create</button><p class="ut-faint">Then set the rights. When new, only admin may read and write.</p></div>`
      : `<div class="empty">Choose a share on the left.<br>${sh.shares.length} Shares, ${sh.shares.filter(x => x.enabled).length} active.</div>`;
  } else {
    const acl = (kind, list, cur) => list.map(n => `<tr><td>${esc(n)}</td><td><select class="ut-select" data-${kind}="${esc(n)}">
      ${[['', '—'], ['rw', 'Read and write'], ['ro', 'Read only'], ['deny', 'No access']].map(([v, l]) => `<option value="${v}"${(cur[n] || '') === v ? ' selected' : ''}>${l}</option>`).join('')}</select></td></tr>`).join('');
    main = `<div class="row"><h2 style="margin:0">${esc(s.name)}</h2><span class="ut-faint mono">${esc(s.path)}</span>${s.present ? '' : '<span class="ut-pill ut-pill--warn">Folder missing</span>'}</div>
      <div class="form">${field('sd', 'Description', s.description)}
      <div class="row">${sw('se', s.enabled, 'Active')} ${sw('sb', s.browseable, 'Visible')} ${sw('sr', s.recycle, 'Recycle bin')}</div>
      <div class="ut-section-title">Media server (DLNA)</div><div class="row">${MEDIA.map(([m, l]) => `<label><input type="checkbox" data-media="${m}"${s.media & m ? ' checked' : ''}> ${l}</label>`).join(' ')}</div>
      <div class="ut-section-title">Web Publishing</div>${sw('swp', s.web_public, 'Public on the web under /MyWeb/' + s.name + ' (read only, without login)')}</div>
      <div class="ut-section-title">Rights (as on stock: users and groups, pc-guest = guests)</div>
      <div class="ut-table-wrap acl"><table class="ut-table"><thead><tr><th>Users</th><th>Right</th></tr></thead><tbody>${acl('u', us.users.map(u => u.name), s.users)}</tbody></table></div>
      <div class="ut-table-wrap acl" style="margin-top:8px"><table class="ut-table"><thead><tr><th>Group</th><th>Right</th></tr></thead><tbody>${acl('g', us.groups.map(g => g.name), s.groups)}</tbody></table></div>
      <div class="row" style="margin-top:12px"><button class="ut-btn ut-btn--primary" id="ssave">Save</button><span class="ut-spacer"></span>
      ${s.type === 'built-in' ? '' : '<button class="ut-btn ut-btn--danger" id="sdel">Remove share</button>'}</div>`;
  }
  b.innerHTML = side + `<div class="ut-window__main">${main}</div>`;
  navBind(b, 'shares');
  // folder picker: browse the volume, pick an existing folder as the share
  let pickPath = (SHARE_PICK || ''), picked = null; SHARE_PICK = null;
  const pick = async () => {
    const vol = $('#sv', b).value, d = await api('volumes/dirs?' + new URLSearchParams({ volume: vol, path: pickPath }));
    const parts = d.path ? d.path.split('/') : [];
    $('#spc', b).innerHTML = `<button data-pp="">${esc(vol)}</button>` + parts.map((x, i) => ` / <button data-pp="${esc(parts.slice(0, i + 1).join('/'))}">${esc(x)}</button>`).join('');
    $('#spl', b).innerHTML = (d.dirs.length ? d.dirs.map(x => `<button class="ut-picker__item" data-pd="${esc(x.name)}"${x.shared ? ' disabled' : ''}>📁 <span translate="no">${esc(x.name)}</span>${x.shared ? ` <small class="muted">(Share <span translate="no">${esc(x.shared)}</span>)</small>` : ''}</button>`).join('') : '<div class="muted">No subfolders.</div>')
      + (d.path ? `<button class="ut-btn ut-btn--sm ut-btn--primary" id="spthis">Choose this folder</button>` : '');
    $$('[data-pp]', b).forEach(x => x.onclick = () => { pickPath = x.dataset.pp; pick(); });
    $$('[data-pd]', b).forEach(x => x.onclick = () => { pickPath = (d.path ? d.path + '/' : '') + x.dataset.pd; pick(); });
    const t = $('#spthis', b); if (t) t.onclick = () => { picked = d.path; $('#spsel', b).textContent = vol + '/' + d.path; if (!$('#sn', b).value) $('#sn', b).value = d.path.split('/').pop().replace(/[^A-Za-z0-9_.-]/g, '-').slice(0, 32); };
  };
  const kind = () => (b.querySelector('[name=sk]:checked') || {}).value;
  $$('[name=sk]', b).forEach(r => r.onchange = () => { $('#spick', b).hidden = kind() !== 'dir'; if (kind() === 'dir') pick().catch(fail); });
  if ($('#sv', b)) $('#sv', b).onchange = () => { pickPath = ''; picked = null; $('#spsel', b).textContent = '–'; if (kind() === 'dir') pick().catch(fail); };
  if (kind() === 'dir') { $('#spick', b).hidden = false; if (pickPath) { picked = pickPath; $('#spsel', b).textContent = $('#sv', b).value + '/' + pickPath; } pick().catch(fail); }
  const mk = $('#mkshare', b);
  if (mk) mk.onclick = async () => {
    const name = $('#sn', b).value.trim();
    if (kind() === 'dir' && !picked) return toast('Choose folder', 'Open a folder in the folder browser and click “Choose this folder”.', 'warn');
    try { await api('shares/save', { new: true, name, volume: $('#sv', b).value, folder: kind() === 'dir' ? picked : '' }); toast('Share created', name); render('shares', name); } catch (e) { fail(e); }
  };
  const sv = $('#ssave', b);
  if (sv) sv.onclick = () => {
    const users = {}, groups = {};
    $$('[data-u]', b).forEach(x => x.value && (users[x.dataset.u] = x.value));
    $$('[data-g]', b).forEach(x => x.value && (groups[x.dataset.g] = x.value));
    save('shares/save', { name: s.name, description: $('#sd', b).value, enabled: $('#se', b).checked, browseable: $('#sb', b).checked,
      recycle: $('#sr', b).checked, media: $$('[data-media]', b).reduce((a, x) => a | (x.checked ? +x.dataset.media : 0), 0), users, groups,
      web_public: $('#swp', b) ? $('#swp', b).checked : s.web_public }, 'shares', s.name);
  };
  const del = $('#sdel', b);
  if (del) del.onclick = () => dialog({ kind: 'danger', title: 'Remove share?', body: `<p>The share <b>${esc(s.name)}</b> disappears from the network. The folder and all files in it are kept (as on stock).</p>`,
    ok: 'Remove', okCls: 'ut-btn--danger', onOk: () => api('shares/delete', { name: s.name }).then(() => render('shares')) });
};

/* storage ---------------------------------------------------------------- */
const LEVELS = { basic: 'Basic (1 disk)', jbod: 'JBOD', raid0: 'RAID 0', raid1: 'RAID 1', raid5: 'RAID 5', raid6: 'RAID 6', raid10: 'RAID 10' };
const RSTATE = { Normal: ['ut-pill--ok', 'healthy'], Degraded: ['ut-pill--danger', 'degraded'], Resyncing: ['ut-pill--warn', 'resyncing'], Crashed: ['ut-pill--danger', 'failed'] };
const ROLE = { free: 'free', foreign: 'free (old data)', member: 'in the RAID', system: 'UntrashOS', busy: 'used' };
let RAIDPOLL = null;
const diskPick = (s, list) => list.length ? list.map(n => { const d = s.disks.find(x => x.bay === n) || {};
  return `<label class="row"><input type="checkbox" data-disk="${esc(n)}"> ${esc(n)} · ${gb(d.size || 0)} ${esc(d.model || '')}${d.role === 'foreign' ? ' <span class="ut-pill ut-pill--warn">' + esc(d.detail) + '</span>' : ''}</label>`; }).join('')
  : '<p class="ut-faint">No free disk.</p>';
const picked = s => $$('[data-disk]', s).filter(x => x.checked).map(x => x.dataset.disk);
const confirmField = word => `<div class="ut-callout ut-callout--danger" style="margin:10px 0"><div>All data on the selected disks or the volume will be lost.</div></div>
  ${field('rconf', 'Type ' + word + ' to confirm', '', 'autocomplete=off')}`;
async function raidRun(op, req, s) {
  await api('raid/job', Object.assign({ op, confirm: s && $('#rconf', s) ? $('#rconf', s).value.trim() : '' }, req));
  toast('Job started', op); render('storage');
}
function raidAction(st, a, act) {
  const free = st.free || [];
  const vols = a.volumes.map(v => `<option value="${esc(v.id)}">${esc(v.name)}</option>`).join('');
  const D = {
    repair: ['Repair', `<p>New disk(s) for ${esc(a.name)} (${esc(a.level)}):</p>${diskPick(st, free)}${confirmField('FORMAT')}`, s => raidRun('repair', { md: a.md, disks: picked(s) }, s)],
    'add-disks': ['Add disks', `<p>${esc(a.name)} extend with disks (${esc(a.level)} stays):</p>${diskPick(st, free)}${confirmField('FORMAT')}`, s => raidRun('add-disks', { md: a.md, disks: picked(s) }, s)],
    'change-level': ['Change RAID type', `<p>${esc(LEVELS[a.level] || a.level)} → <b>${esc(LEVELS[a.next_level] || a.next_level)}</b>, add disk(s) for it:</p>${diskPick(st, free)}${confirmField('FORMAT')}`, s => raidRun('change-level', { md: a.md, level: a.next_level, disks: picked(s) }, s)],
    'add-spare': ['Spare disk', `<p>Spare disk for ${esc(a.name)}:</p>${diskPick(st, free)}${confirmField('FORMAT')}`, s => raidRun('add-spare', { md: a.md, disks: picked(s) }, s)],
    'remove-spare': ['Remove spare disk', diskPick(st, a.members.filter(m => m.state === 'spare').map(m => m.bay)), s => raidRun('remove-spare', { md: a.md, disks: picked(s) })],
    expand: ['Expand to disk size', `<p>After swapping for larger disks: array and file system of ${esc(a.name)} enlarge to the free space.</p>`, () => raidRun('expand', { md: a.md })],
    delete: ['Delete', `<p><b>${esc(a.name)}</b> (${esc(a.level)}${a.type === 'lvm' ? ', Disk group with all volumes' : ''}) delete. Shares on it are removed.</p>${confirmField('DELETE')}`, s => raidRun('delete', { md: a.md }, s)],
    'lv-create': ['Create volume', `${field('lvn', 'Name')}${field('lvs', 'Size in GB (empty = all free space)', '', 'inputmode=numeric')}<p class="ut-faint">Free in the disk group: ${gb(a.vg_free)}</p>`,
      s => raidRun('lv-create', { md: a.md, volume: $('#lvn', s).value.trim(), size: $('#lvs', s).value.trim() ? $('#lvs', s).value.trim() + 'G' : 'max' })],
    'lv-extend': ['Enlarge volume', `<div class="ut-field"><label>Volume</label><select class="ut-select" id="lvi">${vols}</select></div>${field('lvs', 'New size in GB (empty = all free space)', '', 'inputmode=numeric')}`,
      s => raidRun('lv-extend', { md: a.md, lv: $('#lvi', s).value, size: $('#lvs', s).value.trim() ? $('#lvs', s).value.trim() + 'G' : 'max' })],
    'lv-delete': ['Delete volume', `<div class="ut-field"><label>Volume</label><select class="ut-select" id="lvi">${vols}</select></div>${confirmField('DELETE')}`, s => raidRun('lv-delete', { md: a.md, lv: $('#lvi', s).value }, s)],
  }[act];
  dialog({ kind: /delete/.test(act) || RAID_CONFIRM_JS.includes(act) ? 'danger' : '', title: D[0] + ' · ' + a.name, body: D[1], ok: D[0], okCls: /delete/.test(act) ? 'ut-btn--danger' : 'ut-btn--primary', onOk: D[2] });
}
const RAID_CONFIRM_JS = ['repair', 'add-disks', 'change-level', 'add-spare'];
function raidCreate(st) {
  dialog({ kind: 'danger', title: 'New volume', ok: 'Create', body: `${field('rn', 'Name', 'Volume' + (st.arrays.length + 1))}
    <div class="ut-field"><label>Type</label><select class="ut-select" id="rt"><option value="md">Volume directly on the RAID (stock “Quick”)</option><option value="lvm">Disk group with volumes (stock “Expert”, LVM)</option></select></div>
    <div class="ut-field"><label>RAID type</label><select class="ut-select" id="rl">${Object.entries(LEVELS).map(([k, v]) => `<option value="${k}">${esc(UTI18N.tr(v))} · ${esc(UTI18N.tr('ab ' + (st.levels ? st.levels[k] : '') + ' disk(s)'))}</option>`).join('')}</select></div>
    <div class="ut-field"><label>Disks</label>${diskPick(st, st.free || [])}</div>
    <div id="rlvm" hidden>${field('rv', 'First volume: name', 'Volume1')}${field('rs', 'Size in GB (empty = everything)', '', 'inputmode=numeric')}</div>
    <p class="ut-faint">Same format as the Zyxel firmware (GPT, md0/md1, metadata 1.2, ext4): after “Back to stock” the stock firmware reads the volume.</p>${confirmField('FORMAT')}`,
    onOk: s => raidRun('create', { name: $('#rn', s).value.trim(), type: $('#rt', s).value, level: $('#rl', s).value, disks: picked(s),
      volume: $('#rv', s).value.trim(), size: $('#rs', s).value.trim() ? $('#rs', s).value.trim() + 'G' : 'max' }, s) });
  const s = $$('.ut-scrim').pop(); $('#rt', s).onchange = () => { $('#rlvm', s).hidden = $('#rt', s).value !== 'lvm'; };
}
const ACTLABEL = { repair: 'Repair', 'add-disks': 'Add disks', 'change-level': 'Change RAID type', 'add-spare': 'Spare disk', 'remove-spare': 'Remove spare',
  expand: 'Extend', 'lv-create': 'Create volume', 'lv-extend': 'Enlarge volume', 'lv-delete': 'Delete volume', delete: 'Delete' };
VIEWS.storage = async b => {
  const [s, st] = await Promise.all([api('storage'), api('raid')]);
  const role = Object.fromEntries((st.disks || []).map(d => [d.dev.replace('/dev/', ''), d]));
  const job = st.job || {};
  const busy = job.state === 'running' || st.busy;
  b.innerHTML = `<div class="ut-window__main">
    ${job.state && job.state !== 'idle' ? `<div class="ut-card" style="margin-bottom:12px"><div class="row"><b>Job ${esc(job.op)}</b>
      <span class="ut-pill ${job.state === 'running' ? 'ut-pill--warn' : job.state === 'done' ? 'ut-pill--ok' : 'ut-pill--danger'}">${job.state === 'running' ? 'running' : job.state === 'done' ? 'done' : 'failed'}</span></div>
      <pre class="mono joblog" style="max-height:160px;overflow:auto;white-space:pre-wrap">${esc(job.log.slice(-60).join('\n'))}</pre></div>` : ''}
    <div class="row"><div class="ut-section-title" style="flex:1">Volumes and RAID</div>${(st.free || []).length && !busy ? '<button class="ut-btn ut-btn--primary" id="rnew">+ New volume</button>' : ''}</div>
    ${st.arrays.length ? st.arrays.map((a, i) => { const [cls, txt] = RSTATE[a.state] || ['ut-pill--plain', a.state]; return `<div class="ut-card" style="margin-bottom:10px">
      <div class="row"><b>${esc(a.name || a.md)}</b> <span class="ut-faint">${esc(LEVELS[a.level] || a.level)} · ${esc(a.type === 'lvm' ? 'Disk group' : 'Volume')} · ${gb(a.size)} · ${esc(a.md)}</span>
        <span class="ut-pill ${cls}">${txt}</span>${a.host ? ' <span class="ut-pill ut-pill--plain">carries UntrashOS</span>' : ''}</div>
      ${a.progress ? `<div class="ut-progress" style="--v:${parseFloat(a.progress.percent)}%"><i></i></div><span class="ut-faint">${esc(a.progress.action)} ${esc(a.progress.percent)}${a.progress.finish ? ' · remaining ' + esc(a.progress.finish) : ''}</span>` : ''}
      <div class="ut-faint">Disks: ${a.members.map(m => esc(m.bay) + (m.state === 'spare' ? ' (spare)' : m.state === 'faulty' ? ' (faulty)' : '')).join(', ')}</div>
      ${a.volumes.map(v => { const used = v.size ? Math.round(100 * (v.size - v.free) / v.size) : 0; return `<div class="vol"><div><b>${esc(v.name)}</b> <span class="ut-faint mono">${esc(v.mnt.replace(/^.*\/i-data/, '/i-data'))}</span>${v.sysvol ? ' <span class="ut-pill ut-pill--plain">System</span>' : ''}</div>
        ${v.mounted ? `<div class="ut-progress ${used > 90 ? 'ut-progress--danger' : ''}" style="--v:${used}%"><i></i></div><span class="ut-faint">${gb(v.size - v.free)} of ${gb(v.size)} used</span>` : '<span class="ut-pill ut-pill--danger">not mounted</span>'}
        <button class="ut-btn ut-btn--sm" data-ren="${i}:${esc(v.id)}">Rename</button></div>`; }).join('')}
      ${a.type === 'lvm' ? `<div class="ut-faint">Free in the disk group: ${gb(a.vg_free)}</div>` : ''}
      <div class="row" style="margin-top:6px">${busy ? '' : a.actions.map(x => `<button class="ut-btn ut-btn--sm${x === 'delete' || x === 'lv-delete' ? ' ut-btn--danger' : ''}" data-act="${i}:${x}">${esc(ACTLABEL[x] || x)}</button>`).join(' ')}</div></div>`; }).join('')
    : '<div class="ut-card empty">Not an internal volume.</div>'}
    <div class="ut-section-title">Drive</div>
    <div class="ut-table-wrap"><table class="ut-table"><thead><tr><th>Disk</th><th>Bay</th><th class="num">Size</th><th>Model</th><th>SMART</th><th>Temp.</th><th>Role</th></tr></thead><tbody>
    ${s.disks.map(d => { const r = role[d.name]; return `<tr><td>${esc(d.name)}${d.usb ? ' <span class="ut-pill ut-pill--plain">USB</span>' : ''}</td><td>${esc(r ? r.bay : '')}</td><td class="num">${gb(d.size)}</td><td>${esc(d.model)}</td>
      <td><span class="ut-pill ${d.smart === 'ok' ? 'ut-pill--ok' : d.smart === 'fehler' ? 'ut-pill--danger' : 'ut-pill--plain'}">${esc(d.smart)}</span></td><td>${esc(d.temp ? d.temp + ' °C' : '')}</td>
      <td>${r ? esc(ROLE[r.role] || r.role) + ' <span class="ut-faint">' + esc(r.detail) + '</span>' : (d.usb ? 'USB' : '')}</td></tr>`; }).join('')}</tbody></table></div>
    ${s.volumes.filter(v => v.kind === 'partner').length ? `<div class="ut-section-title">Partner volumes (UntrashMesh)</div><div class="ut-card">${s.volumes.filter(v => v.kind === 'partner').map(v => `<div class="vol"><div><b translate="no">${esc(v.label)}</b> <span class="ut-faint mono">${esc(v.path)}</span>${v.mode === 'ro' ? ' <span class="ut-pill ut-pill--plain">' + esc(UTI18N.tr('read only')) + '</span>' : ''}</div><span class="ut-faint">${gb(v.free)} free of ${gb(v.size)}</span></div>`).join('')}</div>` : ''}
    ${s.volumes.filter(v => v.kind === 'usb').length ? `<div class="ut-section-title">USB</div><div class="ut-card">${s.volumes.filter(v => v.kind === 'usb').map(v => `<div class="vol"><div><b>${esc(v.label)}</b> <span class="ut-faint mono">${esc(v.path)}</span></div><span class="ut-faint">${gb(v.free)} free of ${gb(v.size)}</span></div>`).join('')}</div>` : ''}
    <div class="row"><div class="ut-section-title" style="flex:1">iSCSI</div><button class="ut-btn ut-btn--sm" id="ilun">+ LUN</button><button class="ut-btn ut-btn--sm" id="itgt">+ Target</button></div><div id="iscsi" class="ut-card"><span class="ut-faint">…</span></div>
    <p class="ut-faint">Volumes in the Zyxel firmware format: after “Back to stock” they stay readable.</p></div>`;
  iscsiPanel(b);
  const nb = $('#rnew', b); if (nb) nb.onclick = () => raidCreate(st);
  $$('[data-act]', b).forEach(x => x.onclick = () => { const [i, act] = x.dataset.act.split(':'); raidAction(st, st.arrays[+i], act); });
  $$('[data-ren]', b).forEach(x => x.onclick = () => { const [i, id] = x.dataset.ren.split(':'); const a = st.arrays[+i];
    dialog({ title: 'Rename', ok: 'Save', body: field('nn', 'New name', (a.volumes.find(v => v.id === id) || {}).name || ''),
      onOk: s => raidRun('rename', Object.assign({ md: a.md, name: $('#nn', s).value.trim() }, id.startsWith('lv_') ? { lv: id } : {})) }); });
  clearTimeout(RAIDPOLL);
  if (busy || st.arrays.some(a => a.state === 'Resyncing')) RAIDPOLL = setTimeout(() => { if (body('storage')) render('storage'); }, 3000);
};

async function iscsiPanel(b) {
  const c = await api('iscsi');
  const st = Object.fromEntries((c.status.targets || []).map(t => [t.iqn, t])), ls = Object.fromEntries((c.status.luns || []).map(l => [l.name, l]));
  $('#iscsi', b).innerHTML = `${c.luns.length ? c.luns.map(l => `<div class="row"><b>LUN ${esc(l.name)}</b> <span class="ut-faint">${l.size_gb} GB · ${esc(l.volume || '')}${ls[l.name] ? ' · used ' + gb(ls[l.name].allocated || 0) : ''}${l.write_cache ? ' · Write cache' : ''}</span>
      <button class="ut-btn ut-btn--sm ut-btn--danger" style="margin-left:auto" data-ldel="${esc(l.name)}">Delete</button></div>`).join('') : '<div class="ut-faint">No LUN.</div>'}
    ${c.targets.map((t, i) => `<div class="row" style="margin-top:6px"><b>${esc(t.name)}</b> <span class="ut-faint mono">${esc(t.iqn)}</span>
      <span class="ut-pill ${st[t.iqn] && st[t.iqn].running ? 'ut-pill--ok' : 'ut-pill--plain'}">${st[t.iqn] && st[t.iqn].running ? 'active' : 'off'}</span>
      <span class="ut-faint">LUNs: ${esc(t.luns.join(', ') || '–')} · ${t.chap ? 'CHAP' + (t.mutual ? ' gegenseitig' : '') : 'without CHAP'} · ${t.initiators.length ? esc(t.initiators.join(', ')) : 'all initiators'}</span>
      <button class="ut-btn ut-btn--sm" style="margin-left:auto" data-ted="${i}">Edit</button><button class="ut-btn ut-btn--sm ut-btn--danger" data-tdel="${i}">Delete</button></div>`).join('')}`;
  const plainT = t => ({ name: t.name, iqn: t.iqn, luns: t.luns, initiators: t.initiators, active: t.active, chap: t.chap, chap_user: t.chap_user, mutual: t.mutual });
  const tgtDlg = t => { t = t || { name: UTI18N.tr('Target') + (c.targets.length + 1), iqn: '', luns: [], initiators: [], active: true, chap: false, chap_user: '', mutual: false };
    dialog({ title: 'iSCSI target', ok: 'Save', body: `${field('tn', 'Name', t.name)}${field('tq', 'IQN (empty = automatic)', t.iqn)}
      <div class="ut-field"><label>LUNs</label>${c.luns.map(l => `<label class="row"><input type="checkbox" data-tl="${esc(l.name)}"${t.luns.includes(l.name) ? ' checked' : ''}> ${esc(l.name)}</label>`).join('') || '<span class="ut-faint">create a LUN first</span>'}</div>
      ${field('ti', 'Only these initiators (IQN, comma separated; empty = all)', t.initiators.join(', '))}
      ${sw('tc', t.chap, 'CHAP')}<div class="row">${field('tcu', 'CHAP user name', t.chap_user)}${field('tcp', 'CHAP password (12–16 characters; empty = keep)', '', 'type=password autocomplete=new-password')}</div>
      ${sw('tm', t.mutual, 'Mutual CHAP')}<div class="row">${field('tmu', 'User name', '')}${field('tmp', 'Password', '', 'type=password autocomplete=new-password')}</div>${sw('ta', t.active, 'Active')}`,
      onOk: async s => { const nt = { name: $('#tn', s).value.trim(), iqn: $('#tq', s).value.trim(), luns: $$('[data-tl]', s).filter(x => x.checked).map(x => x.dataset.tl),
        initiators: $('#ti', s).value.split(',').map(x => x.trim()).filter(Boolean), chap: $('#tc', s).checked, chap_user: $('#tcu', s).value.trim(), chap_password: $('#tcp', s).value,
        mutual: $('#tm', s).checked, mutual_user: $('#tmu', s).value.trim(), mutual_password: $('#tmp', s).value, active: $('#ta', s).checked };
        await api('iscsi/targets', { targets: c.targets.filter(x => x !== t).map(plainT).concat([nt]) }); render('storage'); } }); };
  $('#ilun', b).onclick = () => dialog({ title: 'New LUN', ok: 'Create', body: `${field('ln', 'Name', 'lun' + (c.luns.length + 1))}
    <div class="ut-field"><label for="lv">Volume</label><select class="ut-select" id="lv">${c.volumes.map(v => `<option value="${esc(v.id)}">${esc(v.label)} (${gb(v.free)} free)</option>`).join('')}</select></div>
    ${field('lg', 'Size in GB', 10, 'type=number min=1')}${sw('lt', true, 'Thin (allocate space only when needed)')}${sw('lw', false, 'Write cache (faster, risk on power failure)')}`,
    onOk: async s => { await api('iscsi/lun', { name: $('#ln', s).value.trim(), volume: $('#lv', s).value, size_gb: +$('#lg', s).value, thin: $('#lt', s).checked, write_cache: $('#lw', s).checked }); render('storage'); } });
  $('#itgt', b).onclick = () => tgtDlg();
  $$('[data-ted]', b).forEach(x => x.onclick = () => tgtDlg(c.targets[+x.dataset.ted]));
  $$('[data-tdel]', b).forEach(x => x.onclick = async () => { try { await api('iscsi/targets', { targets: c.targets.filter((_, i) => i !== +x.dataset.tdel).map(plainT) }); render('storage'); } catch (e) { fail(e); } });
  $$('[data-ldel]', b).forEach(x => x.onclick = () => dialog({ kind: 'danger', title: 'Delete LUN', ok: 'Delete', okCls: 'ut-btn--danger', body: `<p>LUN ${esc(x.dataset.ldel)} delete with all data.</p>${field('lc', 'Type DELETE to confirm')}`,
    onOk: async s => { await api('iscsi/lun-delete', { name: x.dataset.ldel, confirm: $('#lc', s).value.trim() }); render('storage'); } }));
}

/* users ---------------------------------------------------------------- */
VIEWS.users = async (b, sel) => {
  const us = await api('users');
  const side = sidebar('users', [['#', 'Users']].concat(us.users.filter(u => u.name !== 'pc-guest').map(u => ['u:' + u.name, u.name])).concat([['_nu', '+ New user'], ['#', 'Groups']])
    .concat(us.groups.map(g => ['g:' + g.name, g.name])).concat([['_ng', '+ New group']]), sel || '');
  let main = `<div class="empty">${us.users.length - 1} Users, ${us.groups.length} Groups.<br>Choose on the left.</div>`;
  const u = sel && sel.startsWith('u:') && us.users.find(x => x.name === sel.slice(2));
  const g = sel && sel.startsWith('g:') && us.groups.find(x => x.name === sel.slice(2));
  if (sel === '_nu') main = `<h2>New user</h2><div class="form">${field('un', 'Name')}${field('ud', 'Description')}${field('up1', 'Password (at least 8 characters)', '', 'type=password autocomplete=new-password')}
    ${field('up2', 'Repeat password', '', 'type=password autocomplete=new-password')}<div class="ut-field"><label>Groups</label><div class="row">${us.groups.filter(x => x.name !== 'everyone').map(x => `<label><input type="checkbox" data-grp="${esc(x.name)}"> ${esc(x.name)}</label>`).join(' ') || '<span class="ut-faint">none</span>'}</div></div>
    <button class="ut-btn ut-btn--primary" id="mkuser">Create</button></div>`;
  if (sel === '_ng') main = `<h2>New group</h2><div class="form">${field('gn', 'Name')}${field('gd', 'Description')}<button class="ut-btn ut-btn--primary" id="mkgrp">Create</button></div>`;
  if (u) main = `<h2>${esc(u.name)}</h2><p class="ut-faint">UID ${u.uid}${u.admin ? ' · Administrator' : ''}${u.description ? ' · ' + esc(u.description) : ''}</p>
    <p>Groups: ${u.groups.map(esc).join(', ') || '–'}</p>
    <p>${esc(UTI18N.tr('Sign-in'))}: ${esc(UTI18N.tr({ password: 'password only', app: 'password or app', both: 'password and app' }[u.signin] || 'password only'))}${(u.apps || []).length ? ` · ${esc(UTI18N.tr('app'))} <span translate="no">${u.apps.map(a => esc(a.name)).join(', ')}</span>` : ''}
      ${u.signin !== 'password' ? ' <button class="ut-btn ut-btn--sm ut-btn--ghost" id="sireset">Reset to password</button>' : ''}</p><div class="form">${field('np1', 'New password', '', 'type=password autocomplete=new-password')}${field('np2', 'Repeat', '', 'type=password autocomplete=new-password')}
    <div class="row"><button class="ut-btn ut-btn--primary" id="setpw">Set password</button><span class="ut-spacer"></span>${u.builtin ? '' : '<button class="ut-btn ut-btn--danger" id="deluser">Delete user</button>'}</div></div>`;
  if (g) main = `<h2>${esc(g.name)}</h2><p class="ut-faint">GID ${g.gid}${g.description ? ' · ' + esc(g.description) : ''}</p>
    ${g.builtin ? '<p>All users belong to everyone.</p>' : `<div class="ut-field"><label>Members</label><div class="row">${us.users.filter(x => x.name !== 'pc-guest').map(x => `<label><input type="checkbox" data-mem="${esc(x.name)}"${g.members.includes(x.name) ? ' checked' : ''}> ${esc(x.name)}</label>`).join(' ')}</div></div>
    <div class="row"><button class="ut-btn ut-btn--primary" id="setmem">Save</button><span class="ut-spacer"></span><button class="ut-btn ut-btn--danger" id="delgrp">Delete group</button></div>`}`;
  if (u) {
    const qt = await api('users/quota?name=' + encodeURIComponent(u.name));
    main += `<div class="ut-section-title">Storage quota</div>${qt.quotas.length ? `<div class="form">${qt.quotas.map(x => `<div class="row">
      ${field('q_' + x.volume, x.label + ' – GB (0 = no limit)', x.limit_gb, 'type=number min=0 data-qvol="' + esc(x.volume) + '"')}<span class="ut-faint" style="align-self:end">used ${size(x.used_kb * 1024)}</span></div>`).join('')}
      <button class="ut-btn" id="setq">Save quota</button></div>` : '<p class="ut-faint">Not an internal volume.</p>'}`;
  }
  b.innerHTML = side + `<div class="ut-window__main">${main}</div>`;
  navBind(b, 'users');
  const sq = $('#setq', b); if (sq) sq.onclick = () => save('users/quota', { name: u.name, quotas: Object.fromEntries($$('[data-qvol]', b).map(x => [x.dataset.qvol, +x.value || 0])) }, 'users', 'u:' + u.name);
  const on = (id, fn) => { const x = $('#' + id, b); if (x) x.onclick = fn; };
  on('mkuser', async () => {
    if ($('#up1', b).value !== $('#up2', b).value) return fail(new Error('The passwords do not match.'));
    try { await api('users/create', { name: $('#un', b).value.trim(), description: $('#ud', b).value, password: $('#up1', b).value, groups: $$('[data-grp]', b).filter(x => x.checked).map(x => x.dataset.grp) });
      toast('User created'); render('users', 'u:' + $('#un', b).value.trim()); } catch (e) { fail(e); }
  });
  on('mkgrp', async () => { try { await api('groups/create', { name: $('#gn', b).value.trim(), description: $('#gd', b).value }); render('users', 'g:' + $('#gn', b).value.trim()); } catch (e) { fail(e); } });
  on('setpw', () => {
    if ($('#np1', b).value !== $('#np2', b).value) return fail(new Error('The passwords do not match.'));
    save('password', { name: u.name, password: $('#np1', b).value });
  });
  on('deluser', () => dialog({ kind: 'danger', title: 'Delete user?', body: `<p><b>${esc(u.name)}</b> loses all rights. Files are kept.</p>`, ok: 'Delete', okCls: 'ut-btn--danger',
    onOk: () => api('users/delete', { name: u.name }).then(() => render('users')) }));
  on('sireset', () => dialog({ kind: 'danger', title: 'Reset the sign-in?', ok: 'Reset', okCls: 'ut-btn--danger',
    body: `<p><b translate="no">${esc(u.name)}</b> signs in with the password only again, for example after losing the phone.</p>`,
    onOk: () => api('users/signin', { user: u.name, mode: 'password' }).then(() => render('users', 'u:' + u.name)) }));
  on('setmem', () => save('groups/members', { name: g.name, members: $$('[data-mem]', b).filter(x => x.checked).map(x => x.dataset.mem) }, 'users', 'g:' + g.name));
  on('delgrp', () => dialog({ kind: 'danger', title: 'Delete group?', body: `<p>The group <b>${esc(g.name)}</b> and their share rights are removed.</p>`, ok: 'Delete', okCls: 'ut-btn--danger',
    onOk: () => api('groups/delete', { name: g.name }).then(() => render('users')) }));
};

/* network ---------------------------------------------------------------- */
VIEWS.network = async b => {
  const s = await api('settings'), o = await api('overview');
  const ifc = n => { const c = s.network[n]; return `<div class="ut-section-title">${n === 'eth0' ? 'LAN 1 (eth0)' : 'LAN 2 (eth1)'}</div><div class="form">
    <div class="row"><label><input type="radio" name="m${n}" value="dhcp"${c.mode !== 'static' ? ' checked' : ''}> automatic (DHCP)</label> <label><input type="radio" name="m${n}" value="static"${c.mode === 'static' ? ' checked' : ''}> static</label></div>
    <div class="row">${field(n + 'a', 'Address/prefix', c.address, 'placeholder="192.168.1.20/24"')}${field(n + 'g', 'Gateway', c.gateway)}${field(n + 'm', 'MTU', c.mtu)}</div></div>`; };
  b.innerHTML = `<div class="ut-window__main"><p class="ut-faint mono">${o.addresses.map(a => esc(a.if + ' ' + a.addr)).join(' · ')}</p>
    <div class="form"><div class="row">${field('hn', 'Host name', s.hostname)}</div>
    <div class="row">${field('nbn', 'NetBIOS name (SMB)', s.netbios.name, 'maxlength=15')}${field('nbw', 'Workgroup', s.netbios.workgroup, 'maxlength=15')}</div>${field('nbd', 'Description', s.netbios.description)}</div>
    ${ifc('eth0')}${ifc('eth1')}<div class="ut-section-title">Link aggregation (bond0)</div><div class="form">${sw('bd', s.network.bond.active, 'Bond LAN 1 and LAN 2 (then the address below applies instead of the two above)')}
    <div class="ut-field"><label for="bdm">Mode</label><select class="ut-select" id="bdm">${['Round-Robin', 'Active-Backup', 'XOR', 'Broadcast', '802.3ad (LACP, switch required)', 'Adaptive transmit load balancing', 'Adaptive load balancing'].map((l, i) => `<option value="${i}"${s.network.bond.mode === i ? ' selected' : ''}>${l}</option>`).join('')}</select></div>
    <div class="row"><label><input type="radio" name="mbd" value="dhcp"${s.network.bond.mode_ip !== 'static' ? ' checked' : ''}> automatic (DHCP)</label> <label><input type="radio" name="mbd" value="static"${s.network.bond.mode_ip === 'static' ? ' checked' : ''}> static</label></div>
    <div class="row">${field('bda', 'Address/prefix', s.network.bond.address)}${field('bdg', 'Gateway', s.network.bond.gateway)}</div></div>
    <div class="ut-section-title">DNS</div><div class="form">${sw('dauto', s.network.dns.auto, 'from the DHCP server')}
    <div class="row">${field('dns1', 'DNS 1', s.network.dns.servers[0] || '')}${field('dns2', 'DNS 2', s.network.dns.servers[1] || '')}</div></div>
    <div class="ut-section-title">Router (UPnP port forwarding)</div><div class="form" id="upnp"><p class="ut-faint">Searching for the router …</p></div>
    <div class="ut-callout ut-callout--warn" style="margin:10px 0"><div>A wrong static address makes the NAS unreachable on the network. Way back: connect a network cable directly to a PC, the NAS is then reachable via its automatic address and <b>${esc(s.hostname)}.local</b> reachable.</div></div>
    <button class="ut-btn ut-btn--primary" id="nsave">Save and apply</button></div>`;
  api('upnp').then(u => {
    const names = { HTTP: 'Untrash Desk (HTTP)', HTTPS: 'Untrash Desk (HTTPS)', FTP: 'FTP', SSH: 'SSH', WEBDAV_HTTP: 'WebDAV', WEBDAV_HTTPS: 'WebDAV (HTTPS)', WEBPUBLISHING_HTTP: 'Web Publishing', MEDIASERVER: 'Media server' };
    $('#upnp', b).innerHTML = `<p class="ut-faint">${u.router ? 'Router: ' + esc(u.router) + ' · external address ' + esc(u.external_ip || '?') : 'No UPnP router found.'}</p>
      <div class="ut-callout ut-callout--warn"><div>Forwarded services are reachable from the internet.</div></div>
      <table class="ut-table"><thead><tr><th>Service</th><th>WAN port (empty = off)</th><th>at the router</th></tr></thead><tbody>${u.names.map(n => { const m = (u.mappings || []).find(x => x.ours && x.description.endsWith(' ' + n));
        return `<tr><td>${esc(names[n] || n)}</td><td><input class="ut-input" data-upnp="${n}" value="${u.services[n] || ''}" inputmode="numeric" style="max-width:110px"></td><td>${m ? '<span class="ut-pill ut-pill--ok">' + m.wan_port + '</span>' : '–'}</td></tr>`; }).join('')}</tbody></table>
      <button class="ut-btn" id="upsave">Save forwardings</button>`;
    $('#upsave', b).onclick = () => save('upnp', { services: Object.fromEntries($$('[data-upnp]', b).filter(x => x.value.trim()).map(x => [x.dataset.upnp, +x.value])) }, 'network');
  }).catch(e => { $('#upnp', b).textContent = e.message; });
  $('#nsave', b).onclick = () => {
    const ifv = n => ({ mode: $(`[name=m${n}]:checked`, b).value, address: $('#' + n + 'a', b).value.trim(), gateway: $('#' + n + 'g', b).value.trim(), mtu: +$('#' + n + 'm', b).value || 1500 });
    save('settings', { hostname: $('#hn', b).value.trim(), netbios: { name: $('#nbn', b).value.trim(), workgroup: $('#nbw', b).value.trim(), description: $('#nbd', b).value },
      network: { eth0: ifv('eth0'), eth1: ifv('eth1'), dns: { auto: $('#dauto', b).checked, servers: [$('#dns1', b).value.trim(), $('#dns2', b).value.trim()] },
        bond: { active: $('#bd', b).checked, mode: +$('#bdm', b).value, mode_ip: $('[name=mbd]:checked', b).value, address: $('#bda', b).value.trim(), gateway: $('#bdg', b).value.trim() } } }, 'network');
  };
};

/* settings ---------------------------------------------------------------- */
const PDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
function powerRow(e, i) { return `<tr data-ps="${i}"><td><select class="ut-select" data-k="action">${[['on', 'Switch on'], ['off', 'Switch off'], ['reboot', 'Restart']].map(([k, v]) => `<option value="${k}"${e.action === k ? ' selected' : ''}>${v}</option>`).join('')}</select></td>
      <td><select class="ut-select" data-k="kind">${[['daily', 'daily'], ['weekly', 'weekly'], ['monthly', 'monthly']].map(([k, v]) => `<option value="${k}"${e.kind === k ? ' selected' : ''}>${v}</option>`).join('')}</select></td>
      <td><select class="ut-select" data-k="day">${PDAYS.map((d, j) => `<option value="${j}"${e.day === j ? ' selected' : ''}>${d}</option>`).join('')}</select> <input class="ut-input" data-k="mday" type="number" min="1" max="28" value="${e.mday || 1}" style="max-width:70px"></td>
      <td><input class="ut-input" data-k="time" value="${String(e.hour).padStart(2, '0')}:${String(e.minute).padStart(2, '0')}" style="max-width:80px"></td><td><button class="ut-btn ut-btn--sm ut-btn--ghost" data-psdel="${i}">✕</button></td></tr>`; }

VIEWS.settings = async (b, sel = 'services') => {
  const s = await api('settings');
  const side = sidebar('settings', [['#', 'System'], ['language', 'Language'], ['services', 'Services'], ['time', 'Time'], ['power', 'Power'], ['recycle', 'Recycle bin'],
    ['notify', 'Notification'], ['syslog', 'Syslog'], ['dyndns', 'DynDNS'], ['printers', 'Printers'], ['copybtn', 'COPY button'], ['cert', 'Certificate / HTTPS'], ['office', 'Office'], ['#', 'Firmware'], ['stock', 'Back to stock']], sel);
  let main = '';
  if (sel === 'language') {
    main = `<h2>Language</h2><div class="form"><div class="ut-field"><label for="slang">System language</label>${langSel('slang', s.language || 'en')}</div>
      <p class="ut-faint">Applies to everyone who has not chosen a language in their browser.</p>
      <div class="ut-field"><label for="blang">Language of this browser</label>${langSel('blang', UTI18N.own, true)}</div>
      <div class="row"><button class="ut-btn ut-btn--primary" id="lsave">Save</button></div></div>`;
  }
  if (sel === 'services') {
    const f = s.services.ftp, sh = (await api('shares')).shares;
    main = `<h2>Services</h2><div class="form">
      <div class="ut-section-title">SSH</div><div class="row">${sw('ssh', s.services.ssh.active, 'SSH (admin with password)')} ${sw('sftp', s.services.ssh.sftp, 'SFTP')}</div><div class="row">${field('sshp', 'Port', s.services.ssh.port)}</div>
      <div class="ut-section-title">FTP</div><div class="row">${sw('ftp', f.active, 'FTP')} ${sw('ftps', f.tls, 'TLS (FTPS)')} ${sw('ftpa', f.anonymous, 'Anonymous (pc-guest shares)')}</div>
      <div class="row">${field('ftpp', 'Port', f.port)}${field('ftpc', 'Connections per address', f.conn_limit)}${field('ftpd', 'Download KB/s (0 = unlimited)', f.down_kbs)}</div>
      <div class="ut-section-title">Media server (DLNA)</div>${sw('dlna', s.services.mediaserver.active, 'Media server')}<p class="ut-faint">Which shares: in Shares → Media server.</p>
      <div class="ut-section-title">Time Machine</div><div class="row">${sw('tm', s.services.time_machine.active, 'Time Machine')}
        <select class="ut-select" id="tms">${sh.map(x => `<option${x.name === s.services.time_machine.share ? ' selected' : ''}>${esc(x.name)}</option>`).join('')}</select></div>
      <div class="ut-section-title">NFS</div>${sw('nfs', s.services.nfs.active, 'NFS-Server')}
      <textarea class="ut-textarea mono" id="nfsx" rows="4" placeholder="/i-data/xxxxxxxx/Share 192.168.1.0/24 [ro]">${esc(s.services.nfs.exports.map(e => e.path + ' ' + e.clients + (e.options.startsWith('ro') ? ' ro' : '')).join('\n'))}</textarea>
      <div class="ut-section-title">Web Publishing</div><div class="row">${sw('wp', s.services.webpublish.active, 'Show shares with “Web Publishing” publicly')} ${field('wpp', 'Port', s.services.webpublish.port, 'type=number')}</div>
      <p class="ut-faint">Port 80: http://${esc(location.hostname)}/MyWeb/&lt;share&gt;. Which shares: in Shares.</p>
      <div class="ut-section-title">WebDAV</div><div class="row">${sw('dav', s.services.webdav.active, 'WebDAV')} ${sw('davan', s.services.webdav.anonymous, 'Anonymous (guest shares)')}</div>
      <p class="ut-faint">Address: http://${esc(location.hostname)}:5002/webdav/&lt;share&gt; (https: port 5003). Same rights as the share.</p>
      <div style="margin-top:12px"><button class="ut-btn ut-btn--primary" id="svsave">Save and apply</button></div></div>`;
  } else if (sel === 'time') {
    const tz = (await api('timezones')).zones;
    main = `<h2>Time</h2><div class="form"><p>NAS time: <b>${esc((await api('overview')).time.replace('T', ' '))}</b></p>
      <div class="ut-field"><label for="tz">Time zone</label><select class="ut-select" id="tz">${tz.map(z => `<option${z === s.time.timezone ? ' selected' : ''}>${esc(z)}</option>`).join('')}</select></div>
      ${sw('ntp', s.time.ntp, 'Time from the network (NTP)')}${field('ntps', 'NTP-Server', s.time.ntp_server)}<button class="ut-btn ut-btn--primary" id="tsave">Save</button></div>`;
  } else if (sel === 'power') {
    const pw = s.power, nx = await api('power/next').catch(() => ({}));
    main = `<h2>Power</h2><div class="form">${field('spd', 'Spin down disks after (minutes, 0 = never)', pw.spindown_min, 'type=number min=0 max=600')}
      <div class="ut-field"><label for="pwo">After a power failure</label><select class="ut-select" id="pwo">${[['former', 'as before (if it was running, it starts again)'], ['always', 'always switch on'], ['never', 'stay off']].map(([k, v]) => `<option value="${k}"${pw.pwron === k ? ' selected' : ''}>${v}</option>`).join('')}</select></div>
      ${sw('wol', pw.wol, 'Wake-on-LAN (switch on over the network)')}
      <div class="ut-section-title">Power schedule</div>${sw('psa', pw.schedule_active, 'Schedule active')}
      <table class="ut-table"><thead><tr><th>Action</th><th>Repetition</th><th>Day</th><th>Time</th><th></th></tr></thead><tbody id="pst">${pw.schedule.map(powerRow).join('')}</tbody></table>
      <button class="ut-btn ut-btn--sm" id="psadd">+ Entry</button>
      <p class="ut-faint">Next power-on: ${nx.on ? esc(nx.on.replace('T', ' ')) : '–'} · next off/restart: ${nx.off ? esc(nx.off.replace('T', ' ')) : '–'}. Switching on via the RTC alarm: at most 27 days ahead.</p>
      <div class="ut-section-title">UPS (APC via USB)</div>${sw('ups', s.services.ups.active, 'Monitor the UPS when connected')}
      ${field('upsc', 'Shut down at remaining capacity (%)', s.services.ups.min_capacity, 'type=number min=1 max=95')}
      <button class="ut-btn ut-btn--primary" id="psave">Save</button></div>`;
  } else if (sel === 'notify') {
    const m = s.notify.mail;
    main = `<h2>E-mail notification</h2><div class="form">${sw('ml', m.active, 'Send e-mails')}
      <div class="row">${field('mls', 'Mail server (SMTP)', m.server)}${field('mlp', 'Port (0 = automatic)', m.port, 'type=number min=0 max=65535')}</div>
      ${sw('mla', m.auth, 'Mail server login')}<div class="row">${field('mlu', 'User name', m.username, 'autocomplete=off')}${field('mlw', m.password_set ? 'Password (saved; empty = keep)' : 'Password', '', 'type=password autocomplete=new-password')}</div>
      ${field('mlf', 'Sender', m.from)}${field('mlt', 'Warnings to', m.alerts_to)}${sw('mlal', m.alerts, 'Send warnings (RAID, SMART, volume full)')}
      ${field('mlr', 'Log report to', m.log_to)}${sw('mlra', m.report_all, 'Report with all messages (otherwise warnings only)')}
      <div class="row"><div class="ut-field"><label for="mlsc">Report</label><select class="ut-select" id="mlsc">${[['hourly', 'hourly'], ['daily', 'daily'], ['weekly', 'weekly']].map(([k, v]) => `<option value="${k}"${m.schedule === k ? ' selected' : ''}>${v}</option>`).join('')}</select></div>
        <div class="ut-field"><label for="mld">Day</label><select class="ut-select" id="mld">${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d, i) => `<option value="${i}"${m.day === i ? ' selected' : ''}>${d}</option>`).join('')}</select></div>
        ${field('mlh', 'Time (HH:MM)', String(m.hour).padStart(2, '0') + ':' + String(m.minute).padStart(2, '0'))}</div>
      ${field('mlj', 'Subject prefix', m.subject)}
      <div class="row"><button class="ut-btn ut-btn--primary" id="mlsave">Save</button><button class="ut-btn" id="mltest">Send test mail</button></div></div>`;
  } else if (sel === 'syslog') {
    const g = s.notify.syslog, ss = s.services.syslog_server, sh = (await api('shares')).shares;
    const cur = sh.find(x => ss.path && ss.path.startsWith(x.path.replace(/\/$/, '') + '/'));
    main = `<h2>Syslog</h2><div class="form"><div class="ut-section-title">Send the log to a syslog server</div>
      ${sw('lg', g.active, 'Forward')}<div class="row">${field('lgs', 'Server', g.server)}${field('lgp', 'Port (UDP)', g.port, 'type=number')}</div>
      <div class="ut-section-title">Syslog server (collect messages of other devices)</div>${sw('ls', ss.active, 'Syslog server on port 514')}
      <div class="row"><div class="ut-field"><label for="lsh">Share</label><select class="ut-select" id="lsh">${sh.map(x => `<option${cur && cur.name === x.name ? ' selected' : ''}>${esc(x.name)}</option>`).join('')}</select></div>
        ${field('lsf', 'Folder', cur ? ss.path.slice(cur.path.replace(/\/$/, '').length + 1).replace(/\/$/, '') : 'syslog')}</div>
      <div class="row"><div class="ut-field"><label for="lsfm">Format</label><select class="ut-select" id="lsfm"><option value="simple"${ss.format === 'simple' ? ' selected' : ''}>simple (date, device, message)</option><option value="full"${ss.format === 'full' ? ' selected' : ''}>complete</option></select></div>
        ${field('lsm', 'Keep months', ss.months, 'type=number min=1 max=60')}</div>
      <button class="ut-btn ut-btn--primary" id="lgsave">Save</button></div>`;
  } else if (sel === 'printers') {
    const pr = await api('printers');
    main = `<h2>Printer (USB)</h2><div class="form">${sw('prt', s.services.printer.active, 'Share USB printers on the network (SMB and IPP)')}
      <p class="ut-faint">Connected USB printers get a queue without a driver; the computer that prints brings the driver.</p>
      ${pr.printers.length ? `<div class="ut-table-wrap"><table class="ut-table"><thead><tr><th>Name</th><th>Model</th><th>Status</th><th>Jobs</th><th></th></tr></thead><tbody>
      ${pr.printers.map(x => `<tr><td>${esc(x.name)}</td><td>${esc(x.model)}</td><td>${esc(x.status)}</td><td class="num">${x.jobs}</td><td><button class="ut-btn ut-btn--sm" data-cancel="${esc(x.name)}">Delete jobs</button></td></tr>`).join('')}</tbody></table></div>` : '<p>No printer known.</p>'}
      <button class="ut-btn ut-btn--primary" id="prsave">Save</button></div>`;
  } else if (sel === 'office') {
    const o = await api('office');
    main = `<h2>Office</h2><div class="form">
      <p>Documents stay on the NAS; an office server elsewhere edits them in the browser (Collabora Online, Nextcloud Office, ONLYOFFICE). It needs more memory than this NAS has, so it runs on another computer, a server or at a member of your UntrashMesh. Files then shows <b>Open in Office</b> for the document types it supports.</p>
      ${field('ofs', 'Office server', o.server, 'placeholder="https://office.example.org:9980"')}
      ${field('ofw', 'Address of this NAS, as the office server reaches it', o.wopi_base, `placeholder="http://${esc(location.hostname)}"`)}
      ${sw('ofi', o.insecure, 'Accept a self-signed certificate of the office server')}
      <p class="ut-faint">The office server must be allowed to use this NAS as storage (Collabora: <span class="mono">aliasgroup</span>/<span class="mono">storage.wopi.host</span> in coolwsd.xml). Both fields empty: the office bridge is off.</p>
      ${o.error ? `<div class="ut-callout ut-callout--danger"><div>${esc(o.error)}</div></div>` : o.enabled ? `<p class="ut-faint">${esc(UTI18N.tr('Supported types:'))} <span class="mono" translate="no">${esc(o.exts.join(' '))}</span></p>` : ''}
      <div class="row"><button class="ut-btn ut-btn--primary" id="ofsave">Save and check</button></div>
      <div class="ut-section-title">Nextcloud without the office bridge</div>
      <p class="ut-faint">A Nextcloud can also use the NAS shares directly: in Nextcloud, External storage → WebDAV with <span class="mono" translate="no">http://${esc(location.hostname)}:5002/webdav/&lt;share&gt;</span> (WebDAV on under Services), or SMB. Nextcloud Office then edits the files on the NAS.</p></div>`;
  } else if (sel === 'cert') {
    const ci = await api('cert'), h = s.services.https;
    main = `<h2>Certificate and HTTPS</h2><div class="form">
      ${ci.present ? `<div class="ut-card mono" style="font-size:12px">Owner: ${esc(ci.subject)}<br>Issuer: ${esc(ci.issuer)}${ci.self_signed ? ' (self-signed)' : ''}<br>valid: ${esc(ci.from)} – ${esc(ci.until)}<br>SHA-256: ${esc(ci.fingerprint)}</div>` : '<p>No certificate yet.</p>'}
      <div class="row">${field('ccn', 'Name (CN)', s.hostname)}<button class="ut-btn" id="cgen" style="align-self:end">Create a self-signed certificate</button></div>
      <div class="ut-section-title">Own certificate</div><textarea class="ut-textarea mono" id="ccrt" rows="4" placeholder="-----BEGIN CERTIFICATE----- (with intermediate certificates)"></textarea>
      <textarea class="ut-textarea mono" id="ckey" rows="4" placeholder="-----BEGIN PRIVATE KEY----- (unencrypted)"></textarea><button class="ut-btn" id="cup">Upload</button>
      <div class="ut-section-title">HTTPS for this interface</div><div class="row">${sw('hs', h.active, 'HTTPS')} ${field('hsp', 'Port', h.port, 'type=number')} ${sw('hsf', h.force, 'Redirect HTTP to HTTPS')}</div>
      <button class="ut-btn ut-btn--primary" id="hssave">Save (interface restarts)</button>
      <p class="ut-faint">The certificate also applies to FTP over TLS and WebDAV (port 5003).</p></div>`;
  } else if (sel === 'copybtn') {
    const sh = (await api('shares')).shares, last = await api('copybtn');
    const byPath = p => (sh.find(x => x.path === p) || {}).name || '';
    const sel_ = (id, cur, empty) => `<select class="ut-select" id="${id}">${empty ? `<option value="">${empty}</option>` : ''}${sh.map(x => `<option${x.name === cur ? ' selected' : ''}>${esc(x.name)}</option>`).join('')}</select>`;
    const c = s.copybtn.copy, y = s.copybtn.sync;
    main = `<h2>COPY/SYNC button</h2><div class="form"><p class="ut-faint">Short press = copy, hold 3 seconds = synchronise. The source is the most recently connected USB drive.</p>
      <div class="ut-section-title">Copy</div><div class="row"><div class="ut-field"><label>NAS share</label>${sel_('cbs', byPath(c.share_path), '– none –')}</div>
        <div class="ut-field"><label>Direction</label><select class="ut-select" id="cbd"><option value="cp2Vol"${c.direction === 'cp2Vol' ? ' selected' : ''}>USB → NAS</option><option value="cp2USB"${c.direction === 'cp2USB' ? ' selected' : ''}>NAS → USB</option></select></div></div>
      <div class="row"><div class="ut-field"><label>Keep replaced files in</label>${sel_('cbb', byPath(c.bak_path), '– do not keep –')}</div>${sw('cbn', c.newdir, 'Copy into a new (dated) folder')}</div>
      <div class="ut-section-title">Synchronise</div><div class="row"><div class="ut-field"><label>NAS share</label>${sel_('sys', byPath(y.share_path), '– none –')}</div>
        <div class="ut-field"><label>Direction</label><select class="ut-select" id="syd">${[['twoWay', 'both directions'], ['sync2USB', 'NAS → USB (mirror)'], ['sync2Vol', 'USB → NAS (mirror)']].map(([k, v]) => `<option value="${k}"${y.direction === k ? ' selected' : ''}>${v}</option>`).join('')}</select></div></div>
      <div class="ut-field"><label>Keep replaced/deleted files in</label>${sel_('syb', byPath(y.bak_path), '– do not keep –')}</div>
      <div class="row"><button class="ut-btn ut-btn--primary" id="cbsave">Save</button><button class="ut-btn" data-cbrun="copy">Copy now</button><button class="ut-btn" data-cbrun="sync">Synchronise now</button></div>
      ${last.kind ? `<p class="ut-faint">Last: ${esc(last.kind.toUpperCase())} ${last.ok ? 'done' : 'failed'} · ${esc(new Date(last.time * 1000).toLocaleString(UTI18N.locale))}<br>${esc((last.log || []).join(' '))}</p>` : ''}</div>`;
  } else if (sel === 'dyndns') {
    const d = s.services.dyndns;
    const prov = [['dyndns', 'DynDNS (dyn.com)'], ['noip', 'No-IP'], ['3322', '3322.org'], ['zoneedit', 'ZoneEdit'], ['duckdns', 'Duck DNS'], ['freedns', 'FreeDNS (afraid.org)'], ['dynv6', 'dynv6']];
    main = `<h2>DynDNS</h2><div class="form">${sw('dd', d.active, 'Keep the address current at the DynDNS provider')}
      <div class="ut-field"><label for="ddp">Provider</label><select class="ut-select" id="ddp">${prov.map(([k, v]) => `<option value="${k}"${d.provider === k ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></div>
      ${field('ddh', 'Host name', d.hostname)}${field('ddu', 'User name', d.username, 'autocomplete=off')}${field('ddw', d.password_set ? 'Password / token (saved; empty = keep)' : 'Password / token', '', 'type=password autocomplete=new-password')}
      <button class="ut-btn ut-btn--primary" id="ddsave">Save</button></div>`;
  } else if (sel === 'recycle') {
    main = `<h2>Recycle bin</h2><div class="form"><p class="ut-faint">Deleted files in shares with a recycle bin go to the “recycle” folder.</p>
      ${field('rcd', 'Delete permanently after days (0 = never)', s.recycle.expire_days, 'type=number min=0')}<button class="ut-btn ut-btn--primary" id="rsave">Save</button></div>`;
  } else if (sel === 'stock') {
    const st = await api('stock');
    main = `<h2>Back to the Zyxel firmware</h2><div class="form">${st.stick ? `<div class="ut-callout ut-callout--ok"><div>UntrashOS stick with this NAS's stock backup found: <b>${esc(st.run.name)}</b>${st.run.verified ? ' (checked when created)' : ''}.</div></div>
      ${(st.markers || []).includes('ROLLBACK_FAILED') ? '<div class="ut-callout ut-callout--danger" style="margin-top:8px"><div>An earlier attempt failed (UNTRASH/ROLLBACK_FAILED on the stick).</div></div>' : ''}
      <ol class="ut-steps"><li>The backup is checked, the stick gets the “ROLLBACK” order.</li><li>The NAS restarts, runs the Zyxel firmware once, writes its boot data back and switches off (a few minutes, leave the stick in).</li>
      <li>Then switch on: Zyxel firmware as before the installation. Data on the disks stays; UntrashOS files (/.untrash) remain.</li></ol>
      ${field('stc', 'Type STOCK to confirm')}<button class="ut-btn ut-btn--danger" id="stgo">Back to the Zyxel firmware</button>`
      : '<div class="ut-callout ut-callout--warn"><div>Plug in this NAS\'s UntrashOS stick (it holds the backup of the Zyxel state) and open this page again.</div></div>'}</div>`;
  }
  b.innerHTML = side + `<div class="ut-window__main">${main}</div>`;
  navBind(b, 'settings');
  const on = (id, fn) => { const x = $('#' + id, b); if (x) x.onclick = fn; };
  on('ofsave', () => save('office/settings', { server: $('#ofs', b).value.trim(), wopi_base: $('#ofw', b).value.trim(), insecure: $('#ofi', b).checked }, 'settings', 'office'));
  on('lsave', async () => {
    try {
      await api('settings', { language: $('#slang', b).value });
      UTI18N.set($('#blang', b).value);      // reloads in the chosen language
    } catch (e) { fail(e); }
  });
  on('svsave', () => {
    const ex = $('#nfsx', b).value.split('\n').map(l => l.trim().split(/\s+/)).filter(p => p[0]).map(p => ({ path: p[0], clients: p[1] || '*', readonly: p[2] === 'ro' }));
    save('settings', { services: { ssh: { active: $('#ssh', b).checked, sftp: $('#sftp', b).checked, port: +$('#sshp', b).value || 22 },
      ftp: { active: $('#ftp', b).checked, tls: $('#ftps', b).checked, anonymous: $('#ftpa', b).checked, port: +$('#ftpp', b).value || 21, conn_limit: +$('#ftpc', b).value || 1, down_kbs: +$('#ftpd', b).value || 0 },
      mediaserver: { active: $('#dlna', b).checked }, time_machine: { active: $('#tm', b).checked, share: $('#tms', b).value }, nfs: { active: $('#nfs', b).checked, exports: ex },
      webdav: { active: $('#dav', b).checked, anonymous: $('#davan', b).checked }, webpublish: { active: $('#wp', b).checked, port: +$('#wpp', b).value || 80 } } }, 'settings', 'services');
  });
  on('tsave', () => save('settings', { time: { timezone: $('#tz', b).value, ntp: $('#ntp', b).checked, ntp_server: $('#ntps', b).value.trim() } }, 'settings', 'time'));
  const psRows = () => $$('[data-ps]', b).map(r => { const v = k => $(`[data-k=${k}]`, r).value; const [h, m] = (v('time').match(/^(\d{1,2}):(\d{2})$/) || [0, 0, 0]).slice(1).map(Number);
    return { action: v('action'), kind: v('kind'), day: +v('day'), mday: +v('mday') || 1, hour: h, minute: m }; });
  on('psadd', () => { $('#pst', b).insertAdjacentHTML('beforeend', powerRow({ action: 'off', kind: 'daily', hour: 23, minute: 0, day: 0, mday: 1 }, 'n'));
    $$('[data-psdel]', b).forEach(x => x.onclick = () => x.closest('tr').remove()); });
  $$('[data-psdel]', b).forEach(x => x.onclick = () => x.closest('tr').remove());
  on('psave', () => save('settings', { power: { spindown_min: +$('#spd', b).value || 0, pwron: $('#pwo', b).value, wol: $('#wol', b).checked,
    schedule_active: $('#psa', b).checked, schedule: psRows() }, services: { ups: { active: $('#ups', b).checked, min_capacity: +$('#upsc', b).value || 5 } } }, 'settings', 'power'));
  const mailReq = () => { const [h, mi] = ($('#mlh', b).value.match(/^(\d{1,2}):(\d{2})$/) || [0, 0, 0]).slice(1).map(Number);
    return { notify: { mail: { active: $('#ml', b).checked, server: $('#mls', b).value.trim(), port: +$('#mlp', b).value || 0, auth: $('#mla', b).checked,
      username: $('#mlu', b).value, password: $('#mlw', b).value, from: $('#mlf', b).value.trim(), alerts_to: $('#mlt', b).value.trim(), alerts: $('#mlal', b).checked,
      log_to: $('#mlr', b).value.trim(), report_all: $('#mlra', b).checked, schedule: $('#mlsc', b).value, day: +$('#mld', b).value, hour: h, minute: mi, subject: $('#mlj', b).value } } }; };
  on('mlsave', () => save('settings', mailReq(), 'settings', 'notify'));
  on('mltest', async () => { try { await api('settings', mailReq()); await api('notify/test', {}); toast('Test mail sent'); } catch (e) { fail(e); } });
  on('lgsave', () => save('settings', { notify: { syslog: { active: $('#lg', b).checked, server: $('#lgs', b).value.trim(), port: +$('#lgp', b).value || 514 } },
    services: { syslog_server: { active: $('#ls', b).checked, share: $('#lsh', b).value, folder: $('#lsf', b).value.trim(), format: $('#lsfm', b).value, months: +$('#lsm', b).value || 6 } } }, 'settings', 'syslog'));
  on('cgen', async () => { try { await api('cert/regenerate', { cn: $('#ccn', b).value.trim() }); toast('Certificate created', 'The interface is restarting.'); setTimeout(() => render('settings', 'cert'), 3000); } catch (e) { fail(e); } });
  on('cup', async () => { try { await api('cert/upload', { cert: $('#ccrt', b).value, key: $('#ckey', b).value }); toast('Certificate installed'); setTimeout(() => render('settings', 'cert'), 3000); } catch (e) { fail(e); } });
  on('hssave', () => save('settings', { services: { https: { active: $('#hs', b).checked, port: +$('#hsp', b).value || 443, force: $('#hsf', b).checked } } }, 'settings', 'cert'));
  on('cbsave', () => save('settings', { copybtn: { copy: { share: $('#cbs', b).value, bak_share: $('#cbb', b).value, direction: $('#cbd', b).value, newdir: $('#cbn', b).checked },
    sync: { share: $('#sys', b).value, bak_share: $('#syb', b).value, direction: $('#syd', b).value } } }, 'settings', 'copybtn'));
  $$('[data-cbrun]', b).forEach(x => x.onclick = async () => { try { await api('copybtn/run', { kind: x.dataset.cbrun }); toast('Running', x.dataset.cbrun.toUpperCase()); setTimeout(() => body('settings') && render('settings', 'copybtn'), 5000); } catch (e) { fail(e); } });
  on('prsave', () => save('settings', { services: { printer: { active: $('#prt', b).checked } } }, 'settings', 'printers'));
  $$('[data-cancel]', b).forEach(x => x.onclick = async () => { try { await api('printers/cancel', { name: x.dataset.cancel }); toast('Jobs deleted'); render('settings', 'printers'); } catch (e) { fail(e); } });
  on('ddsave', () => save('settings', { services: { dyndns: { active: $('#dd', b).checked, provider: $('#ddp', b).value, hostname: $('#ddh', b).value.trim(), username: $('#ddu', b).value, password: $('#ddw', b).value } } }, 'settings', 'dyndns'));
  on('rsave', () => save('settings', { recycle: { expire_days: +$('#rcd', b).value || 0 } }, 'settings', 'recycle'));
  on('stgo', async () => {
    try { await api('stock/rollback', { confirm: $('#stc', b).value.trim() });
      $('#app').innerHTML = '<main class="ut-login"><div class="ut-login__card"><h2>Way back running</h2><p>The NAS restarts, restores the Zyxel firmware and then switches off. Only then switch it on again.</p></div></main>';
    } catch (e) { fail(e); }
  });
};

/* cloud ---------------------------------------------------------------- */
const DIRS = { both: 'two-way sync', up: 'upload only', down: 'download only' };
const RTYPE = { dropbox: 'Dropbox', drive: 'Google Drive', ftp: 'FTP-Server' };
function cloudConnect(provider) {
  const s = dialog({ title: 'Connect ' + RTYPE[provider], ok: 'Done', body: `${field('cn', 'Account name', provider === 'drive' ? 'GoogleDrive' : 'Dropbox')}
    <ol class="ut-steps"><li><button class="ut-btn" id="cgo">Open the sign-in page</button> (new tab) and sign in and agree there.</li>
    <li>Then the browser shows an error page at <span class="mono">localhost:53682</span> (or 127.0.0.1:53682) – that is correct.</li>
    <li>Copy the complete address from that page's address bar and paste it here:</li></ol>${field('cu', 'Redirect address', '', 'placeholder="http://127.0.0.1:53682/?state=…&code=…"')}`,
    onOk: async s => { await api('cloud/auth-finish', { name: $('#cn', s).value.trim(), url: $('#cu', s).value.trim() }); toast('Account connected'); render('cloud'); } });
  $('#cgo', s).onclick = async () => { const w = window.open('about:blank', '_blank');
    try { const r = await api('cloud/auth-start', { provider }); if (w) w.location = r.url; else toast('Sign-in page', r.url); } catch (e) { if (w) w.close(); fail(e); } };
}
function cloudJob(c, j) {
  j = j || { name: 'Sync', remote: (c.remotes[0] || {}).name, path: '', share: c.shares[0], folder: '', direction: 'both', interval_min: 60, active: true };
  dialog({ title: j.id ? 'Edit job' : 'New job', ok: 'Save', body: `${field('jn', 'Name', j.name)}
    <div class="row"><div class="ut-field"><label for="jr">Account</label><select class="ut-select" id="jr">${c.remotes.map(r => `<option value="${esc(r.name)}"${r.name === j.remote ? ' selected' : ''}>${esc(r.name)} (${esc(RTYPE[r.type] || r.type)})</option>`).join('')}</select></div>${field('jp', 'Folder in the cloud (empty = everything)', j.path)}</div>
    <div class="row"><div class="ut-field"><label for="js">Share</label><select class="ut-select" id="js">${c.shares.map(x => `<option${x === j.share ? ' selected' : ''}>${esc(x)}</option>`).join('')}</select></div>${field('jf', 'Folder in the share', j.folder)}</div>
    <div class="row"><div class="ut-field"><label for="jd">Direction</label><select class="ut-select" id="jd">${Object.entries(DIRS).map(([k, v]) => `<option value="${k}"${k === j.direction ? ' selected' : ''}>${v}</option>`).join('')}</select></div>${field('ji', 'every … minutes', j.interval_min, 'type=number min=5')}</div>
    ${sw('ja', j.active, 'Active')}<p class="ut-faint">Two-way = Dropbox/Google Drive client of the stock firmware; “upload only” = Upload Manager (new files to the FTP server).</p>`,
    onOk: async s => { const nj = Object.assign({}, j, { name: $('#jn', s).value.trim(), remote: $('#jr', s).value, path: $('#jp', s).value.trim(), share: $('#js', s).value,
      folder: $('#jf', s).value.trim(), direction: $('#jd', s).value, interval_min: +$('#ji', s).value || 60, active: $('#ja', s).checked });
      await api('cloud/jobs', { jobs: c.jobs.filter(x => x.id !== j.id).concat([nj]) }); render('cloud'); } });
}
VIEWS.cloud = async b => {
  const c = await api('cloud');
  b.innerHTML = `<div class="ut-window__main"><div class="row"><div class="ut-section-title" style="flex:1">Accounts</div>
      <button class="ut-btn ut-btn--sm" data-conn="dropbox">+ Dropbox</button><button class="ut-btn ut-btn--sm" data-conn="drive">+ Google Drive</button><button class="ut-btn ut-btn--sm" id="cftp">+ FTP-Server</button></div>
    <div class="ut-card">${c.remotes.length ? c.remotes.map(r => `<div class="row"><b>${esc(r.name)}</b> <span class="ut-faint">${esc(RTYPE[r.type] || r.type)}</span><button style="margin-left:auto" class="ut-btn ut-btn--sm ut-btn--danger" data-rdel="${esc(r.name)}">Remove</button></div>`).join('') : '<div class="empty">No account connected yet.</div>'}</div>
    <div class="row"><div class="ut-section-title" style="flex:1">Jobs</div>${c.remotes.length ? '<button class="ut-btn ut-btn--primary ut-btn--sm" id="cjob">+ Job</button>' : ''}</div>
    ${c.jobs.length ? `<div class="ut-table-wrap"><table class="ut-table"><thead><tr><th>Name</th><th>Account</th><th>Direction</th><th>NAS</th><th>Last</th><th></th></tr></thead><tbody>${c.jobs.map(j => { const st = c.status[j.id];
      return `<tr><td>${esc(j.name)}${j.active ? '' : ' <span class="ut-pill ut-pill--plain">off</span>'}</td><td>${esc(j.remote)}:${esc(j.path || '/')}</td><td>${DIRS[j.direction]}</td><td class="mono">${esc(j.share + (j.folder ? '/' + j.folder : ''))}</td>
      <td>${st ? `<span class="ut-pill ${st.ok ? 'ut-pill--ok' : 'ut-pill--danger'}" title="${esc(st.log.slice(-5).join('\n'))}">${st.ok ? 'ok' : 'Error'}</span> ${esc(new Date(st.time * 1000).toLocaleString(UTI18N.locale))}` : '–'}</td>
      <td><button class="ut-btn ut-btn--sm" data-jrun="${j.id}">Now</button> <button class="ut-btn ut-btn--sm" data-jed="${j.id}">Edit</button> <button class="ut-btn ut-btn--sm ut-btn--danger" data-jdel="${j.id}">Delete</button></td></tr>`; }).join('')}</tbody></table></div>` : '<div class="ut-card empty">No job.</div>'}
    </div>`;
  $$('[data-conn]', b).forEach(x => x.onclick = () => cloudConnect(x.dataset.conn));
  $('#cftp', b).onclick = () => dialog({ title: 'Add FTP server', ok: 'Save', body: `${field('fn', 'Name', 'FTP')}<div class="row">${field('fh', 'Server')}${field('fp', 'Port', 21, 'type=number')}</div>
    <div class="row">${field('fu', 'User name')}${field('fw', 'Password', '', 'type=password autocomplete=new-password')}</div>${sw('ft', false, 'TLS (explicit)')}`,
    onOk: async s => { await api('cloud/ftp', { name: $('#fn', s).value.trim(), host: $('#fh', s).value.trim(), port: +$('#fp', s).value || 21, user: $('#fu', s).value, password: $('#fw', s).value, tls: $('#ft', s).checked }); render('cloud'); } });
  $$('[data-rdel]', b).forEach(x => x.onclick = () => dialog({ kind: 'danger', title: 'Remove account', ok: 'Remove', okCls: 'ut-btn--danger', body: `<p>${esc(x.dataset.rdel)} remove? The files stay.</p>`,
    onOk: async () => { await api('cloud/delete', { name: x.dataset.rdel }); render('cloud'); } }));
  const nj = $('#cjob', b); if (nj) nj.onclick = () => cloudJob(c);
  $$('[data-jed]', b).forEach(x => x.onclick = () => cloudJob(c, c.jobs.find(j => j.id === x.dataset.jed)));
  $$('[data-jrun]', b).forEach(x => x.onclick = async () => { try { await api('cloud/run', { id: x.dataset.jrun }); toast('Job running'); setTimeout(() => body('cloud') && render('cloud'), 4000); } catch (e) { fail(e); } });
  $$('[data-jdel]', b).forEach(x => x.onclick = async () => { try { await api('cloud/jobs', { jobs: c.jobs.filter(j => j.id !== x.dataset.jdel) }); render('cloud'); } catch (e) { fail(e); } });
};

/* downloads ---------------------------------------------------------------- */
const DLST = { active: 'loading', waiting: 'waiting', paused: 'paused', complete: 'done', error: 'Error', removed: 'removed' };
let DLPOLL = null;
VIEWS.downloads = async (b, sel = 'list') => {
  const d = await api('downloads'), c = d.settings;
  const side = sidebar('downloads', [['#', 'Downloads'], ['list', 'Jobs'], ['settings', 'Settings']], sel);
  let main;
  if (sel === 'settings') {
    main = `<h2>Download service</h2><div class="form">${sw('dla', c.active, 'Download service (HTTP, FTP, BitTorrent, magnet)')}
      <div class="row"><div class="ut-field"><label for="dls">Share</label><select class="ut-select" id="dls">${d.shares.map(x => `<option${x === c.share ? ' selected' : ''}>${esc(x)}</option>`).join('')}</select></div>
        ${field('dlf', 'Target folder', c.folder)}${field('dli', 'Watched folder for .torrent', c.incoming)}</div>
      <div class="row">${field('dld', 'Download max. KB/s (0 = unlimited)', c.dl_kbs, 'type=number min=0')}${field('dlu', 'Upload max. KB/s (0 = unlimited)', c.up_kbs, 'type=number min=0')}${field('dlz', 'Time window HHMM:HHMM (empty = always)', c.period)}</div>
      <div class="row">${field('dlsl', 'Simultaneous downloads', c.slots, 'type=number min=1 max=10')}${field('dlc', 'Connections per torrent', c.max_conn, 'type=number min=2 max=450')}${field('dlp', 'BitTorrent-Port', c.bt_port, 'type=number')}</div>
      <div class="row">${field('dlr', 'Seed until ratio % (-1 = always)', c.ratio, 'type=number min=-1')}${field('dlt', 'Seed at most minutes (-1 = no limit)', c.seed_min, 'type=number min=-1')}</div>
      ${sw('dldht', c.dht, 'DHT')} ${sw('dln', c.notify, 'E-mail when a download is finished')}
      <button class="ut-btn ut-btn--primary" id="dlsave">Save</button></div>`;
  } else {
    main = !c.active ? '<div class="empty">The download service is off (Settings).</div>' : !d.running ? '<div class="ut-callout ut-callout--warn"><div>The download service is starting or not running.</div></div>' : `
      <div class="row">${field('dlurl', 'Address (http, ftp or magnet)', '', 'placeholder="https://… or magnet:?xt=…"')}<button class="ut-btn ut-btn--primary" id="dladd" style="align-self:end">Add</button>
        <label class="ut-btn" style="align-self:end">Torrent file …<input type="file" id="dltor" accept=".torrent" hidden></label></div>
      ${d.items.length ? `<div class="ut-table-wrap"><table class="ut-table"><thead><tr><th>Name</th><th>Status</th><th class="num">Progress</th><th class="num">↓ / ↑</th><th></th></tr></thead><tbody>${d.items.map(x => {
        const pct = x.size ? Math.floor(100 * x.done / x.size) : 0;
        return `<tr><td>${esc(x.name)}${x.error ? '<br><span class="ut-faint">' + esc(x.error) + '</span>' : ''}</td><td>${esc(DLST[x.status] || x.status)}</td>
        <td class="num">${pct} %<br><span class="ut-faint">${size(x.done)} / ${size(x.size)}</span></td><td class="num">${size(x.down)}/s<br>${size(x.up)}/s</td>
        <td>${x.status === 'active' || x.status === 'waiting' ? `<button class="ut-btn ut-btn--sm" data-dl="pause:${x.gid}">Pause</button>` : ''}${x.status === 'paused' ? `<button class="ut-btn ut-btn--sm" data-dl="resume:${x.gid}">Resume</button>` : ''}
        <button class="ut-btn ut-btn--sm ut-btn--danger" data-dl="remove:${x.gid}">Remove</button></td></tr>`; }).join('')}</tbody></table></div>
        <button class="ut-btn ut-btn--sm" data-dl="purge:">Finished ones from the list</button>` : '<div class="empty">No downloads.</div>'}`;
  }
  b.innerHTML = side + `<div class="ut-window__main">${main}</div>`;
  navBind(b, 'downloads');
  const on = (id, fn) => { const x = $('#' + id, b); if (x) x.onclick = fn; };
  on('dladd', async () => { try { await api('downloads/add', { url: $('#dlurl', b).value.trim() }); render('downloads'); } catch (e) { fail(e); } });
  const tf = $('#dltor', b); if (tf) tf.onchange = async () => { try { await api('downloads/torrent', tf.files[0], true); render('downloads'); } catch (e) { fail(e); } };
  $$('[data-dl]', b).forEach(x => x.onclick = async () => { const [action, gid] = x.dataset.dl.split(':'); try { await api('downloads/ctl', { action, gid }); render('downloads'); } catch (e) { fail(e); } });
  on('dlsave', () => save('settings', { services: { download: { active: $('#dla', b).checked, share: $('#dls', b).value, folder: $('#dlf', b).value.trim(), incoming: $('#dli', b).value.trim(),
    dl_kbs: +$('#dld', b).value || 0, up_kbs: +$('#dlu', b).value || 0, period: $('#dlz', b).value.trim(), slots: +$('#dlsl', b).value || 3, max_conn: +$('#dlc', b).value || 55,
    bt_port: +$('#dlp', b).value || 6881, ratio: +$('#dlr', b).value, seed_min: +$('#dlt', b).value, dht: $('#dldht', b).checked, notify: $('#dln', b).checked } } }, 'downloads', 'settings'));
  clearTimeout(DLPOLL);
  if (sel === 'list' && d.items.some(x => x.status === 'active')) DLPOLL = setTimeout(() => { if (body('downloads')) render('downloads', 'list'); }, 3000);
};

/* transfers: copy/move jobs, uploads and downloads of the Desk, download service ------------- */
const TRKIND = { copy: 'Copy', move: 'Move', upload: 'Upload', download: 'Download', service: 'Download service' };
const TRSTATE = { running: 'running', paused: 'paused', done: 'done', errors: 'with errors', cancelled: 'cancelled',
  active: 'loading', waiting: 'waiting', complete: 'done', error: 'Error', removed: 'removed' };
const TRS = { sel: 'all', timer: null };
const dur = s => s >= 3600 ? Math.floor(s / 3600) + ' h ' + Math.round(s % 3600 / 60) + ' min' : s >= 60 ? Math.round(s / 60) + ' min' : Math.max(1, Math.round(s)) + ' s';
function trRow(o) {
  const live = o.state === 'running' || o.state === 'paused' || o.state === 'active' || o.state === 'waiting';
  const pct = o.total ? Math.min(100, Math.floor(100 * o.done / o.total)) : (live ? 0 : 100);
  const eta = o.state === 'running' && o.rate > 0 && o.total > o.done ? ' · ' + UTI18N.tr('%s left').replace('%s', dur((o.total - o.done) / o.rate)) : '';
  const btn = (act, label, cls = '') => `<button class="ut-btn ut-btn--sm ${cls}" data-tr="${act}:${esc(o.id)}">${esc(UTI18N.tr(label))}</button>`;
  let acts = '';
  if (o.kind === 'service') acts = (o.state === 'active' || o.state === 'waiting' ? btn('pause', 'Pause') : '') + (o.state === 'paused' ? btn('resume', 'Resume') : '') + btn('cancel', 'Remove', 'ut-btn--danger');
  else if (live) acts = (o.kind === 'copy' || o.kind === 'move' ? (o.state === 'paused' ? btn('resume', 'Resume') : btn('pause', 'Pause')) : '') + btn('cancel', 'Cancel', 'ut-btn--danger');
  else acts = `<button class="ut-btn ut-btn--sm ut-btn--ghost" data-tr="dismiss:${esc(o.id)}" aria-label="${esc(UTI18N.tr('Remove from the list'))}">✕</button>`;
  const sub = [o.kind === 'download' ? (o.where === 'link' ? UTI18N.tr('via share link') : '') : o.where ? '→ ' + o.where : '', o.current && o.current !== o.name ? o.current : '',
    ME.admin && o.user ? UTI18N.tr('by %s').replace('%s', o.user) : ''].filter(Boolean);
  return `<div class="ut-tr${live ? '' : ' ut-tr--end'}"><div class="ut-tr__name"><b>${esc(UTI18N.tr(TRKIND[o.kind] || o.kind))}</b> <span translate="no">${esc(o.name)}</span>
      ${sub.length ? `<div class="ut-faint" translate="no">${esc(sub.join(' · '))}</div>` : ''}</div>
    <div class="ut-tr__bar"><div class="ut-progress${o.state === 'errors' || o.state === 'error' ? ' ut-progress--danger' : o.state === 'paused' ? ' ut-progress--warn' : ''}" style="--v:${pct}%"><i></i></div>
      <span class="ut-faint">${o.total ? `${pct} % · ${size(o.done)} / ${size(o.total)}` : size(o.done)}${o.files > 1 ? ' · ' + UTI18N.tr('%s files').replace('%s', o.files) : ''}</span></div>
    <div class="ut-tr__rate"><span>${esc(UTI18N.tr(TRSTATE[o.state] || o.state))}</span><span class="ut-faint">${o.state === 'running' || o.state === 'active' ? size(o.rate) + '/s' + eta : ''}</span></div>
    <div class="ut-tr__acts">${acts}</div>
    ${(o.errors || []).length ? `<div class="ut-faint ut-tr__err" translate="no">${o.errors.map(esc).join('<br>')}</div>` : ''}</div>`;
}
VIEWS.transfers = async (b, sel) => {
  if (sel) TRS.sel = sel;
  if (!$('#trlist', b)) {
    const items = [['#', 'Transfers'], ['all', 'All'], ['copy', 'Copy and move'], ['upload', 'Uploads'], ['download', 'Downloads']];
    if (ME.admin) items.push(['service', 'Download service']);
    b.innerHTML = sidebar('transfers', items, TRS.sel) + `<div class="ut-window__main"><div id="trlist"><span class="ut-spinner"></span></div>
      <div class="row" style="margin-top:12px"><button class="ut-btn ut-btn--sm" data-tr="dismiss:">Finished ones from the list</button></div>
      <p class="ut-faint">Copying and moving run as their own process: the Desk stays responsive meanwhile. Pause holds a copy where it is; cancel removes the partly copied file.</p></div>`;
    $$('[data-nav]', b).forEach(n => n.onclick = () => { $$('[data-nav]', b).forEach(x => x.removeAttribute('aria-current')); n.setAttribute('aria-current', 'page'); TRS.sel = n.dataset.nav; VIEWS.transfers(b); });
    b.addEventListener('click', async e => {
      const x = e.target.closest('[data-tr]'); if (!x) return;
      const i = x.dataset.tr.indexOf(':'), action = x.dataset.tr.slice(0, i), id = x.dataset.tr.slice(i + 1);
      try { await api('transfers/ctl', { id, action }); VIEWS.transfers(b); } catch (err) { fail(err); }
    });
    CLEANUP.transfers = () => clearTimeout(TRS.timer);
  }
  clearTimeout(TRS.timer);
  let d;
  try { d = await apiRaw('transfers' + (ME.admin && (TRS.sel === 'all' || TRS.sel === 'service') ? '?service=1' : '')); }
  catch (e) { $('#trlist', b).innerHTML = `<div class="ut-callout ut-callout--danger">${esc(e.message)}</div>`; return; }
  const svc = (d.service || []).map(x => ({ id: 'dl:' + x.gid, kind: 'service', name: x.name, state: x.status, total: x.size, done: x.done, rate: x.down,
    errors: x.error ? [x.error] : [], files: 0 }));
  const want = { all: () => true, copy: o => o.kind === 'copy' || o.kind === 'move', upload: o => o.kind === 'upload', download: o => o.kind === 'download', service: o => o.kind === 'service' }[TRS.sel] || (() => true);
  const list = d.ops.concat(svc).filter(want);
  const el = $('#trlist', b); if (!el) return;
  el.innerHTML = list.length ? list.map(trRow).join('') : `<div class="empty">${esc(UTI18N.tr('No transfers.'))}</div>`;
  const busy = list.some(o => o.state === 'running' || o.state === 'active' || o.state === 'paused');
  TRS.timer = setTimeout(() => { if (body('transfers')) VIEWS.transfers(b); }, busy ? 1000 : 5000);
};

/* backup planner ---------------------------------------------------------------- */
const BTYPE = { archive: 'Archive (versions)', sync: 'Synchronisation (mirror)', rsync: 'Rsync server' };
const BSCHED = { manual: 'manual only', hourly: 'hourly', daily: 'daily', weekly: 'weekly', monthly: 'monthly' };
function backupJob(c, j) {
  j = j || { name: UTI18N.tr('Backup'), type: 'archive', source_names: [{ share: c.shares[0], folder: '' }], target: { kind: 'local', share: c.shares[0], folder: UTI18N.tr('Backup') },
    keep: 7, bwlimit: 0, active: true, schedule: { kind: 'daily', hour: 2, minute: 0, day: 0, mday: 1 } };
  const shOpt = cur => c.shares.map(x => `<option${x === cur ? ' selected' : ''}>${esc(x)}</option>`).join('');
  const srcRow = (x, i) => `<div class="row" data-src="${i}"><select class="ut-select">${shOpt(x.share)}</select><input class="ut-input" value="${esc(x.folder || '')}" placeholder="Folder (empty = whole share)"></div>`;
  const t = j.target, sc = j.schedule;
  const s = dialog({ title: j.id ? 'Edit backup' : 'New backup', ok: 'Save', body: `${field('bn', 'Name', j.name)}
    <div class="ut-field"><label for="bt">Type</label><select class="ut-select" id="bt">${Object.entries(BTYPE).map(([k, v]) => `<option value="${k}"${k === j.type ? ' selected' : ''}>${v}</option>`).join('')}</select></div>
    <div class="ut-field"><label>Sources</label><div id="bsrc">${(j.source_names || []).map(srcRow).join('')}</div><button class="ut-btn ut-btn--sm" id="bsadd">+ Source</button></div>
    <div id="blocal"><div class="ut-field"><label for="bk">Target</label><select class="ut-select" id="bk"><option value="local"${t.kind !== 'usb' ? ' selected' : ''}>Share on this NAS</option>${c.usb.map(u => `<option value="usb:${esc(u.path)}"${t.kind === 'usb' && t.path === u.path ? ' selected' : ''}>USB: ${esc(u.label)}</option>`).join('')}</select></div>
      <div class="row" id="bshare"><select class="ut-select" id="bts">${shOpt(t.share)}</select><input class="ut-input" id="btf" value="${esc(t.folder || '')}" placeholder="Folder"></div></div>
    <div id="brs"><div class="row">${field('bh', 'Rsync server', t.host || '')}${field('bm', 'Module', t.module || '')}</div><div class="row">${field('bu', 'User name', t.user || '')}${field('bp', 'Password (empty = keep)', '', 'type=password autocomplete=new-password')}</div></div>
    <div class="row"><div class="ut-field"><label for="bsk">Schedule</label><select class="ut-select" id="bsk">${Object.entries(BSCHED).map(([k, v]) => `<option value="${k}"${k === sc.kind ? ' selected' : ''}>${v}</option>`).join('')}</select></div>
      ${field('bsh', 'Time HH:MM', String(sc.hour).padStart(2, '0') + ':' + String(sc.minute).padStart(2, '0'))}
      <div class="ut-field"><label for="bsd">Weekday</label><select class="ut-select" id="bsd">${['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d, i) => `<option value="${i}"${sc.day === i ? ' selected' : ''}>${d}</option>`).join('')}</select></div>
      ${field('bsm', 'Day of month', sc.mday, 'type=number min=1 max=28')}</div>
    <div class="row">${field('bkeep', 'Keep versions (archive)', j.keep, 'type=number min=1')}${field('bbw', 'Bandwidth KB/s (0 = unlimited)', j.bwlimit, 'type=number min=0')}</div>${sw('ba', j.active, 'Active')}`,
    onOk: async s => { const [h, mi] = ($('#bsh', s).value.match(/^(\d{1,2}):(\d{2})$/) || [0, 2, 0]).slice(1).map(Number); const k = $('#bk', s).value;
      const nj = Object.assign({}, j, { name: $('#bn', s).value.trim(), type: $('#bt', s).value,
        sources: $$('[data-src]', s).map(r => ({ share: $('select', r).value, folder: $('input', r).value.trim() })),
        target: $('#bt', s).value === 'rsync' ? { kind: 'rsync', host: $('#bh', s).value.trim(), module: $('#bm', s).value.trim(), user: $('#bu', s).value.trim() }
          : k.startsWith('usb:') ? { kind: 'usb', path: k.slice(4) } : { kind: 'local', share: $('#bts', s).value, folder: $('#btf', s).value.trim() },
        password: $('#bp', s).value, keep: +$('#bkeep', s).value || 7, bwlimit: +$('#bbw', s).value || 0, active: $('#ba', s).checked,
        schedule: { kind: $('#bsk', s).value, hour: h, minute: mi, day: +$('#bsd', s).value, mday: +$('#bsm', s).value || 1 } });
      const keep = c.jobs.filter(x => x.id !== j.id).map(x => Object.assign({}, x, { sources: x.source_names, target: x.target.kind === 'local' ? { kind: 'local', share: x.target.share, folder: x.target.folder } : x.target }));
      await api('backup/jobs', { jobs: keep.concat([nj]) }); render('backup'); } });
  const vis = () => { const rs = $('#bt', s).value === 'rsync'; $('#brs', s).hidden = !rs; $('#blocal', s).hidden = rs; $('#bshare', s).hidden = $('#bk', s).value !== 'local'; };
  $('#bt', s).onchange = vis; $('#bk', s).onchange = vis; vis();
  $('#bsadd', s).onclick = () => { $('#bsrc', s).insertAdjacentHTML('beforeend', srcRow({ share: c.shares[0], folder: '' }, $$('[data-src]', s).length)); };
}
VIEWS.backup = async b => {
  const c = await api('backup');
  b.innerHTML = `<div class="ut-window__main"><div class="row"><div class="ut-section-title" style="flex:1">Backup jobs</div><button class="ut-btn ut-btn--primary ut-btn--sm" id="bnew">+ Backup</button></div>
    ${c.jobs.length ? `<div class="ut-table-wrap"><table class="ut-table"><thead><tr><th>Name</th><th>Type</th><th>Target</th><th>Schedule</th><th>Last</th><th></th></tr></thead><tbody>${c.jobs.map(j => { const st = c.status[j.id];
      const tgt = j.target.kind === 'rsync' ? 'rsync://' + j.target.host + '/' + j.target.module : j.target.kind === 'usb' ? 'USB ' + j.target.path : j.target.share + (j.target.folder ? '/' + j.target.folder : '');
      return `<tr><td>${esc(j.name)}${j.active ? '' : ' <span class="ut-pill ut-pill--plain">off</span>'}</td><td>${BTYPE[j.type]}</td><td class="mono">${esc(tgt)}</td><td>${BSCHED[j.schedule.kind]}</td>
      <td>${st ? `<span class="ut-pill ${st.ok ? 'ut-pill--ok' : 'ut-pill--danger'}" title="${esc(st.log.slice(-6).join('\n'))}">${st.ok ? 'ok' : 'Error'}</span> ${esc(new Date(st.time * 1000).toLocaleString(UTI18N.locale))}` : '–'}</td>
      <td><button class="ut-btn ut-btn--sm" data-brun="${j.id}">Now</button> ${j.type !== 'rsync' ? `<button class="ut-btn ut-btn--sm" data-bres="${j.id}">Restore</button>` : ''} <button class="ut-btn ut-btn--sm" data-bed="${j.id}">Edit</button> <button class="ut-btn ut-btn--sm ut-btn--danger" data-bdel="${j.id}">Delete</button></td></tr>`; }).join('')}</tbody></table></div>` : '<div class="ut-card empty">No backup set up.</div>'}
    <p class="ut-faint">Archive: one dated folder per backup, unchanged files take no extra space. Synchronisation: the target mirrors the source. Rsync: to an rsync server (another NAS or computer).</p></div>`;
  const plain = x => Object.assign({}, x, { sources: x.source_names, target: x.target.kind === 'local' ? { kind: 'local', share: x.target.share, folder: x.target.folder } : x.target });
  $('#bnew', b).onclick = () => backupJob(c);
  $$('[data-bed]', b).forEach(x => x.onclick = () => backupJob(c, c.jobs.find(j => j.id === x.dataset.bed)));
  $$('[data-bdel]', b).forEach(x => x.onclick = async () => { try { await api('backup/jobs', { jobs: c.jobs.filter(j => j.id !== x.dataset.bdel).map(plain) }); render('backup'); } catch (e) { fail(e); } });
  $$('[data-brun]', b).forEach(x => x.onclick = async () => { try { await api('backup/run', { id: x.dataset.brun }); toast('Backup running'); setTimeout(() => body('backup') && render('backup'), 5000); } catch (e) { fail(e); } });
  $$('[data-bres]', b).forEach(x => x.onclick = async () => { try {
    const v = (await api('backup/versions?id=' + x.dataset.bres)).versions;
    if (!v.length) return toast('No backup yet');
    dialog({ title: 'Restore', ok: 'Restore', body: `<div class="ut-field"><label for="rv">Version</label><select class="ut-select" id="rv">${v.map(n => `<option value="${esc(n)}">${n === '-' ? 'current mirror' : esc(n.replace(/^(\d{4})(\d\d)(\d\d)-(\d\d)(\d\d)(\d\d)$/, '$3.$2.$1 $4:$5:$6'))}</option>`).join('')}</select></div>
      <div class="row"><select class="ut-select" id="rs">${c.shares.map(n => `<option>${esc(n)}</option>`).join('')}</select><input class="ut-input" id="rf" value="Restored" placeholder="Folder"></div><p class="ut-faint">Existing files with the same name are overwritten.</p>`,
      onOk: async s => { await api('backup/restore', { id: x.dataset.bres, version: $('#rv', s).value, share: $('#rs', s).value, folder: $('#rf', s).value.trim() }); toast('Restored'); } });
  } catch (e) { fail(e); } });
};

/* updates ---------------------------------------------------------------- */
VIEWS.updates = async b => {
  const u = await api('update'), rel = u.release || {}, av = rel.available, dl = rel.download || {}, cfg = u.settings || {};
  const when = t => t ? esc(new Date(t * 1000).toLocaleString(UTI18N.locale)) : '–';
  let auto;
  if (av) {
    const busy = dl.state === 'downloading' || dl.state === 'verifying';
    const pct = dl.size ? Math.round(100 * (dl.bytes || 0) / dl.size) : 0;
    auto = `<div class="ut-card"><div class="ut-card__head"><h3>${esc(UTI18N.tr('UntrashOS %s is available').replace('%s', av.version))}</h3>
        ${av.prerelease ? '<span class="ut-pill ut-pill--warn">Beta</span>' : ''}<span class="ut-spacer"></span>
        ${av.page ? `<a href="${esc(av.page)}" target="_blank" rel="noopener">Release page</a>` : ''}</div>
      ${av.notes ? `<pre translate="no" class="ut-log" style="max-height:220px">${esc(av.notes)}</pre>` : ''}
      ${dl.state === 'ready' ? `<div class="ut-callout ut-callout--ok" style="margin-top:10px"><div>Downloaded and checked (signature, checksums). Installing writes it to the other slot; the NAS starts it after a restart and goes back on its own if it does not start cleanly.</div></div>
          <div class="row" style="margin-top:10px"><button class="ut-btn ut-btn--primary" id="relinst">${esc(UTI18N.tr('Install UntrashOS %s').replace('%s', av.version))}</button></div>`
        : busy ? `<div class="ut-progress" style="margin-top:10px"><i style="--v:${pct}%"></i></div><p class="ut-faint">${dl.state === 'verifying' ? 'Checking (signature, checksums) …' : esc(UTI18N.tr('Downloading …')) + ' ' + pct + ' % (' + gb(dl.bytes || 0) + ' / ' + gb(dl.size || 0) + ')'}</p>`
        : `${dl.state === 'failed' ? `<div class="ut-callout ut-callout--danger" style="margin-top:10px"><div translate="no">${esc(dl.error || '')}</div></div>` : ''}
          <div class="row" style="margin-top:10px"><button class="ut-btn ut-btn--primary" id="reldl">${dl.state === 'failed' ? 'Try again' : 'Download'}</button><span class="ut-faint">${gb(av.size || 0)}</span></div>`}
    </div>`;
    if (busy) setTimeout(() => { if (document.body.contains(b)) render('updates'); }, 2000);
  } else auto = `<div class="ut-callout ut-callout--ok"><div>UntrashOS is up to date.</div></div>`;
  b.innerHTML = `<div class="ut-window__main"><p>Installed: <b>${esc(u.version)}</b> · running from slot <b>${esc(String(u.slot).toUpperCase())}</b></p>
    <div class="ut-section-title">Updates from the release page</div>
    ${rel.error ? `<div class="ut-callout ut-callout--warn" style="margin-bottom:10px"><div>${esc(rel.error)}</div></div>` : ''}
    ${auto}
    <div class="row" style="margin-top:10px"><button class="ut-btn" id="relchk">Check now</button><span class="ut-faint">Last check: ${when(rel.checked)}</span></div>
    <div class="form" style="margin-top:12px">${sw('ucheck', cfg.check !== false, 'Check for updates every day')}<br>
      ${sw('udown', cfg.download !== false, 'Download updates automatically (installing always needs your confirmation)')}
      <div class="ut-field" style="margin-top:10px"><label for="uchan">Channel</label><select class="ut-select" id="uchan">
        <option value="stable"${cfg.channel !== 'beta' ? ' selected' : ''}>Stable releases</option><option value="beta"${cfg.channel === 'beta' ? ' selected' : ''}>Beta (pre-releases too)</option></select>
      <span class="ut-hint">A check is one anonymous request to the release page on github.com; nothing about this NAS is sent. Only images signed by UntrashOS are accepted.</span></div></div>
    <div class="ut-section-title">Install from a file</div>
    <div class="form"><p class="ut-faint">A new system image (slot.utslot) is checked (signature, checksums) and written to the other slot. If it does not start cleanly, the loader automatically goes back to the current one.</p>
    <label class="ut-btn">Choose a system image …<input type="file" id="uf" accept=".utslot" hidden></label>
    <div class="ut-progress" id="upr" hidden style="margin-top:10px"><i></i></div><div class="ut-callout" id="ust" hidden style="margin-top:8px"></div>
    ${u.state === 'ready' && u.source === 'upload' ? `${u.older ? `<div class="ut-callout ut-callout--warn" style="margin:10px 0"><div>${esc(UTI18N.tr('Image %s is not newer than the running system.').replace('%s', u.image))}</div></div>${sw('udowngrade', false, 'Install the older version anyway')}<br>` : ''}<button class="ut-btn ut-btn--primary" id="uinst">Install</button>` : ''}${u.state === 'installed' ? '<button class="ut-btn ut-btn--primary" id="ureb">Restart now</button>' : ''}
    <pre translate="no" class="ut-log" style="margin-top:10px">${esc(u.log.join('\n')) || esc(UTI18N.tr('No operation.'))}</pre></div></div>`;
  $('#relchk', b).onclick = async () => { await api('update/check', {}).catch(fail); toast('Updates', 'Checking the release page …'); setTimeout(() => { if (document.body.contains(b)) render('updates'); }, 4000); };
  const dlb = $('#reldl', b); if (dlb) dlb.onclick = async () => { await api('update/download', {}).catch(fail); setTimeout(() => render('updates'), 1500); };
  const ri = $('#relinst', b); if (ri) ri.onclick = () => dialog({ title: UTI18N.tr('Install UntrashOS %s').replace('%s', av.version), ok: 'Install', okCls: 'ut-btn--primary',
    body: '<p>The image is written to the other slot (a few minutes). Restart afterwards to start it; the current system stays as the fallback.</p>',
    onOk: async () => { await api('update/install', { source: 'release' }); render('updates'); } });
  const save = () => api('update/settings', { check: $('#ucheck', b).checked, download: $('#udown', b).checked, channel: $('#uchan', b).value }).catch(fail);
  ['#ucheck', '#udown', '#uchan'].forEach(q => { $(q, b).onchange = save; });
  $('#uf', b).onchange = () => {
    const f = $('#uf', b).files[0]; if (!f) return;
    const st = $('#ust', b), bar = $('#upr', b);
    const show = (msg, cls) => { st.textContent = msg; st.className = 'ut-callout ' + (cls || ''); st.hidden = false; };
    // a stick image (.img) or anything else: refuse here, before 400 MB go over the network
    if (!/\.utslot$/i.test(f.name) || f.size < 8192 || f.size > 1536 * 1048576) return show(UTI18N.tr('This is not a system image (*.utslot). For updates choose the file untrash-…-update.utslot.'), 'ut-callout--danger');
    // XMLHttpRequest instead of fetch: only it reports upload progress
    const x = new XMLHttpRequest();
    x.open('POST', '/api/update/upload'); x.setRequestHeader('X-UT', '1'); x.setRequestHeader('Content-Type', 'application/octet-stream');
    bar.hidden = false; $('i', bar).style.setProperty('--v', '0%');
    x.upload.onprogress = e => { if (e.lengthComputable) { const p = Math.round(100 * e.loaded / e.total); $('i', bar).style.setProperty('--v', p + '%'); show(UTI18N.tr('Uploading …') + ' ' + p + ' % (' + gb(e.loaded) + ' / ' + gb(e.total) + ')'); } };
    x.upload.onload = () => show(UTI18N.tr('Uploaded, checking (signature, checksums) …'));
    x.onload = () => {
      let j = {}; try { j = JSON.parse(x.responseText); } catch (e) { }
      if (x.status === 200) render('updates');
      else { bar.hidden = true; show((j.error || ('Error ' + x.status)), 'ut-callout--danger'); }
    };
    x.onerror = () => { bar.hidden = true; show(UTI18N.tr('Transfer aborted (network). Please try again.'), 'ut-callout--danger'); };
    show(UTI18N.tr('Uploading …')); x.send(f);
  };
  const i = $('#uinst', b); if (i) i.onclick = async () => { try { await api('update/install', { downgrade: !!($('#udowngrade', b) || {}).checked }); render('updates'); } catch (e) { fail(e); } };
  const r = $('#ureb', b); if (r) r.onclick = () => api('power', { action: 'reboot' }).then(() => toast('Restart', 'The NAS is restarting.'));
};

/* logs ---------------------------------------------------------------- */
VIEWS.logs = async (b, unit = '') => {
  const l = await api('logs?' + new URLSearchParams({ unit }));
  const units = [['', 'System'], ['smbd', 'SMB'], ['untrash-zyxel', 'Volumes'], ['untrash-takeover-firstboot', 'Takeover'], ['ssh', 'SSH'], ['vsftpd', 'FTP'], ['minidlna', 'Media server'], ['untrash-desk', 'Desk']];
  b.innerHTML = sidebar('logs', [['#', 'Logs']].concat(units), unit) + `<div class="ut-window__main"><pre translate="no" class="ut-log" style="max-height:none">${esc(l.lines.join('\n')) || 'empty'}</pre></div>`;
  navBind(b, 'logs');
  const pre = $('pre', b); pre.scrollTop = pre.scrollHeight;
};

/* account ---------------------------------------------------------------- */
/* the user's own sign-in (password / password or app / password and app) */
function signinFields() {
  if (!(ME.apps || []).length) return `<div class="ut-section-title">Sign-in</div><p class="ut-faint">With the UntrashApp you can sign in by confirming on your phone, or use it as a second factor. An administrator pairs the app in UntrashMesh.</p>`;
  return `<div class="ut-section-title">Sign-in</div><p class="ut-faint">${esc(UTI18N.tr('Paired app:'))} <b translate="no">${ME.apps.map(a => esc(a.name)).join(', ')}</b></p>
    <div class="ut-field"><label for="sim">Sign in with</label><select class="ut-select" id="sim">${[['password', 'Password only'], ['app', 'Password or the UntrashApp'], ['both', 'Password and the UntrashApp (two factors)']]
      .map(([k, n]) => `<option value="${k}"${ME.signin === k ? ' selected' : ''}>${esc(UTI18N.tr(n))}</option>`).join('')}</select></div>
    ${field('sip', 'Current password', '', 'type=password autocomplete=current-password')}
    <p class="ut-faint">With two factors, installing updates, deleting users and similar actions also need a confirmation in the app. Lost phone: an administrator resets the sign-in under Users; for admin, the RESET button on the NAS does.</p>
    <button class="ut-btn" id="sis" type="button">Save sign-in</button>`;
}
function signinBind(root) {
  const b = $('#sis', root);
  if (b) b.onclick = async () => {
    try { const r = await api('signin', { mode: $('#sim', root).value, password: $('#sip', root).value }); ME.signin = r.signin; $('#sip', root).value = ''; toast('Saved'); }
    catch (e) { fail(e); }
  };
}

VIEWS.account = async b => {
  b.innerHTML = `<div class="ut-window__main"><div class="form"><p>Signed in as <b>${esc(ME.user)}</b>.</p>
    ${field('op', 'Current password', '', 'type=password autocomplete=current-password')}${field('np1', 'New password', '', 'type=password autocomplete=new-password')}${field('np2', 'Repeat', '', 'type=password autocomplete=new-password')}
    <button class="ut-btn ut-btn--primary" id="pw">Change password</button> <button class="ut-btn" id="lo">Sign out</button>
    ${signinFields()}<div class="ut-section-title">Appearance</div>${appearanceFields()}</div></div>`;
  appearanceBind(b); signinBind(b);
  $('#pw', b).onclick = () => {
    if ($('#np1', b).value !== $('#np2', b).value) return fail(new Error('The passwords do not match.'));
    save('password', { old: $('#op', b).value, password: $('#np1', b).value });
  };
  $('#lo', b).onclick = async () => { await api('logout', {}); location.reload(); };
};

function powerDialog() {
  dialog({ kind: 'danger', title: 'Switch the NAS off?', body: `<p>All connections will be closed.</p>${sw('rb', false, 'Restart instead')}`, ok: 'Run', okCls: 'ut-btn--danger',
    onOk: async s => { const r = $('#rb', s).checked; await api('power', { action: r ? 'reboot' : 'poweroff' });
      $('#app').innerHTML = `<main class="ut-login"><div class="ut-login__card"><h2>${r ? 'Restart' : 'Switch off'}</h2><p>${r ? 'The NAS is restarting. Reload this page in a few minutes.' : 'The NAS is switching off.'}</p></div></main>`; } });
}

boot().catch(e => { document.body.textContent = 'Untrash Desk: ' + e.message; });


/* status: load, memory, temperatures, network (2 s poll while open) ------ */
const ring = (v, max, label, unit, warn, crit) => {
  const pct = Math.max(0, Math.min(1, (v || 0) / max)), C = 2 * Math.PI * 34;
  const cls = v >= crit ? 'crit' : v >= warn ? 'warn' : 'ok';
  return `<figure class="ut-ring ut-ring--${cls}"><svg viewBox="0 0 80 80"><circle class="bg" cx="40" cy="40" r="34"/>
    <circle class="fg" cx="40" cy="40" r="34" style="stroke-dasharray:${C};stroke-dashoffset:${C * (1 - pct)}"/></svg>
    <figcaption><b>${v == null ? '–' : Math.round(v)}</b><small>${unit}</small><span>${esc(label)}</span></figcaption></figure>`;
};
const rate = b => b > 1048576 ? (b / 1048576).toFixed(1) + ' MB/s' : b > 1024 ? (b / 1024).toFixed(0) + ' kB/s' : b + ' B/s';
const NETH = {};
VIEWS.status = async b => {
  const draw = async () => {
    if (!wins.status) return;
    const L = await api('live'), m = L.mem, used = m.total - m.avail;
    const hours = Math.floor(L.uptime / 3600), days = Math.floor(hours / 24);
    let net = '';
    for (const [n, v] of Object.entries(L.net)) {
      const h = NETH[n] = (NETH[n] || []).concat(v.rx_bps + v.tx_bps).slice(-40), mx = Math.max(...h, 1);
      net += `<div class="ut-net"><div class="row"><b>${esc(n)}</b><span class="ut-spacer"></span><span>↓ ${rate(v.rx_bps)}</span><span>↑ ${rate(v.tx_bps)}</span></div>
        <svg viewBox="0 0 120 24" preserveAspectRatio="none"><polyline points="${h.map((x, i) => `${i * 3},${24 - 22 * x / mx}`).join(' ')}"/></svg></div>`;
    }
    const disks = Object.entries(L.disks).map(([d, t]) => `<span class="ut-pill ${t == null ? '' : t >= 50 ? 'ut-pill--warn' : 'ut-pill--ok'}">${esc(d)} ${t == null ? 'asleep' : t + ' °C'}</span>`).join(' ');
    const main = b.querySelector('#st-top');
    const html = `<div class="ut-rings">${ring(L.cpu.total, 100, 'CPU', '%', 70, 90)}${L.cpu.cores.map((c, i) => ring(c, 100, 'Core ' + (i + 1), '%', 70, 90)).join('')}
        ${ring(100 * used / m.total, 100, 'RAM ' + size(used), '%', 80, 92)}${ring(L.board.temp_c, 80, 'Case' + (L.board.stale ? ' (old)' : ''), '°C', 55, 68)}</div>
      <div class="ut-section-title">Disks</div><div class="row" style="flex-wrap:wrap;gap:6px">${disks || '<span class="muted">none</span>'}</div>
      <div class="ut-section-title">Network</div>${net}
      <p class="muted">Load ${L.load.join(' · ')} · Fan level ${L.board.level ?? '–'} · up for ${days ? days + ' d ' : ''}${hours % 24} h · swap ${size(m.swap_total - m.swap_free)} / ${size(m.swap_total)}</p>`;
    if (main) main.innerHTML = html;
    else {
      b.innerHTML = `<div class="ut-window__main ut-status"><div id="st-top">${html}</div>
        <div class="row ut-procs__head"><div class="ut-section-title">Processes</div><span class="ut-spacer"></span>
          <input class="ut-input ut-procs__filter" id="psf" type="search" placeholder="${esc(UTI18N.tr('Filter by name, user or command'))}" aria-label="Filter">
          ${sw('psk', PROCS.kernel, 'Kernel threads')}</div>
        <div class="ut-table-wrap"><table class="ut-table ut-procs"><thead><tr>
          ${[['name', 'Name'], ['pid', 'PID'], ['user', 'User'], ['cpu', 'CPU'], ['rss', 'Memory']].map(([k, n]) => `<th${k === 'pid' || k === 'cpu' || k === 'rss' ? ' class="num"' : ''}><button class="ut-th" data-ps="${k}">${esc(UTI18N.tr(n))}</button></th>`).join('')}
          <th>Command</th><th></th></tr></thead><tbody id="pst"></tbody></table></div>
        <p class="muted" id="psn"></p></div>`;
      $('#psf', b).oninput = e => { PROCS.filter = e.target.value; procDraw(b); };
      $('#psk', b).onchange = e => { PROCS.kernel = e.target.checked; procDraw(b); };
      $$('[data-ps]', b).forEach(x => x.onclick = () => { PROCS.dir = PROCS.sort === x.dataset.ps ? -PROCS.dir : (x.dataset.ps === 'name' || x.dataset.ps === 'user' ? 1 : -1); PROCS.sort = x.dataset.ps; procDraw(b); });
      $('#pst', b).onclick = e => {
        const btn = e.target.closest('[data-pk]'); if (!btn) return;
        const p = PROCS.list.find(x => x.pid === +btn.dataset.pk); if (!p) return;
        const hard = btn.dataset.sig === 'KILL';
        dialog({ kind: 'danger', title: hard ? 'Kill the process?' : 'End the process?', ok: hard ? 'Kill' : 'End', okCls: 'ut-btn--danger',
          body: `<p><b translate="no">${esc(p.name)}</b> (PID ${p.pid}, ${esc(p.user)})</p><p class="ut-faint mono" translate="no">${esc(p.cmd)}</p>
            <p>${esc(UTI18N.tr(hard ? 'It stops at once, without saving anything.' : 'It is asked to end (TERM). System services may be started again automatically.'))}</p>`,
          onOk: async () => { await api('processes/kill', { pid: p.pid, start: p.start, signal: hard ? 'KILL' : 'TERM' }); toast(UTI18N.tr(hard ? 'Killed' : 'Ended'), p.name); setTimeout(() => procs(b), 600); } });
      };
    }
    await procs(b);
  };
  await draw();
  const d1 = single(draw), t = setInterval(() => d1().catch(() => { }), 2000);
  CLEANUP.status = () => clearInterval(t);
};
const PROCS = { list: [], self: 0, sort: 'cpu', dir: -1, filter: '', kernel: false };
async function procs(b) {
  try { const r = await apiRaw('processes'); PROCS.list = r.processes; PROCS.self = r.self; } catch (e) { return; }
  procDraw(b);
}
function procDraw(b) {
  const tb = $('#pst', b); if (!tb) return;
  const f = PROCS.filter.toLowerCase(), k = PROCS.sort;
  const list = PROCS.list.filter(p => (PROCS.kernel || !p.kernel) && (!f || (p.name + ' ' + p.user + ' ' + p.cmd + ' ' + p.pid).toLowerCase().includes(f)))
    .sort((a, c) => { const x = a[k] ?? -1, y = c[k] ?? -1; return PROCS.dir * (typeof x === 'string' ? x.localeCompare(y) : x - y) || a.pid - c.pid; });
  const shown = list.slice(0, 200);
  tb.innerHTML = shown.map(p => {
    const locked = p.kernel || p.pid <= 2 || p.pid === PROCS.self;
    return `<tr><td translate="no"><b>${esc(p.name)}</b></td><td class="num">${p.pid}</td><td translate="no">${esc(p.user)}</td>
      <td class="num">${p.cpu == null ? '–' : p.cpu.toFixed(1) + ' %'}</td><td class="num">${p.rss ? size(p.rss) : '–'}</td>
      <td class="ut-procs__cmd mono" translate="no" title="${esc(p.cmd)}">${esc(p.cmd)}</td>
      <td class="ut-rowbtns">${locked ? '' : `<button class="ut-btn ut-btn--sm ut-btn--ghost" data-pk="${p.pid}" data-sig="TERM">End</button><button class="ut-btn ut-btn--sm ut-btn--ghost ut-btn--danger" data-pk="${p.pid}" data-sig="KILL">Kill</button>`}</td></tr>`;
  }).join('');
  $$('[data-ps]', b).forEach(x => { x.dataset.on = x.dataset.ps === k ? (PROCS.dir > 0 ? '▲' : '▼') : ''; });
  const n = $('#psn', b); if (n) n.textContent = UTI18N.tr('%s processes').replace('%s', list.length) + (list.length > shown.length ? ' · ' + UTI18N.tr('the first 200 shown') : '');
}

/* terminal: xterm.js over a WebSocket to a login shell (admins; sudo for root) */
const loadOnce = (tag, attrs) => new Promise((ok, bad) => {
  const key = attrs.src || attrs.href; if (document.querySelector(`[data-once="${key}"]`)) return ok();
  const e = Object.assign(document.createElement(tag), attrs); e.dataset.once = key; e.onload = ok; e.onerror = bad; document.head.append(e);
});
VIEWS.terminal = async b => {
  await loadOnce('link', { rel: 'stylesheet', href: '/desk/vendor/xterm/xterm.css' });
  await loadOnce('script', { src: '/desk/vendor/xterm/xterm.js' });
  await loadOnce('script', { src: '/desk/vendor/xterm/xterm-addon-fit.js' });
  b.innerHTML = '<div class="ut-term"></div>';
  const term = new Terminal({ cursorBlink: true, fontSize: 13, fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
    theme: { background: '#0b1418', foreground: '#d8e6ea', cursor: '#05c7af' } });
  const fit = new FitAddon.FitAddon(); term.loadAddon(fit); term.open(b.querySelector('.ut-term')); fit.fit();
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/term');
  ws.binaryType = 'arraybuffer';
  const send = o => ws.readyState === 1 && ws.send(JSON.stringify(o));
  ws.onopen = () => { send({ t: 'r', c: term.cols, r: term.rows }); term.focus(); };
  ws.onmessage = e => term.write(new Uint8Array(e.data));
  ws.onclose = () => term.write('\r\n\x1b[33m' + UTI18N.tr('[Connection closed – reopen the window for a new session]') + '\x1b[0m\r\n');
  term.onData(d => send({ t: 'i', d }));
  term.onResize(({ cols, rows }) => send({ t: 'r', c: cols, r: rows }));
  const ro = new ResizeObserver(() => { try { fit.fit(); } catch (e) { } }); ro.observe(b);
  CLEANUP.terminal = () => { ro.disconnect(); ws.close(); term.dispose(); };
};

/* UntrashMesh: members, invitations (untrash-mesh) ------------------------ */
/* user manual (docs/user-guide, English; also readable without signing in) */
VIEWS.manual = async b => {
  b.innerHTML = `<div class="ut-window__main ut-manual"><div class="row ut-manual__bar"><span class="muted">User guide (English)</span><span class="ut-spacer"></span>
    <a class="ut-btn ut-btn--sm" href="/manual/" target="_blank" rel="noopener">Open in a new tab</a>
    <a class="ut-btn ut-btn--sm ut-btn--primary" href="/manual/UntrashOS-User-Guide.pdf" download>Download PDF</a></div>
    <iframe src="/manual/" title="User guide"></iframe></div>`;
};
const MIRROR_ENDED = ['stopped', 'partner-stopped', 'declined'];
const memberName = (m, node) => (m.members.find(x => x.node === node) || {}).name || node.slice(0, 8);
/* DRBD state as words: live = {cs, role, ds, sync} from untrash-mesh */
function mirrorState(o) {
  const l = o.live || {}, ds = String(l.ds || ''), t = s => esc(UTI18N.tr(s));
  if (o.state === 'requested') return ['', t("waiting for the partner's consent")];
  if (o.state === 'declined') return ['ut-pill--danger', t('declined by the partner')];
  if (o.state === 'partner-stopped') return ['ut-pill--danger', t('ended by the partner')];
  if (o.state === 'stopping' || o.state === 'stopped') return ['', t('ends at the next restart')];
  if (o.bypassed) return ['ut-pill--warn', t('needs a full resync')];
  if (!l.cs || l.cs === 'Unconfigured') return ['', t('starts at the next restart')];
  if (/^Sync|^PausedSync/.test(l.cs)) return ['ut-pill--warn', t('copying') + (l.sync != null ? ' ' + l.sync.toFixed(1) + ' %' : '')];
  if (l.cs === 'Ahead' || l.cs === 'Behind') return ['ut-pill--warn', t('catching up')];
  if (l.cs === 'Connected' && /^UpToDate\/UpToDate$|^UpToDate$/.test(ds)) return ['ut-pill--ok', t('in sync')];
  if (l.cs === 'Connected') return ['ut-pill--warn', esc(ds)];
  return ['ut-pill--warn', t('partner not reachable, changes are kept')];
}
function copyState(c) {
  const l = c.live || {}, t = s => esc(UTI18N.tr(s));
  if (c.state === 'pending') return ['ut-pill--warn', t('asks for your consent')];
  if (/^Sync/.test(l.cs || '')) return ['ut-pill--warn', t('receiving') + (l.sync != null ? ' ' + l.sync.toFixed(1) + ' %' : '')];
  if (l.cs === 'Connected') return ['ut-pill--ok', t('in sync')];
  return ['', t('waiting for the owner')];
}
function mirrorRows(m) {
  const outs = (m.mirrors || []).map(o => { const [cls, txt] = mirrorState(o);
    return `<tr><td><b translate="no">${esc(o.label)}</b> → <span translate="no">${esc(memberName(m, o.peer))}</span><div class="ut-faint mono" translate="no">${esc(o.vol)} · ${gb(o.size)}</div>${o.error ? `<div class="ut-faint">${esc(o.error)}</div>` : ''}</td>
      <td><span class="ut-pill ${cls}">${txt}</span></td>
      <td class="ut-rowbtns">${MIRROR_ENDED.includes(o.state) || o.state === 'stopping' ? '' : `<button class="ut-btn ut-btn--sm ut-btn--ghost" data-mmstop="${esc(o.id)}" data-side="out">End</button>`}</td></tr>`; });
  const ins = (m.mirror_copies || []).map(c => { const [cls, txt] = copyState(c);
    return `<tr><td><span class="ut-faint">${esc(UTI18N.tr('Copy for'))}</span> <b translate="no">${esc(memberName(m, c.from))}</b>: <span translate="no">${esc(c.label)}</span><div class="ut-faint mono" translate="no">${c.vol ? esc(c.vol) + ' · ' : ''}${gb(c.size)}</div></td>
      <td><span class="ut-pill ${cls}">${txt}</span></td>
      <td class="ut-rowbtns">${c.state === 'pending' ? `<button class="ut-btn ut-btn--sm ut-btn--primary" data-mmacc="${esc(c.id)}">Agree…</button> <button class="ut-btn ut-btn--sm ut-btn--ghost" data-mmdec="${esc(c.id)}">Decline</button>`
        : `<button class="ut-btn ut-btn--sm ut-btn--ghost" data-mmstop="${esc(c.id)}" data-side="in">End</button>`}</td></tr>`; });
  return outs.length || ins.length ? `<div class="ut-table-wrap"><table class="ut-table"><tbody>${outs.join('')}${ins.join('')}</tbody></table></div>`
    : '<p class="ut-faint">A member can keep a complete copy of a volume of this NAS, so its data survives a fire or a theft here.</p>';
}

VIEWS.mesh = async b => {
  const m = await api('mesh'), ago = t => t ? esc(new Date(t * 1000).toLocaleString(UTI18N.locale)) : '–';
  const me = `<div class="ut-card"><div class="ut-card__head"><h3>This NAS</h3><span class="ut-spacer"></span>
      <button class="ut-btn ut-btn--sm ut-btn--ghost" id="mren">Rename</button></div>
    <p><b translate="no">${esc(m.name)}</b>${m.address ? ` · <span class="mono" translate="no">${esc(m.address)}</span> · <span class="mono" translate="no">${esc(m.name)}.mesh</span>` : ''}</p>
    <p class="ut-faint">Key fingerprint <span class="mono" translate="no">${esc(m.node)}</span></p></div>`;
  if (!m.mesh) {
    b.innerHTML = `<div class="ut-window__main ut-mesh"><img src="${ICON('mesh')}" alt="" class="ut-mesh__logo"><h2>UntrashMesh</h2>
      <p>Several UntrashOS devices form one encrypted network (WireGuard), at home and over the internet, without a cloud provider and without a fixed IP address: every device keeps an address book that the others update when their address changes.</p>
      ${me}
      <div class="ut-card"><h3>Start a mesh</h3>${field('mnew', 'Name of the mesh', 'home')}<button class="ut-btn ut-btn--primary" id="mcreate">Create the mesh</button></div>
      <div class="ut-card"><h3>Join a mesh</h3><p class="ut-faint">Paste the invitation an admin of the mesh created on their device.</p>
        <textarea class="ut-textarea" id="minv" rows="3" placeholder="Invitation" translate="no"></textarea>
        <button class="ut-btn ut-btn--primary" id="mjoin" style="margin-top:8px">Join</button></div>
      <p class="ut-faint">The UntrashApp is paired over UntrashMesh as well: create a mesh first, then choose Pair the UntrashApp.</p></div>`;
    $('#mcreate', b).onclick = () => save('mesh/create', { name: $('#mnew', b).value }, 'mesh');
    $('#mjoin', b).onclick = () => save('mesh/join', { invitation: $('#minv', b).value }, 'mesh');
  } else {
    const rows = m.members.map(x => `<tr><td><b translate="no">${esc(x.name)}</b>${x.self ? ' <span class="ut-pill ut-pill--plain">' + esc(UTI18N.tr('this NAS')) + '</span>' : ''}
        <div class="ut-faint mono" translate="no">${esc(x.name)}.mesh · ${esc(x.address)}</div></td>
      <td>${x.role === 'admin' ? 'Admin' : 'Member'} · ${x.kind === 'app' ? 'App' : 'NAS'}${x.kind === 'app' ? `<div class="ut-faint">${x.user ? esc(UTI18N.tr('signs in as %s').replace('%s', x.user)) : esc(UTI18N.tr('not linked to a user'))}</div>` : ''}</td>
      <td><span class="ut-pill ${x.online ? 'ut-pill--ok' : ''}">${x.online ? 'online' : 'not reachable'}</span>
        <div class="ut-faint" translate="no">${esc(x.endpoint || (x.endpoints || [])[0] || '')}</div></td>
      <td class="ut-faint">${x.self ? '' : ago(x.handshake || x.seen)}</td>
      <td class="ut-rowbtns">${x.kind === 'app' ? `<button class="ut-btn ut-btn--sm" data-mlink="${esc(x.node)}" data-mname="${esc(x.name)}" data-muser="${esc(x.user || '')}">Link…</button>`
        : !x.self ? `<button class="ut-btn ut-btn--sm" data-mshare="${esc(x.node)}" data-mname="${esc(x.name)}">Share…</button>` : ''}${m.admin && !x.self ? ` <button class="ut-btn ut-btn--sm ut-btn--ghost" data-mrm="${esc(x.node)}" data-mname="${esc(x.name)}">Remove</button>` : ''}
        ${(m.offers || {})[x.node] && Object.keys(m.offers[x.node]).length ? `<div class="ut-faint" translate="no">${esc(Object.entries(m.offers[x.node]).map(([k, v]) => k + (v === 'ro' ? ' (r)' : ' (rw)')).join(', '))}</div>` : ''}</td></tr>`).join('');
    const pvs = (m.partner_volumes || []).map(v => `<tr><td><b translate="no">${esc(v.share)}</b> <span class="ut-faint">@ <span translate="no">${esc(v.partner)}</span></span><div class="ut-faint mono" translate="no">${esc(v.path)}</div></td>
      <td>${v.mode === 'ro' ? esc(UTI18N.tr('read only')) : esc(UTI18N.tr('read/write'))}</td>
      <td><span class="ut-pill ${v.mounted ? 'ut-pill--ok' : ''}">${v.mounted ? esc(UTI18N.tr('mounted')) : esc(UTI18N.tr('partner not reachable'))}</span></td>
      <td class="ut-faint">${v.mounted ? gb(v.free) + ' ' + esc(UTI18N.tr('free')) : ''}</td></tr>`).join('');
    b.innerHTML = `<div class="ut-window__main ut-mesh"><div class="row"><img src="${ICON('mesh')}" alt="" style="width:40px;height:40px"><h2 style="margin:0">UntrashMesh <span translate="no">${esc(m.mesh.name)}</span></h2>
        <span class="ut-spacer"></span><button class="ut-btn" id="mpair">Pair the UntrashApp</button>${m.admin ? ' <button class="ut-btn ut-btn--primary" id="minvite">Invite a device</button>' : ''}</div>
      ${me}
      <div class="ut-section-title">Members</div>
      <div class="ut-table-wrap"><table class="ut-table"><thead><tr><th>Name</th><th>Role</th><th>State</th><th>Last contact</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <div class="row ut-section-title"><span>Off-site mirrors</span><span class="ut-spacer"></span>${m.members.length > 1 ? '<button class="ut-btn ut-btn--sm" id="mmirror">Mirror a volume…</button>' : ''}</div>
      ${mirrorRows(m)}
      <div class="ut-section-title">Partner volumes</div>
      ${pvs ? `<div class="ut-table-wrap"><table class="ut-table"><tbody>${pvs}</tbody></table></div><p class="ut-faint">Partner volumes appear under Storage; under Shares you can make shares on them for your own users.</p>`
        : '<p class="ut-faint">No member shares anything with this NAS yet. A member offers shares with Share… in its own Desk.</p>'}
      <p class="ut-faint">Members reach each other at <span class="mono">name.mesh</span>, for example shares at <span class="mono" translate="no">\\\\${esc(m.members.find(x => !x.self)?.name || 'nas')}.mesh</span>, the Desk at <span class="mono" translate="no">http://${esc(m.members.find(x => !x.self)?.name || 'nas')}.mesh</span>. Over the internet the router needs UPnP or a forwarding of UDP port 51820 on at least one side.</p>
      <div class="row" style="margin-top:12px"><button class="ut-btn ut-btn--ghost ut-btn--danger" id="mleave">Leave the mesh</button></div></div>`;
    const inv = $('#minvite', b);
    if (inv) inv.onclick = async () => {
      try {
        const r = await api('mesh/invite', { hours: 24 });
        const d = dialog({ title: 'Invite a device', ok: 'Done', body: `<p>On the other UntrashOS device (or in the UntrashApp) open UntrashMesh, choose <b>Join</b> and paste this invitation. It works once, until ${ago(r.expires)}.</p>
          <textarea class="ut-textarea mono" rows="5" readonly translate="no" id="minvt">${esc(r.invitation)}</textarea>
          <div class="row" style="margin-top:8px"><button class="ut-btn ut-btn--sm" id="mcopy">Copy</button></div>` });
        $('#mcopy', d).onclick = () => { $('#minvt', d).select(); navigator.clipboard ? navigator.clipboard.writeText(r.invitation).then(() => toast('Copied', '')) : document.execCommand('copy'); };
      } catch (e) { fail(e); }
    };
    const userSel = async (id, cur, none) => `<select class="ut-select" id="${id}">${none ? `<option value="">${esc(UTI18N.tr('not linked'))}</option>` : ''}${(await api('users')).users
      .filter(u => u.name !== 'pc-guest').map(u => `<option value="${esc(u.name)}"${u.name === cur ? ' selected' : ''} translate="no">${esc(u.name)}</option>`).join('')}</select>`;
    $('#mpair', b).onclick = async () => {
      if (!m.admin) return toast('Only an admin of the mesh can pair', 'Pair the app on the NAS that created the mesh, then link it to a user here.');
      dialog({ title: 'Pair the UntrashApp', ok: 'Show the code',
        body: `<p>The app joins UntrashMesh and signs in on this NAS as the user you choose. It can confirm sign-ins and actions of that user.</p>
          <div class="ut-field"><label for="mpu">Signs in as</label>${await userSel('mpu', ME.user)}</div>`,
        onOk: async d => {
          const r = await api('mesh/pair', { user: $('#mpu', d).value, hours: 1 });
          dialog({ title: 'Pair the UntrashApp', ok: 'Done', body: `<p>In the UntrashApp choose <b>Pair with a NAS</b> and scan this code. It works once, until ${ago(r.expires)}.</p>
            <div class="ut-qr">${UTQR.svg(r.invitation, 'M')}</div>
            <details><summary>Show as text</summary><textarea class="ut-textarea mono" rows="4" readonly translate="no">${esc(r.invitation)}</textarea></details>`, onOk: () => render('mesh') });
        } });
    };
    $$('[data-mlink]', b).forEach(x => x.onclick = async () => dialog({ title: UTI18N.tr('Link %s').replace('%s', x.dataset.mname), ok: 'Save',
      body: `<p>The Desk user this app signs in as on this NAS. Without a link the app is only a mesh member here.</p><div class="ut-field"><label for="mlu">Signs in as</label>${await userSel('mlu', x.dataset.muser, true)}</div>`,
      onOk: d => save('mesh/app-link', { node: x.dataset.mlink, user: $('#mlu', d).value }, 'mesh') }));
    $$('[data-mshare]', b).forEach(x => x.onclick = async () => {
      const sh = (await api('shares')).shares.filter(s => s.enabled && s.present && !s.path.startsWith('/p-data/'));
      const cur = (m.offers || {})[x.dataset.mshare] || {};
      const d = dialog({ title: UTI18N.tr('Share with %s').replace('%s', x.dataset.mname), ok: 'Save',
        body: `<p>Shares this NAS offers to <b translate="no">${esc(x.dataset.mname)}</b>. They appear there as partner volumes; only over UntrashMesh.</p>
          <div class="ut-table-wrap"><table class="ut-table"><tbody>${sh.map(s => `<tr><td translate="no">${esc(s.name)}</td><td><select class="ut-select ut-select--sm" data-msh="${esc(s.name)}">
            ${[['', 'not shared'], ['ro', 'read only'], ['rw', 'read/write']].map(([k, n]) => `<option value="${k}"${(cur[s.name] || '') === k ? ' selected' : ''}>${esc(UTI18N.tr(n))}</option>`).join('')}</select></td></tr>`).join('')}</tbody></table></div>`,
        onOk: async dd => { const shares = {}; $$('[data-msh]', dd).forEach(e => { if (e.value) shares[e.dataset.msh] = e.value; });
          await api('mesh/share', { node: x.dataset.mshare, shares }); render('mesh'); } });
    });
    const mm = $('#mmirror', b);
    if (mm) mm.onclick = async () => {
      const vols = (await api('storage')).volumes.filter(v => v.kind === 'intern' && !v.host && !(m.mirrors || []).some(o => o.vol === v.path && !MIRROR_ENDED.includes(o.state)));
      if (!vols.length) return toast('No volume to mirror', 'Every data volume is mirrored already, or only the volume of the running system is left.');
      dialog({ title: 'Mirror a volume', ok: 'Ask the partner',
        body: `<p>A member keeps a complete copy of the volume (RAID 1 over UntrashMesh). Its admin must agree and choose where the copy goes; it needs as much free space as the volume is large.</p>
          <label class="ut-field"><span class="ut-label">Volume</span><select class="ut-select" id="mmv">${vols.map(v => `<option value="${esc(v.id)}" translate="no">${esc(v.label)} (${gb(v.size)})</option>`).join('')}</select></label>
          <label class="ut-field"><span class="ut-label">Partner</span><select class="ut-select" id="mmn">${m.members.filter(x => !x.self && x.kind !== 'app').map(x => `<option value="${esc(x.node)}" translate="no">${esc(x.name)}</option>`).join('')}</select></label>
          <p class="ut-faint">The mirror starts with the next restart of this NAS. Writes go to the volume first and to the partner as fast as the line allows; while the partner is not reachable, the changes are kept and sent later. The volume of the running system cannot be mirrored.</p>`,
        onOk: d => save('mesh/mirror-start', { volume: $('#mmv', d).value, node: $('#mmn', d).value }, 'mesh') });
    };
    $$('[data-mmacc]', b).forEach(x => x.onclick = async () => {
      const c = (m.mirror_copies || []).find(c => c.id === x.dataset.mmacc);
      const vols = (await api('storage')).volumes.filter(v => v.kind === 'intern' && v.free > c.size);
      if (!vols.length) return toast('Not enough space', UTI18N.tr('No volume has %s free.').replace('%s', gb(c.size)));
      dialog({ title: 'Keep a mirror copy', ok: 'Agree',
        body: `<p><b translate="no">${esc(memberName(m, c.from))}</b> asks this NAS to keep a copy of its volume <b translate="no">${esc(c.label)}</b> (${gb(c.size)}). The copy is a file that grows as it fills; it does not appear here as a volume or share. It is not encrypted: anyone with administrator access to this NAS could read it.</p>
          <label class="ut-field"><span class="ut-label">Keep it on</span><select class="ut-select" id="mmt">${vols.map(v => `<option value="${esc(v.id)}" translate="no">${esc(v.label)} (${gb(v.free)} ${esc(UTI18N.tr('free'))})</option>`).join('')}</select></label>`,
        onOk: d => save('mesh/mirror-accept', { id: c.id, volume: $('#mmt', d).value }, 'mesh') });
    });
    $$('[data-mmdec]', b).forEach(x => x.onclick = () => save('mesh/mirror-decline', { id: x.dataset.mmdec }, 'mesh'));
    $$('[data-mmstop]', b).forEach(x => x.onclick = () => dialog({ kind: 'danger', title: 'End the mirror?', ok: 'End the mirror', okCls: 'ut-btn--danger',
      body: x.dataset.side === 'out' ? '<p>The volume stays as it is; from the next restart on it is mounted without the mirror. The partner deletes its copy.</p>'
        : '<p>The copy on this NAS is deleted. The owner keeps its volume and is told that the mirror ended.</p>',
      onOk: () => save('mesh/mirror-stop', { id: x.dataset.mmstop }, 'mesh') }));
    $$('[data-mrm]', b).forEach(x => x.onclick = () => dialog({ kind: 'danger', title: UTI18N.tr('Remove %s from the mesh?').replace('%s', x.dataset.mname), ok: 'Remove', okCls: 'ut-btn--danger',
      body: '<p>It loses its connection to every member. To come back it needs a new invitation.</p>', onOk: () => save('mesh/remove', { node: x.dataset.mrm }, 'mesh') }));
    $('#mleave', b).onclick = () => dialog({ kind: 'danger', title: 'Leave the mesh?', ok: 'Leave', okCls: 'ut-btn--danger',
      body: '<p>The connections to all members end. To come back this NAS needs a new invitation.</p>', onOk: () => save('mesh/leave', {}, 'mesh') });
  }
  $('#mren', b).onclick = () => {
    dialog({ title: 'Name in the mesh', ok: 'Save', body: field('mrn', 'Name (letters, digits, -)', m.name),
      onOk: d => save('mesh/rename', { name: $('#mrn', d).value }, 'mesh') });
  };
};


/* player: music and video with a playlist of the folder; formats the browser
   cannot play are remuxed on the NAS (video copied, sound to AAC) ---------- */
const PL = { list: [], i: 0, share: '', probe: null, off: 0 };
const fmtT = t => { t = Math.max(0, Math.floor(t || 0)); const h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60, x = t % 60;
  return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(x).padStart(2, '0'); };
function openPlayer(names, cur, rel) {
  PL.list = names.map(n => ({ name: n, path: rel(n) })); PL.share = FS.share;
  PL.i = Math.max(0, names.indexOf(cur));
  if (wins.player) { wins.player.hidden = false; focusWin(wins.player); plLoad(); } else openApp('player');
}
const plUrl = (what, extra) => '/api/files/' + what + '?' + new URLSearchParams(Object.assign({ share: PL.share, path: PL.list[PL.i].path }, extra || {}));
async function plLoad(t = 0) {
  const b = body('player'); if (!b) return;
  const v = $('#pv', b), it = PL.list[PL.i];
  $$('.ut-pl__item', b).forEach((x, i) => x.toggleAttribute('aria-current', i === PL.i));
  $('#pt', b).textContent = it.name; $('#pn', b).textContent = '';
  let p = PL.probe;
  if (!t || !p || p.path !== it.path) { p = PL.probe = Object.assign(await api('files/probe?' + new URLSearchParams({ share: PL.share, path: it.path })), { path: it.path }); }
  const a = $('#pa', b);
  a.innerHTML = p.audio.map(x => `<option value="${x.index}">${esc((x.lang || 'Tone') + ' · ' + x.codec + (x.channels ? ' ' + x.channels + 'ch' : '') + (x.title ? ' · ' + x.title : ''))}</option>`).join('');
  a.hidden = p.audio.length < 2;
  b.querySelector('.ut-pl').classList.toggle('ut-pl--audio', !p.video.length);
  const seek = $('#ps', b); seek.max = Math.ceil(p.duration || 0); seek.hidden = p.mode !== 'remux';
  if (p.mode === 'none') { v.removeAttribute('src'); v.load(); $('#pn', b).textContent = p.note; return; }
  PL.off = p.mode === 'remux' ? t : 0;
  v.src = p.mode === 'remux' ? plUrl('stream', { t: t.toFixed(1), a: a.value || '' }) : plUrl('download', { inline: '1' });
  if (p.mode === 'remux') $('#pn', b).textContent = 'Being converted on the NAS (picture unchanged, sound → AAC).';
  v.play().catch(() => { });
}
VIEWS.player = async b => {
  b.innerHTML = `<div class="ut-pl"><div class="ut-pl__main">
      <div class="ut-pl__stage"><video id="pv" controls playsinline poster="${ICON('player')}"></video></div>
      <div class="ut-pl__bar"><button class="ut-btn ut-btn--sm" id="pp" aria-label="Previous">⏮</button><button class="ut-btn ut-btn--sm" id="px" aria-label="Next">⏭</button>
        <b id="pt" class="ut-pl__title" translate="no"></b><select class="ut-select" id="pa" hidden aria-label="Audio track"></select></div>
      <input type="range" id="ps" min="0" value="0" step="1" hidden aria-label="Position"><div class="muted" id="pn"></div></div>
    <aside class="ut-pl__list" translate="no">${PL.list.map((x, i) => `<button class="ut-pl__item" data-i="${i}">${esc(x.name)}</button>`).join('')}</aside></div>`;
  const v = $('#pv', b), seek = $('#ps', b);
  $('#pp', b).onclick = () => { PL.i = (PL.i - 1 + PL.list.length) % PL.list.length; plLoad(); };
  $('#px', b).onclick = () => { PL.i = (PL.i + 1) % PL.list.length; plLoad(); };
  $$('.ut-pl__item', b).forEach(x => x.onclick = () => { PL.i = +x.dataset.i; plLoad(); });
  $('#pa', b).onchange = () => plLoad(PL.off + (v.currentTime || 0) || 0.01);
  v.onended = () => { if (PL.i + 1 < PL.list.length) { PL.i++; plLoad(); } };
  v.ontimeupdate = () => { if (!seek.hidden && !seek.matches(':active')) seek.value = PL.off + v.currentTime; };
  seek.onchange = () => plLoad(+seek.value || 0.01);
  CLEANUP.player = () => { v.pause(); v.removeAttribute('src'); v.load(); };
  await plLoad();
};

/* document reader: PDF (pdf.js, rendered here), text, Markdown ------------ */
const md = t => esc(t).replace(/^### (.*)$/gm, '<h4>$1</h4>').replace(/^## (.*)$/gm, '<h3>$1</h3>').replace(/^# (.*)$/gm, '<h2>$1</h2>')
  .replace(/^```[\s\S]*?^```/gm, m => '<pre>' + m.replace(/^```.*$/gm, '') + '</pre>')
  .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/(^|\W)\*(.+?)\*(?=\W|$)/g, '$1<i>$2</i>').replace(/`([^`]+)`/g, '<code>$1</code>')
  .replace(/^[-*] (.*)$/gm, '<li>$1</li>').replace(/\n{2,}/g, '<p></p>');
async function docViewer(name, path, size) {
  const url = '/api/files/download?' + new URLSearchParams({ share: FS.share, path });
  const s = document.createElement('div'); s.className = 'ut-scrim';
  s.innerHTML = `<div class="ut-dialog ut-doc"><div class="ut-dialog__head"><h2 translate="no">${esc(name)}</h2></div><div class="ut-dialog__body ut-doc__body"><span class="ut-spinner"></span></div>
    <div class="ut-dialog__foot"><span class="ut-faint" id="dp"></span><span class="ut-spacer"></span><span id="dctl"></span><a class="ut-btn" href="${url}">Download</a><button class="ut-btn ut-btn--primary" data-x>Close</button></div></div>`;
  const close = () => { s.remove(); document.removeEventListener('keydown', key); };
  const key = e => { if (e.key === 'Escape') close(); };
  s.onclick = e => { if (e.target === s || e.target.closest('[data-x]')) close(); };
  document.addEventListener('keydown', key); document.body.append(s);
  const bd = $('.ut-doc__body', s);
  try {
    if (/\.pdf$/i.test(name)) {
      await loadOnce('script', { src: '/desk/vendor/pdfjs/pdf.min.js' });
      pdfjsLib.GlobalWorkerOptions.workerSrc = '/desk/vendor/pdfjs/pdf.worker.min.js';
      const doc = await pdfjsLib.getDocument({ url, isEvalSupported: false }).promise;
      let pg = 1, zoom = 1.25;
      const draw = async () => {
        const page = await doc.getPage(pg), vp = page.getViewport({ scale: zoom * (devicePixelRatio || 1) });
        const c = document.createElement('canvas'); c.width = vp.width; c.height = vp.height; c.style.width = vp.width / (devicePixelRatio || 1) + 'px';
        await page.render({ canvasContext: c.getContext('2d'), viewport: vp }).promise;
        bd.replaceChildren(c); bd.scrollTop = 0; $('#dp', s).textContent = `Page ${pg} / ${doc.numPages}`;
      };
      $('#dctl', s).innerHTML = '<button class="ut-btn ut-btn--sm" data-p="-1">‹</button><button class="ut-btn ut-btn--sm" data-p="1">›</button><button class="ut-btn ut-btn--sm" data-z="-0.25">−</button><button class="ut-btn ut-btn--sm" data-z="0.25">+</button>';
      $$('[data-p]', s).forEach(x => x.onclick = () => { pg = Math.min(doc.numPages, Math.max(1, pg + +x.dataset.p)); draw(); });
      $$('[data-z]', s).forEach(x => x.onclick = () => { zoom = Math.min(4, Math.max(0.5, zoom + +x.dataset.z)); draw(); });
      document.addEventListener('keydown', e => { if (!s.isConnected) return; if (e.key === 'ArrowRight' || e.key === 'PageDown') $('[data-p="1"]', s).click(); if (e.key === 'ArrowLeft' || e.key === 'PageUp') $('[data-p="-1"]', s).click(); });
      await draw();
    } else {
      if (size > 4 * 1048576) { bd.innerHTML = '<p>The file is larger than 4 MB – please download it.</p>'; return; }
      const t = await (await fetch(url)).text();
      bd.innerHTML = /\.(md|markdown)$/i.test(name) ? `<div class="ut-md" translate="no">${md(t)}</div>` : `<pre class="ut-text" translate="no">${esc(t)}</pre>`;
      $('#dp', s).textContent = size ? size.toLocaleString(UTI18N.locale) + ' bytes' : '';
    }
  } catch (e) { bd.innerHTML = `<div class="ut-callout ut-callout--danger">${esc(e.message)}</div>`; }
}

/* sounds: the buzzer jingles in a timeline editor (sound-render.js): note
   blocks and motifs dragged onto a piano roll, lengths on a grid, patterns
   repeated like loops, modulation the buzzer can play; heard in the browser
   (square wave, the same rendering) or on the NAS ------------------------ */
const EV_NAMES = { boot: 'Start', shutdown: 'Shut down', error: 'Error', critical: 'Critical', success: 'Success', connect: 'Device connected', disconnect: 'Device disconnected', warning: 'Warning', standby: 'Standby' };
const MODS = [['none', 'None'], ['staccato', 'Staccato'], ['vibrato', 'Vibrato'], ['slide', 'Slide'], ['fall', 'Fall'], ['arp', 'Arpeggio']];
const MOD_SIGN = { staccato: '·', vibrato: '∿', slide: '↗', fall: '↘', arp: '⋯' };
const MOTIFS = [['chime', 'Chime'], ['rise', 'Rise'], ['fall', 'Fall'], ['alarm', 'Alarm'], ['trill', 'Trill'], ['beep', 'Beep']];
const ROW_H = 16;
const SND = { ev: 'boot', score: null, cur: 0, sel: -1, zoom: 0.24, oct: 5, loaded: null, st: null, ctx: null, stop: null, dirty: false };

/* the rendered notes in the browser: one square oscillator per tied run, like the buzzer */
function sndPreview(notes) {
  if (SND.stop) SND.stop();
  const ctx = SND.ctx = SND.ctx || new (window.AudioContext || window.webkitAudioContext)();
  let t = ctx.currentTime + 0.05, o = null, g = null;
  const nodes = [];
  notes.forEach(([hz, ms, tie], i) => {
    const d = ms / 1000;
    if (hz) {
      if (!o) {
        o = ctx.createOscillator(); g = ctx.createGain(); o.type = 'square';
        g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(0.08, t + 0.004);
        o.connect(g).connect(ctx.destination); o.start(t); nodes.push(o);
      }
      o.frequency.setValueAtTime(hz, t);
      if (!tie) { g.gain.setValueAtTime(0.08, t + d - 0.005); g.gain.linearRampToValueAtTime(0.0001, t + d); o.stop(t + d); o = null; }
    }
    t += d + (hz && !tie && notes[i + 1] && notes[i + 1][0] ? UTSOUND.GAP / 1000 : 0);
  });
  SND.stop = () => { nodes.forEach(x => { try { x.stop(); } catch (e) { } }); SND.stop = null; };
}

VIEWS.sound = async (b, sel) => {
  if (sel && sel !== SND.ev) { SND.ev = sel; SND.loaded = null; }
  const S = UTSOUND, st = SND.st = await api('sound'), user = (st.user || {})[SND.ev];
  if (SND.loaded !== SND.ev) {
    SND.score = user && user.score ? JSON.parse(JSON.stringify(user.score)) : S.fromNotes(user ? user.notes : st.builtin[SND.ev] || [], user ? user.tempo || 1 : 1);
    SND.cur = 0; SND.sel = -1; SND.loaded = SND.ev; SND.dirty = false;
  }
  const sc = SND.score;
  const side = sidebar('sound', [['#', 'Events']].concat(Object.keys(EV_NAMES).map(k => [k, EV_NAMES[k] + ((st.user || {})[k] ? ' ★' : '')])), SND.ev);
  const selBox = (id, list, cur) => `<select class="ut-select ut-select--sm" id="${id}">${list.map(([k, n]) => `<option value="${esc(k)}"${String(k) === String(cur) ? ' selected' : ''}>${esc(n)}</option>`).join('')}</select>`;
  b.innerHTML = side + `<div class="ut-window__main ut-snd">
    <div class="row"><h2 style="margin:0">${esc(EV_NAMES[SND.ev])}</h2><span class="ut-pill ${user ? 'ut-pill--ok' : ''}">${user ? 'own version' + (user.source ? ' · ' + esc(user.source) : '') : 'built-in'}</span>
      <span class="ut-spacer"></span><span class="muted" id="sinfo"></span></div>
    <div class="row ut-snd__bar">
      <button class="ut-btn ut-btn--sm" id="sweb">▶ In the browser</button><button class="ut-btn ut-btn--sm" id="snas">▶ On the NAS</button><button class="ut-btn ut-btn--sm" id="sstop" aria-label="Stop">■</button>
      <span class="ut-snd__sep"></span>
      <label>Tempo <input class="ut-input ut-input--sm" type="number" id="sbpm" min="40" max="300" value="${sc.bpm}" style="width:64px"> BPM</label>
      <label>Grid ${selBox('sgrid', [[8, '1/8'], [16, '1/16'], [32, '1/32']], sc.grid)}</label>
      <label>Key ${selBox('skey', S.KEYS.map(k => [k, k]), sc.key)} ${selBox('sscale', Object.keys(S.SCALES).map(k => [k, k]), sc.scale)}</label>
      <label>Zoom <input type="range" id="szoom" min="0.06" max="0.8" step="0.02" value="${SND.zoom}"></label></div>
    <div class="ut-snd__arr" id="sarr"></div>
    <div class="ut-snd__pal" id="spal"></div>
    <div class="ut-snd__roll" id="sroll" tabindex="0" aria-label="Timeline"></div>
    <div class="ut-snd__insp" id="sinsp"></div>
    <div class="row" style="gap:6px;flex-wrap:wrap"><button class="ut-btn ut-btn--primary" id="ssave">Save</button>
      <button class="ut-btn ut-btn--ghost" id="sreset" ${user ? '' : 'disabled'}>Back to built-in</button><span class="ut-spacer"></span>
      <label class="ut-btn ut-btn--ghost">Import sound set<input type="file" id="simp" accept=".json,application/json" hidden></label>
      <button class="ut-btn ut-btn--ghost" id="sexp">Export as sound set</button></div>
    <p class="muted">Drag notes or motifs from the palette onto the timeline, or click into it. Drag a block to move it, its right edge to change its length; double-click removes it.
      Keys: ← → move, ↑ ↓ pitch, Shift+← → length, Delete removes. The buzzer plays one tone at a time (square wave, 100–4000 Hz).</p></div>`;
  navBind(b, 'sound');
  const pat = () => sc.patterns[SND.cur];
  const step = () => S.stepMs(sc);
  const snap = ms => Math.max(0, Math.round(ms / step()) * step());
  const rows = () => S.rows(sc);
  const rowOf = hz => { const m = S.hz2midi(hz), r = rows(); let bi = 0; r.forEach((x, i) => { if (Math.abs(x - m) < Math.abs(r[bi] - m)) bi = i; }); return bi; };
  const free = (p, t, d, skip) => p.notes.every((n, i) => i === skip || n.t + n.d <= t + 0.5 || n.t >= t + d - 0.5);
  const nextStart = (p, t, skip) => Math.min(Infinity, ...p.notes.filter((n, i) => i !== skip && n.t >= t + 0.5).map(n => n.t));
  const changed = () => { SND.dirty = true; info(); };

  function info() {
    const r = S.render(sc), secs = S.total(r) / 1000, ok = S.fits(r);
    $('#sinfo', b).innerHTML = `${esc(UTI18N.tr('%s steps').replace('%s', r.length))} · ${secs.toFixed(1)} s${ok ? '' : ' · <b class="ut-snd__over">' + esc(UTI18N.tr('too long for the buzzer (60 s, 4000 tones)')) + '</b>'}${SND.dirty ? ' · ' + esc(UTI18N.tr('not saved')) : ''}`;
    $('#ssave', b).disabled = !ok;
  }

  function drawArr() {
    $('#sarr', b).innerHTML = `<span class="ut-snd__lbl">Arrangement</span>` + sc.arrangement.map((c, i) => `<span class="ut-snd__clip${c.p === SND.cur ? ' is-cur' : ''}" data-ci="${i}">
        <button class="ut-snd__clipname" data-cpick="${i}" translate="no">${esc(sc.patterns[c.p].name)}</button>
        <button data-cdec="${i}" aria-label="One repeat less">−</button><b translate="no">×${c.n}</b><button data-cinc="${i}" aria-label="One repeat more">+</button>
        ${i ? `<button data-cleft="${i}" aria-label="Earlier">◀</button>` : ''}${sc.arrangement.length > 1 ? `<button data-cdel="${i}" aria-label="Remove from the arrangement">✕</button>` : ''}</span>`).join('')
      + `<button class="ut-btn ut-btn--sm" id="snewp">+ Pattern</button><button class="ut-btn ut-btn--sm ut-btn--ghost" id="sdupp">Duplicate pattern</button>`;
    $$('[data-cpick]', b).forEach(x => x.onclick = () => { SND.cur = sc.arrangement[+x.dataset.cpick].p; SND.sel = -1; drawArr(); drawRoll(); drawInsp(); });
    $$('[data-cinc]', b).forEach(x => x.onclick = () => { const c = sc.arrangement[+x.dataset.cinc]; c.n = Math.min(32, c.n + 1); drawArr(); changed(); });
    $$('[data-cdec]', b).forEach(x => x.onclick = () => { const c = sc.arrangement[+x.dataset.cdec]; c.n = Math.max(1, c.n - 1); drawArr(); changed(); });
    $$('[data-cleft]', b).forEach(x => x.onclick = () => { const i = +x.dataset.cleft; [sc.arrangement[i - 1], sc.arrangement[i]] = [sc.arrangement[i], sc.arrangement[i - 1]]; drawArr(); changed(); });
    $$('[data-cdel]', b).forEach(x => x.onclick = () => { sc.arrangement.splice(+x.dataset.cdel, 1); drawArr(); changed(); });
    const nextName = () => String.fromCharCode(65 + sc.patterns.length % 26) + (sc.patterns.length >= 26 ? Math.floor(sc.patterns.length / 26) : '');
    $('#snewp', b).onclick = () => { sc.patterns.push({ name: nextName(), notes: [], len: 16 * step() }); sc.arrangement.push({ p: sc.patterns.length - 1, n: 1 }); SND.cur = sc.patterns.length - 1; SND.sel = -1; drawArr(); drawRoll(); drawInsp(); changed(); };
    $('#sdupp', b).onclick = () => { const c = JSON.parse(JSON.stringify(pat())); c.name = nextName(); sc.patterns.push(c); sc.arrangement.push({ p: sc.patterns.length - 1, n: 1 }); SND.cur = sc.patterns.length - 1; SND.sel = -1; drawArr(); drawRoll(); drawInsp(); changed(); };
  }

  function drawPal() {
    const r = rows().filter(m => Math.floor(m / 12) - 1 === SND.oct).reverse();
    $('#spal', b).innerHTML = `<span class="ut-snd__lbl">Notes</span><button class="ut-btn ut-btn--sm ut-btn--ghost" id="soctd" aria-label="Octave down">‹</button><b translate="no">${SND.oct}</b><button class="ut-btn ut-btn--sm ut-btn--ghost" id="soctu" aria-label="Octave up">›</button>`
      + r.map(m => `<span class="ut-snd__chip" draggable="true" data-drag="note:${m}" translate="no">${S.name(m)}</span>`).join('')
      + `<span class="ut-snd__lbl">Motifs</span>` + MOTIFS.map(([k, n]) => `<span class="ut-snd__chip ut-snd__chip--motif" draggable="true" data-drag="motif:${k}">${esc(n)}</span>`).join('');
    $('#soctd', b).onclick = () => { SND.oct = Math.max(2, SND.oct - 1); drawPal(); };
    $('#soctu', b).onclick = () => { SND.oct = Math.min(7, SND.oct + 1); drawPal(); };
    $$('[data-drag]', b).forEach(c => c.ondragstart = e => { e.dataTransfer.setData('text/plain', c.dataset.drag); e.dataTransfer.effectAllowed = 'copy'; });
  }

  function drawRoll() {
    const p = pat(), r = rows(), z = SND.zoom, len = Math.max(S.patLen(p), 16 * step()) + 8 * step(), w = Math.ceil(len * z);
    const beat = 60000 / sc.bpm, bar = beat * 4;
    const roll = $('#sroll', b), keep = roll.scrollTop, keepX = roll.scrollLeft;
    roll.innerHTML = `<div class="ut-snd__keys">${r.map(m => `<div class="${S.name(m).startsWith(sc.key) && S.name(m)[sc.key.length] !== '#' ? 'is-root' : ''}" translate="no">${S.name(m)}</div>`).join('')}</div>
      <div class="ut-snd__grid" id="sgridel" style="width:${w}px;height:${r.length * ROW_H}px;--step:${step() * z}px;--beat:${beat * z}px;--bar:${bar * z}px">
        ${p.notes.map((n, i) => `<div class="ut-snd__blk${i === SND.sel ? ' is-sel' : ''}${n.mod && n.mod.k !== 'none' ? ' has-mod' : ''}" data-i="${i}" style="left:${n.t * z}px;width:${Math.max(4, n.d * z)}px;top:${rowOf(n.hz) * ROW_H}px" title="${S.name(Math.round(S.hz2midi(n.hz)))} · ${Math.round(n.d)} ms">
          <span translate="no">${S.name(Math.round(S.hz2midi(n.hz)))}${n.mod && MOD_SIGN[n.mod.k] ? ' ' + MOD_SIGN[n.mod.k] : ''}</span><i class="ut-snd__rz"></i></div>`).join('')}
        <div class="ut-snd__end" id="send" style="left:${S.patLen(p) * z}px" title="${esc(UTI18N.tr('End of the pattern (drag)'))}"></div>
      </div>`;
    roll.scrollTop = keep || (p.notes.length ? Math.max(0, rowOf(p.notes[0].hz) * ROW_H - 100) : rows().indexOf(72) * ROW_H - 100);
    roll.scrollLeft = keepX;
    bindRoll();
  }

  function drawInsp() {
    const p = pat(), n = p.notes[SND.sel];
    if (!n) { $('#sinsp', b).innerHTML = `<span class="muted">Pattern <b translate="no">${esc(p.name)}</b> · ${esc(UTI18N.tr('length %s ms').replace('%s', Math.round(S.patLen(p))))} · ${esc(UTI18N.tr('select a block to set its modulation'))}</span>`; return; }
    const m = n.mod || { k: 'none' }, r = rows();
    const rng = (id, label, v, min, max, stp) => `<label>${esc(label)} <input type="range" id="${id}" min="${min}" max="${max}" step="${stp}" value="${v}"> <b id="${id}v">${v}</b></label>`;
    $('#sinsp', b).innerHTML = `<label>Note <select class="ut-select ut-select--sm" id="inote" translate="no">${r.map(x => `<option value="${x}"${x === r[rowOf(n.hz)] ? ' selected' : ''}>${S.name(x)}</option>`).join('')}</select></label>
      <label>Length <input class="ut-input ut-input--sm" type="number" id="ilen" min="1" max="64" value="${Math.max(1, Math.round(n.d / step()))}" style="width:56px"> × ${sc.grid === 8 ? '1/8' : sc.grid === 32 ? '1/32' : '1/16'}</label>
      <label>Modulation ${selBox('imod', MODS, m.k)}</label>
      ${m.k === 'staccato' ? rng('ig', UTI18N.tr('Gap %'), Math.round((m.g ?? 0.5) * 100), 10, 80, 5) : ''}
      ${m.k === 'vibrato' ? rng('idep', UTI18N.tr('Depth (semitones)'), m.depth ?? 0.5, 0.1, 2, 0.1) + rng('irate', UTI18N.tr('Rate (Hz)'), m.rate ?? 6, 2, 14, 1) : ''}
      ${m.k === 'slide' ? rng('ist', UTI18N.tr('To (semitones)'), m.st ?? 12, -24, 24, 1) : ''}
      ${m.k === 'arp' ? `<label>Chord ${selBox('ichord', [['major', 'Major'], ['minor', 'Minor'], ['fifth', 'Fifth'], ['octave', 'Octave']], m.chord || 'major')}</label>` + rng('ims', UTI18N.tr('Speed (ms)'), m.ms ?? 60, 30, 150, 5) : ''}
      <span class="ut-spacer"></span><button class="ut-btn ut-btn--sm" id="idup">Duplicate</button><button class="ut-btn ut-btn--sm ut-btn--danger" id="idel">Remove</button>`;
    const upd = () => { drawRoll(); changed(); };
    $('#inote', b).onchange = e => { n.hz = S.midi2hz(+e.target.value); upd(); };
    $('#ilen', b).onchange = e => { const d = Math.max(1, +e.target.value || 1) * step(); n.d = Math.min(d, nextStart(p, n.t, SND.sel) - n.t); upd(); drawInsp(); };
    $('#imod', b).onchange = e => { n.mod = e.target.value === 'none' ? undefined : { k: e.target.value }; upd(); drawInsp(); };
    const bindR = (id, key, f = x => x) => { const x = $('#' + id, b); if (x) x.oninput = () => { n.mod[key] = f(+x.value); $('#' + id + 'v', b).textContent = x.value; upd(); }; };
    bindR('ig', 'g', v => v / 100); bindR('idep', 'depth'); bindR('irate', 'rate'); bindR('ist', 'st'); bindR('ims', 'ms');
    const ch = $('#ichord', b); if (ch) ch.onchange = () => { n.mod.chord = ch.value; upd(); };
    $('#idel', b).onclick = () => { p.notes.splice(SND.sel, 1); SND.sel = -1; drawRoll(); drawInsp(); changed(); };
    $('#idup', b).onclick = () => dup();
  }

  function dup() {
    const p = pat(), n = p.notes[SND.sel];
    if (!n) return;
    const c = JSON.parse(JSON.stringify(n)); c.t = n.t + n.d;
    if (!free(p, c.t, c.d, -1)) return toast('No room', 'The place after the block is taken.', 'warn');
    p.notes.push(c); SND.sel = p.notes.length - 1; drawRoll(); drawInsp(); changed();
  }

  function bindRoll() {
    const p = pat(), grid = $('#sgridel', b), z = SND.zoom;
    const at = e => { const r = grid.getBoundingClientRect(); return { x: e.clientX - r.left, y: e.clientY - r.top }; };
    grid.onpointerdown = e => {
      if (e.button) return;
      const blk = e.target.closest('.ut-snd__blk'), end = e.target.closest('.ut-snd__end'), p0 = at(e);
      if (end) {                            // pattern end marker
        grid.setPointerCapture(e.pointerId);
        grid.onpointermove = ev => { end.style.left = Math.max(S.patLen({ notes: p.notes }), snap(at(ev).x / z)) * z + 'px'; };
        grid.onpointerup = ev => { grid.onpointermove = grid.onpointerup = null; p.len = Math.max(Math.max(0, ...p.notes.map(n => n.t + n.d)), snap(at(ev).x / z)); drawRoll(); drawInsp(); changed(); };
        return;
      }
      if (!blk) {                           // empty grid: a new note, one beat long
        const t = Math.floor(p0.x / z / step()) * step(), row = Math.floor(p0.y / ROW_H), m = rows()[row];
        if (m === undefined || !free(p, t, step(), -1)) return;
        const d = Math.min(Math.max(step(), 60000 / sc.bpm), nextStart(p, t, -1) - t);
        p.notes.push({ t, d, hz: S.midi2hz(m) }); SND.sel = p.notes.length - 1;
        drawRoll(); drawInsp(); changed(); sndPreview([[Math.round(S.midi2hz(m)), 150]]);
        return;
      }
      const i = +blk.dataset.i, n = p.notes[i], resize = e.target.classList.contains('ut-snd__rz');
      SND.sel = i; $$('.ut-snd__blk', grid).forEach(x => x.classList.toggle('is-sel', x === blk));
      grid.setPointerCapture(e.pointerId);
      let nt = n.t, nd = n.d, nrow = rowOf(n.hz);
      grid.onpointermove = ev => {
        const q = at(ev);
        if (resize) { nd = Math.max(step(), snap(n.d + (q.x - p0.x) / z)); nd = Math.min(nd, nextStart(p, n.t, i) - n.t); blk.style.width = nd * z + 'px'; }
        else { nt = snap(n.t + (q.x - p0.x) / z); nrow = Math.min(rows().length - 1, Math.max(0, rowOf(n.hz) + Math.round((q.y - p0.y) / ROW_H)));
          blk.style.left = nt * z + 'px'; blk.style.top = nrow * ROW_H + 'px'; }
      };
      grid.onpointerup = () => {
        grid.onpointermove = grid.onpointerup = null;
        if (resize) n.d = nd;
        else if (nt !== n.t || nrow !== rowOf(n.hz)) {
          if (free(p, nt, n.d, i)) { const moved = nrow !== rowOf(n.hz); n.t = nt; if (moved) n.hz = S.midi2hz(rows()[nrow]); if (moved) sndPreview([[Math.round(n.hz), 150]]); }
          else toast('No room', 'The buzzer plays one tone at a time: blocks must not overlap.', 'warn');
        }
        drawRoll(); drawInsp(); changed();
      };
    };
    grid.ondblclick = e => { const blk = e.target.closest('.ut-snd__blk'); if (!blk) return; p.notes.splice(+blk.dataset.i, 1); SND.sel = -1; drawRoll(); drawInsp(); changed(); };
    grid.ondragover = e => { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; };
    grid.ondrop = e => {
      e.preventDefault();
      const [kind, v] = (e.dataTransfer.getData('text/plain') || '').split(':'), q = at(e);
      const t = Math.floor(q.x / z / step()) * step(), m = kind === 'note' ? +v : rows()[Math.max(0, Math.floor(q.y / ROW_H))];
      const add = kind === 'note' ? [{ t, d: Math.max(step(), 60000 / sc.bpm), hz: S.midi2hz(m) }] : kind === 'motif' ? S.motif(v, sc, m, t) : [];
      if (!add.length) return;
      if (!add.every(n => free(p, n.t, n.d, -1) && add.every(o => o === n || o.t + o.d <= n.t || o.t >= n.t + n.d)))
        return toast('No room', 'The buzzer plays one tone at a time: blocks must not overlap.', 'warn');
      p.notes.push(...add); SND.sel = p.notes.length - 1; drawRoll(); drawInsp(); changed();
      sndPreview(S.render({ ...sc, patterns: [{ name: 'x', notes: add.map(n => ({ ...n, t: n.t - t })) }], arrangement: [{ p: 0, n: 1 }] }));
    };
  }

  $('#sroll', b).onkeydown = e => {
    const p = pat(), n = p.notes[SND.sel];
    if (!n) return;
    const r = rows(), row = rowOf(n.hz);
    if (e.key === 'Delete' || e.key === 'Backspace') { p.notes.splice(SND.sel, 1); SND.sel = -1; }
    else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') { const nr = Math.min(r.length - 1, Math.max(0, row + (e.key === 'ArrowUp' ? -1 : 1))); n.hz = S.midi2hz(r[nr]); sndPreview([[Math.round(n.hz), 120]]); }
    else if ((e.key === 'ArrowLeft' || e.key === 'ArrowRight') && e.shiftKey) { const d = Math.max(step(), n.d + (e.key === 'ArrowRight' ? step() : -step())); if (free(p, n.t, d, SND.sel)) n.d = d; }
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { const t = Math.max(0, n.t + (e.key === 'ArrowRight' ? step() : -step())); if (free(p, t, n.d, SND.sel)) n.t = t; }
    else if (e.key === 'd' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); return dup(); }
    else return;
    e.preventDefault(); drawRoll(); drawInsp(); changed(); $('#sroll', b).focus();
  };
  $('#sbpm', b).onchange = e => {
    const bpm = Math.min(300, Math.max(40, +e.target.value || 120)), f = sc.bpm / bpm;
    sc.patterns.forEach(p => { p.notes.forEach(n => { n.t *= f; n.d *= f; }); if (p.len) p.len *= f; });   // the music keeps its shape, only faster or slower
    sc.bpm = bpm; drawRoll(); drawInsp(); changed();
  };
  $('#sgrid', b).onchange = e => { sc.grid = +e.target.value; drawRoll(); drawInsp(); };
  $('#skey', b).onchange = e => { sc.key = e.target.value; drawPal(); drawRoll(); drawInsp(); changed(); };
  $('#sscale', b).onchange = e => { sc.scale = e.target.value; drawPal(); drawRoll(); drawInsp(); changed(); };
  $('#szoom', b).oninput = e => { SND.zoom = +e.target.value; drawRoll(); };
  $('#sweb', b).onclick = () => sndPreview(S.render(sc));
  $('#sstop', b).onclick = () => { if (SND.stop) SND.stop(); api('sound/play', { stop: true }).catch(() => { }); };
  $('#snas', b).onclick = () => api('sound/play', { notes: S.render(sc), tempo: 1 }).catch(fail);
  $('#ssave', b).onclick = async () => { await save('sound/save', { event: SND.ev, notes: S.render(sc), tempo: 1, score: sc }, 'sound'); SND.dirty = false; };
  $('#sreset', b).onclick = () => { SND.loaded = null; save('sound/save', { event: SND.ev, reset: true }, 'sound'); };
  $('#simp', b).onchange = async e => {
    try { const j = JSON.parse(await e.target.files[0].text()); const r = await api('sound/import', { soundset: j }); SND.loaded = null; toast('Imported', r.imported + ' Events'); render('sound'); }
    catch (x) { fail(x); }
  };
  $('#sexp', b).onclick = () => {
    const ev = {};
    for (const k of Object.keys(EV_NAMES)) {
      const u = (SND.st.user || {})[k];
      if (u) ev[k] = { tempo: u.tempo, notes: u.notes.map(([h, m, t]) => Object.assign({ frequency_hz: h, duration_ms: m }, t ? { tie: true } : {})), ...(u.score ? { score: u.score } : {}) };
    }
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify({ title: 'UntrashOS sound set', events: ev }, null, 1)], { type: 'application/json' }));
    a.download = 'untrash-soundset.json'; a.click();
  };
  drawArr(); drawPal(); drawRoll(); drawInsp(); info();
};


/* share links and "share this folder" (Files) ------------------------------ */
function linkDialog(share, path, name) {
  const d = dialog({ title: 'Share link', ok: 'Create link',
    body: `<p>A download link for <b translate="no">${esc(name)}</b>${/\.[^/]+$/.test(name) ? '' : ' (folder as ZIP)'}. Anyone with the link can download – without signing in.</p>
      <div class="ut-field"><label for="ld">Valid</label><select class="ut-select" id="ld"><option value="1">1 day</option><option value="7" selected>7 days</option><option value="30">30 days</option><option value="90">90 days</option></select></div>
      ${field('lp', 'Password (optional, at least 4 characters)', '', 'type=password autocomplete=new-password')}
      <p class="ut-faint">Usable at once in the home network; from outside only with port forwarding or later via UntrashMesh.</p>`,
    onOk: async s => {
      const r = await api('links/create', { share, path, days: +$('#ld', s).value, password: $('#lp', s).value });
      const url = location.origin + r.url;
      dialog({ title: 'Link created', ok: 'Copy', body: `<input class="ut-input" id="lu" value="${esc(url)}" readonly translate="no"><p class="ut-faint">Valid until ${new Date(r.expires * 1000).toLocaleDateString(UTI18N.locale)}.</p>`,
        onOk: async () => { try { await navigator.clipboard.writeText(url); toast('Copied'); } catch (e) { $('#lu').select(); document.execCommand('copy'); toast('Copied'); } } });
    } });
  return d;
}
async function linksDialog() {
  const r = await api('links');
  const d = dialog({ title: 'Shared links', ok: 'Close', onOk: () => true,
    body: r.links.length ? `<div class="ut-table-wrap"><table class="ut-table"><thead><tr><th>File</th><th>Valid until</th><th></th></tr></thead><tbody>
      ${r.links.map(l => `<tr><td translate="no">${esc(l.share + '/' + l.path)}${l.password ? ' 🔒' : ''}${ME.admin && l.owner !== ME.user ? ` <small class="muted">${esc(l.owner)}</small>` : ''}</td>
        <td>${new Date(l.expires * 1000).toLocaleDateString(UTI18N.locale)}</td><td><button class="ut-btn ut-btn--ghost ut-btn--sm" data-cp="${esc(l.token)}">Copy</button><button class="ut-btn ut-btn--ghost ut-btn--sm" data-ld="${esc(l.token)}">Delete</button></td></tr>`).join('')}</tbody></table></div>`
      : '<p class="muted">No shared links.</p>' });
  $$('[data-cp]', d).forEach(x => x.onclick = async () => { try { await navigator.clipboard.writeText(location.origin + '/s/' + x.dataset.cp); toast('Copied'); } catch (e) { fail(e); } });
  $$('[data-ld]', d).forEach(x => x.onclick = async () => { try { await api('links/delete', { token: x.dataset.ld }); d.remove(); linksDialog(); } catch (e) { fail(e); } });
}
async function shareFromFolder(share, path, name) {
  const sh = await api('shares'), s = sh.shares.find(x => x.name === share);
  const abs = s.path + '/' + path, vol = sh.volumes.find(v => abs.startsWith(v.path + '/'));
  if (!vol) return toast('Not an internal volume.', '', 'warn');
  SHARE_PICK = abs.slice(vol.path.length + 1);
  SHARE_PREFILL = { volume: vol.id, folder: SHARE_PICK, name: name.replace(/[^A-Za-z0-9_.-]/g, '-').slice(0, 32) };
  openApp('shares'); render('shares', '_new');
}


/* feedback: a prefilled GitHub issue; nothing is sent by the NAS ---------- */
VIEWS.feedback = async b => {
  const f = await api('feedback/info'), i = f.info;
  b.innerHTML = `<div class="ut-window__main ut-fb"><h2>Feedback</h2>
    <p class="muted">Report a bug or suggest an improvement. Nothing is sent automatically: the text opens as a prepared issue on GitHub, you check it and submit it yourself (GitHub account needed).</p>
    <div class="row" style="gap:16px"><label><input type="radio" name="fk" value="bug" checked> Error</label><label><input type="radio" name="fk" value="enhancement"> Suggestion</label></div>
    ${field('ft', 'Title')}
    <div class="ut-field"><label for="fd">Description</label><textarea class="ut-input" id="fd" rows="6" placeholder="What happened? What did you expect? How can it be reproduced?"></textarea></div>
    ${sw('fi', true, 'Attach anonymised system info (version, kernel, disks, RAID, services, recent error messages; no addresses or names)')}
    <details><summary>Preview</summary><pre class="ut-log" id="fp" translate="no"></pre></details>
    <div class="row" style="gap:6px;flex-wrap:wrap"><span class="ut-spacer"></span><button class="ut-btn" id="fcopy">Copy text</button>
      <button class="ut-btn ut-btn--primary" id="fgo"${f.issues ? '' : ' disabled'}>Open on GitHub</button></div>
    ${f.issues ? '' : '<p class="ut-faint">No project address is set for this image.</p>'}</div>`;
  const text = () => {
    const kind = b.querySelector('[name=fk]:checked').value;
    let t = $('#fd', b).value.trim() + '\n';
    if ($('#fi', b).checked) t += `\n---\n**UntrashOS** ${i.version} · Kernel ${i.kernel} · Start ${i.boot} · Language ${i.language}\n**Disks** ${i.disks || '–'} · **RAID** ${i.raid}\n**Services** ${i.services || '–'}\n` +
      (i.errors ? '\n<details><summary>Recent error messages</summary>\n\n```\n' + i.errors + '\n```\n</details>\n' : '');
    return { kind, title: $('#ft', b).value.trim(), body: t.slice(0, 6000) };
  };
  const prev = () => { const x = text(); $('#fp', b).textContent = '[' + x.kind + '] ' + x.title + '\n\n' + x.body; };
  b.querySelectorAll('input,textarea').forEach(x => x.addEventListener('input', prev)); prev();
  $('#fcopy', b).onclick = async () => { const x = text(); try { await navigator.clipboard.writeText(x.title + '\n\n' + x.body); toast('Copied'); } catch (e) { fail(e); } };
  $('#fgo', b).onclick = () => {
    const x = text(); if (!x.title) return toast('Title missing', '', 'warn');
    window.open(f.issues.replace(/\/$/, '') + '/new?' + new URLSearchParams({ title: x.title, body: x.body, labels: x.kind }), '_blank', 'noopener');
  };
};


/* export: copy or convert to a USB drive / SD card or another share ------- */
async function exportDialog(share, path, name, isDir) {
  const [tg, pr] = await Promise.all([api('export/targets'), !isDir && /^(video)$/.test(mediaKind(name)) ? api('files/probe?' + new URLSearchParams({ share, path })) : null]);
  const audio = pr ? pr.audio : [];
  const opts = (id, list, cur) => `<select class="ut-select" id="${id}">${list.map(([v, l]) => `<option value="${v}"${String(v) === String(cur) ? ' selected' : ''}>${l}</option>`).join('')}</select>`;
  const d = dialog({ kind: 'wide', title: 'Export', ok: 'Start export', body: `<div class="ut-exp">
    <p><b translate="no">${esc(name)}</b>${isDir ? ' (folder with all subfolders)' : ''}</p>
    <div class="ut-field"><label for="et">Target</label><select class="ut-select" id="et">
      ${tg.usb.map(u => `<option value="usb:${esc(u.id)}" translate="no">USB/SD: ${esc(u.name)} (${gb(u.free)} ${esc(UTI18N.tr('free'))})</option>`).join('')}
      ${tg.shares.map(x => `<option value="share:${esc(x)}" translate="no">${esc(UTI18N.tr('Share'))}: ${esc(x)}</option>`).join('')}</select>
      ${tg.usb.length ? '' : '<p class="ut-faint">No USB drive found: plug in a USB stick or SD card reader and open the dialog again.</p>'}</div>
    ${field('ef', 'Target folder', 'UntrashOS-Export ' + new Date().toISOString().slice(0, 10))}
    <div class="row" style="gap:16px"><label><input type="radio" name="em" value="copy" checked> Copy only</label><label><input type="radio" name="em" value="convert"> Convert</label></div>
    <div id="econv" hidden>
      <div class="ut-section-title">Video (H.264)</div>
      <div class="row" style="gap:8px;flex-wrap:wrap">
        <div class="ut-field"><label for="eh">Resolution</label>${opts('eh', [[0, 'as original'], [1080, '1080p'], [720, '720p'], [480, '480p'], [360, '360p']], 720)}</div>
        <div class="ut-field"><label for="eq">Quality</label>${opts('eq', [[20, 'high'], [23, 'good'], [26, 'medium'], [29, 'small']], 23)}</div>
        <div class="ut-field"><label for="es">Target file size (MB)</label><input class="ut-input" id="es" inputmode="numeric" placeholder="empty = by quality"></div>
      </div>
      ${sw('ek', false, 'Keep the picture unchanged if possible (H.264, fast)')}
      <div class="ut-section-title">Audio</div>
      <div class="row" style="gap:8px;flex-wrap:wrap">
        <div class="ut-field"><label for="ea">Format</label>${opts('ea', [['aac', 'AAC'], ['mp3', 'MP3'], ['opus', 'Opus'], ['copy', 'unchanged']], 'aac')}</div>
        <div class="ut-field"><label for="eb">Bitrate</label>${opts('eb', [[96, '96 kbit/s'], [128, '128 kbit/s'], [160, '160 kbit/s'], [192, '192 kbit/s'], [256, '256 kbit/s']], 160)}</div>
      </div>
      ${sw('e2', true, 'Mix down to stereo')}
      ${audio.length > 1 ? `<div class="ut-field"><label>Audio tracks</label>${audio.map(a => `<label class="row" style="gap:6px"><input type="checkbox" data-tr="${a.index}" checked> <span translate="no">${esc((a.lang || '?') + ' · ' + a.codec + (a.channels ? ' ' + a.channels + 'ch' : '') + (a.title ? ' · ' + a.title : ''))}</span></label>`).join('')}</div>` : ''}
      ${sw('esub', true, 'Keep subtitles')}
      <div class="ut-field"><label for="ec">Container</label>${opts('ec', [['mp4', 'MP4 (plays everywhere)'], ['mkv', 'MKV (all subtitles)']], 'mp4')}</div>
      <div class="ut-section-title">Music</div>
      <div class="row" style="gap:8px;flex-wrap:wrap"><div class="ut-field"><label for="emc">Format</label>${opts('emc', [['mp3', 'MP3'], ['aac', 'AAC'], ['opus', 'Opus'], ['flac', 'FLAC'], ['copy', 'unchanged']], 'mp3')}</div>
        <div class="ut-field"><label for="emb">Bitrate</label>${opts('emb', [[128, '128 kbit/s'], [192, '192 kbit/s'], [256, '256 kbit/s'], [320, '320 kbit/s']], 192)}</div></div>
      <p class="ut-faint">The target file size applies per video and is an upper limit.</p>
      <p class="ut-faint">Converting runs in the background and is slow on the NAS (no hardware encoder): a feature film in 720p takes several hours. Progress under “Exports”.</p>
    </div></div>`,
    onOk: async s => {
      const conv = (s.querySelector('[name=em]:checked') || {}).value === 'convert', t = $('#et', s).value;
      if (!t) throw new Error('Choose a USB target.');
      const tracks = $$('[data-tr]', s).length ? $$('[data-tr]', s).filter(x => x.checked).map(x => +x.dataset.tr) : null;
      await api('export/start', { sources: [{ share, path }], folder: $('#ef', s).value.trim(), mode: conv ? 'convert' : 'copy',
        target: t.startsWith('usb:') ? { usb: t.slice(4) } : { share: t.slice(6), path: '' },
        video: { height: +$('#eh', s).value, quality: +$('#eq', s).value, size_mb: parseFloat($('#es', s).value) || 0, keep: $('#ek', s).checked },
        audio: { codec: $('#ea', s).value, kbps: +$('#eb', s).value, stereo: $('#e2', s).checked, tracks },
        subs: $('#esub', s).checked, container: $('#ec', s).value, music: { codec: $('#emc', s).value, kbps: +$('#emb', s).value } });
      toast('Export started', name); exportsDialog();
    } });
  $$('[name=em]', d).forEach(r => r.onchange = () => { $('#econv', d).hidden = (d.querySelector('[name=em]:checked') || {}).value !== 'convert'; });
}
async function exportsDialog() {
  const old = document.getElementById('expdlg'); if (old) old.remove();
  const d = dialog({ kind: 'wide', title: 'Exports', ok: 'Close', onOk: () => { clearInterval(t); return true; }, body: '<div id="expl"><span class="ut-spinner"></span></div>' });
  d.id = 'expdlg';
  const ST = { waiting: 'waiting', running: 'running', done: 'done', failed: 'with errors', cancelled: 'cancelled' };
  const draw = async () => {
    if (!d.isConnected) return clearInterval(t);
    const j = (await api('export/jobs')).jobs, l = $('#expl', d);
    l.innerHTML = j.length ? j.map(e => `<div class="ut-expjob"><div class="row"><b translate="no">${esc(e.folder)}</b><span class="ut-pill ${e.state === 'done' ? 'ut-pill--ok' : e.state === 'failed' ? 'ut-pill--danger' : ''}">${ST[e.state] || e.state}</span><span class="ut-spacer"></span>
        ${/waiting|running/.test(e.state) ? `<button class="ut-btn ut-btn--ghost ut-btn--sm" data-xc="${e.id}">Cancel</button>` : `<button class="ut-btn ut-btn--ghost ut-btn--sm" data-xr="${e.id}">Remove</button>`}</div>
        <div class="ut-progress"><i style="--v:${e.percent || 0}%"></i></div>
        <div class="muted" translate="no">${esc(e.file || '')}</div><div class="muted">${e.percent || 0} %${e.eta_s ? ' · remaining ' + fmtT(e.eta_s) : ''}${e.errors.length ? ' · ' + e.errors.length + ' Error' : ''}</div>
        ${e.errors.length ? `<pre class="ut-log" translate="no">${esc(e.errors.join('\n'))}</pre>` : ''}</div>`).join('') : '<p class="muted">No exports.</p>';
    $$('[data-xc]', d).forEach(x => x.onclick = () => api('export/cancel', { id: x.dataset.xc }).then(draw).catch(fail));
    $$('[data-xr]', d).forEach(x => x.onclick = () => api('export/cancel', { id: x.dataset.xr, remove: true }).then(draw).catch(fail));
  };
  const d1 = single(draw), t = setInterval(() => d1().catch(() => { }), 2000); d1();
}


/* media server (DLNA): status, media types per share, settings ------------ */
const PROFILES = [['480', 'Video 480p (little CPU)'], ['720', 'Video 720p (more CPU)'], ['copy', 'Video unchanged (H.264 only, hardly any CPU)'], ['radio', 'Radio (sound only)']];
VIEWS.media = async (b, sel = 'status') => {
  const m = await api('media');
  const nav = sidebar('media', [['status', 'Status'], ['shares', 'Shares'], ['tv', 'Channels'], ['settings', 'Settings']], sel);
  let main = '';
  if (sel === 'status') {
    const L = m.library, n = x => (x || 0).toLocaleString(UTI18N.locale);
    main = `<div class="row"><h2 style="margin:0">Media server</h2><span class="ut-pill ${m.running ? 'ut-pill--ok' : m.active ? 'ut-pill--warn' : ''}">${m.running ? 'running' : m.active ? 'starting …' : 'off'}</span>
        ${m.indexing ? '<span class="ut-pill"><span class="ut-spinner" style="width:10px;height:10px"></span> indexing</span>' : ''}<span class="ut-spacer"></span>
        <button class="ut-btn ut-btn--sm" id="mrs"${m.active ? '' : ' disabled'}>Rescan</button></div>
      <p class="muted">On the network as <b translate="no">${esc(m.name)}</b> (DLNA/UPnP: TVs, consoles, VLC, Kodi).</p>
      <div class="ut-media-stats">${[['video', 'Videos', '🎬'], ['audio', 'Songs', '🎵'], ['image', 'Photos', '🖼']].map(([k, l, i]) => `<div class="ut-card"><div class="ut-media-stat__n">${n(L[k])}</div><div class="muted">${i} ${l}</div></div>`).join('')}</div>
      <div class="ut-section-title">Devices</div>
      ${m.clients.length ? `<table class="ut-table"><thead><tr><th>Device</th><th>Address</th><th class="num">Connections</th></tr></thead><tbody>${m.clients.map(c => `<tr><td translate="no">${esc(c.type)}</td><td class="mono" translate="no">${esc(c.ip)}</td><td class="num">${c.connections}</td></tr>`).join('')}</tbody></table>` : '<p class="muted">No device has queried the media server yet.</p>'}
      <p class="muted">Current playbacks: ${m.streams} · Database ${size(m.db_size)}${m.db_time ? ' · As of ' + esc(new Date(m.db_time * 1000).toLocaleString(UTI18N.locale)) : ''}</p>
      <div class="ut-section-title">Channels</div>
      <p class="muted">${m.tv.channels.length ? m.tv.channels.map(c => `<span translate="no">${esc(c.name)}</span>${c.running ? ' (' + c.viewers + ' viewers)' : ''}`).join(' · ') : 'No channels yet.'}</p>`;
  } else if (sel === 'shares') {
    main = `<h2>What the media server shows</h2><p class="muted">Media types per share. The server does not publish empty or missing folders.</p>
      <table class="ut-table"><thead><tr><th>Share</th>${MEDIA.map(([, l]) => `<th>${l}</th>`).join('')}<th></th></tr></thead><tbody>
      ${m.shares.map(x => `<tr data-s="${esc(x.name)}"><td translate="no">${esc(x.name)}</td>${MEDIA.map(([k]) => `<td><input type="checkbox" data-m="${k}"${x.media & k ? ' checked' : ''}></td>`).join('')}
        <td>${x.published ? '<span class="ut-pill ut-pill--ok">published</span>' : x.media ? `<span class="ut-pill">${x.present ? 'empty' : 'missing'}</span>` : ''}</td></tr>`).join('')}</tbody></table>
      <div class="row" style="margin-top:12px"><button class="ut-btn ut-btn--primary" id="msv">Save</button></div>`;
  } else if (sel === 'tv') {
    main = tvAdmin(m.tv);
  } else {
    main = `<h2>Settings</h2>${sw('mon', m.active, 'Media server on')}
      ${sw('mlan', m.tv.lan_open, 'Channels receivable in the home network without signing in (for TVs, VLC, Kodi)')}
      <p class="muted">The network name is the host name (Settings → System).</p>
      <div class="row" style="margin-top:12px"><button class="ut-btn ut-btn--primary" id="mss">Save</button></div>`;
  }
  b.innerHTML = nav + `<div class="ut-window__main">${main}</div>`;
  navBind(b, 'media');
  const rs = $('#mrs', b); if (rs) rs.onclick = () => dialog({ title: 'Rescan?', ok: 'Rescan', body: '<p>The media database is rebuilt. Depending on the collection this takes a few minutes; meanwhile devices do not see all files.</p>',
    onOk: async () => { await api('media/rescan', {}); toast('Rescan started'); setTimeout(() => render('media', 'status'), 1500); } });
  const sv = $('#msv', b); if (sv) sv.onclick = () => {
    const shares = {}; $$('[data-s]', b).forEach(r => { shares[r.dataset.s] = $$('[data-m]', r).reduce((a, c) => a | (c.checked ? +c.dataset.m : 0), 0); });
    save('media/save', { shares }, 'media', 'shares');
  };
  const ss = $('#mss', b); if (ss) ss.onclick = () => save('media/save', { active: $('#mon', b).checked, lan_open: $('#mlan', b).checked }, 'media', 'settings');
  if (sel === 'tv') {
    tvAdminBind(b, m.tv);
    if (m.tv.channels.some(c => c.preparing)) { const t = setTimeout(() => wins.media && $('#tvn', b) && render('media', 'tv'), 4000); CLEANUP.media = () => clearTimeout(t); }
  }
  if (sel === 'status') { const t = setTimeout(() => wins.media && $('#mrs', b) && render('media', 'status'), 10000); CLEANUP.media = () => clearTimeout(t); }
};

/* broadcast channels ("Sendemodus") --------------------------------------- */
const tvUrl = id => location.origin + '/tv/' + id + '/index.m3u8';
function tvAdmin(t) {
  return `<div class="row"><h2 style="margin:0">Channels</h2><span class="ut-spacer"></span><a class="ut-btn ut-btn--sm ut-btn--ghost" href="/tv/channels.m3u" download>Channel list (M3U)</a><button class="ut-btn ut-btn--sm ut-btn--primary" id="tvn">New channel</button></div>
    <p class="muted">A channel plays its playlist endlessly by the clock, like TV: whoever tunes in sees what is on right now, and all devices see the same. The NAS converts only once, no matter how many are watching (at most ${t.max_running} channels at once). A channel starts with the first viewer and pauses after one minute without viewers.</p>
    ${t.channels.length ? t.channels.map(c => `<div class="ut-card ut-tvch">
      <div class="row"><b translate="no">${c.profile === 'radio' ? '📻' : '📺'} ${esc(c.name)}</b><span class="ut-pill ${c.running ? 'ut-pill--ok' : ''}">${c.running ? '● ' + c.viewers + ' viewers' : c.preparing ? 'preparing' : 'paused'}</span>
        <span class="ut-spacer"></span><span class="muted">${esc((PROFILES.find(p => p[0] === c.profile) || ['', c.profile])[1])}</span></div>
      ${c.preparing ? `<div class="ut-progress"><i style="--v:${Math.round(100 * c.preparing.done / Math.max(1, c.preparing.total))}%"></i></div>
        <div class="muted">Reading durations: ${c.preparing.done} of ${c.preparing.total} files (once; afterwards the channel starts at once)</div>` : ''}
      <div class="muted">On now: <span translate="no">${esc(c.now || '–')}</span>${c.now_left_s ? ' · remaining ' + fmtT(c.now_left_s) : ''} · ${c.files} Files · ${fmtT(c.total_s)}</div>
      <div class="ut-rowbtns"><button class="ut-btn ut-btn--sm" data-tw="${c.id}">Watch</button><button class="ut-btn ut-btn--sm ut-btn--ghost" data-tu="${c.id}">Address</button><button class="ut-btn ut-btn--sm ut-btn--ghost" data-te="${c.id}">Edit</button>${c.running ? `<button class="ut-btn ut-btn--sm ut-btn--ghost" data-ts="${c.id}">Stop</button>` : ''}<button class="ut-btn ut-btn--sm ut-btn--ghost" data-td="${c.id}">Delete</button></div></div>`).join('')
      : '<p class="muted">No channels yet. “New channel” creates one: pick a name and videos or music from the shares, done.</p>'}`;
}
function tvAdminBind(b, t) {
  $('#tvn', b).onclick = () => tvEdit(null);
  $$('[data-te]', b).forEach(x => x.onclick = () => tvEdit(t.channels.find(c => c.id === x.dataset.te)));
  $$('[data-tw]', b).forEach(x => x.onclick = () => { TVW.id = x.dataset.tw; wins.tv ? render('tv') : openApp('tv'); });
  $$('[data-tu]', b).forEach(x => x.onclick = () => dialog({ title: 'Channel address', ok: 'Copy',
    body: `<p>Open as a network stream in VLC, Kodi or an IPTV app. All channels at once: the channel list (M3U).</p><input class="ut-input mono" id="tvu" readonly value="${esc(tvUrl(x.dataset.tu))}">
      <input class="ut-input mono" readonly value="${esc(location.origin + '/tv/channels.m3u')}" style="margin-top:6px">`,
    onOk: async s => { try { await navigator.clipboard.writeText($('#tvu', s).value); toast('Copied'); } catch (e) { $('#tvu', s).select(); document.execCommand('copy'); toast('Copied'); } } }));
  $$('[data-ts]', b).forEach(x => x.onclick = () => api('tv/stop', { id: x.dataset.ts }).then(() => render('media', 'tv')).catch(fail));
  $$('[data-td]', b).forEach(x => x.onclick = () => dialog({ title: 'Delete channel?', ok: 'Delete', okCls: 'ut-btn--danger', body: '<p>The files stay, only the channel goes.</p>',
    onOk: async () => { await api('tv/delete', { id: x.dataset.td }); render('media', 'tv'); } }));
}
async function tvEdit(c) {
  const items = c ? c.items.map(x => Object.assign({}, x)) : [];
  const sh = (await api('shares')).shares.filter(x => x.present !== false);
  let cur = { share: (items[0] || sh[0] || {}).share || (sh[0] || {}).name || '', path: '' };
  const d = dialog({ kind: 'wide', title: c ? 'Edit channel' : 'New channel', ok: 'Save', body: `<div class="ut-tvedit">
    <div class="row" style="gap:8px;flex-wrap:wrap">${field('tvname', 'Name', c ? c.name : '', 'maxlength=40 placeholder="e.g. Movie channel"')}
      <div class="ut-field"><label for="tvp">Type</label><select class="ut-select" id="tvp">${PROFILES.map(([k, l]) => `<option value="${k}"${(c ? c.profile : '480') === k ? ' selected' : ''}>${l}</option>`).join('')}</select></div></div>
    ${sw('tvsh', c && c.shuffle, 'Random order (the same for everyone)')}
    <div class="ut-tvedit__cols"><div><div class="ut-section-title">Shares</div><select class="ut-select" id="tvs" translate="no">${sh.map(x => `<option${x.name === cur.share ? ' selected' : ''}>${esc(x.name)}</option>`).join('')}</select>
      <div class="crumbs" id="tvc"></div><div class="ut-tvedit__list" id="tvb"></div></div>
      <div><div class="ut-section-title">Playlist</div><div class="ut-tvedit__list" id="tvl"></div><p class="ut-faint">Folders play all videos or songs in them (with subfolders) in name order.</p></div></div></div>`,
    onOk: async s => {
      await api('tv/save', { id: c ? c.id : '', name: $('#tvname', s).value, profile: $('#tvp', s).value, shuffle: $('#tvsh', s).checked, items });
      toast('Saved'); render('media', 'tv');
    } });
  const drawList = () => {
    $('#tvl', d).innerHTML = items.length ? items.map((x, i) => `<div class="ut-tvedit__it"><span translate="no">${esc(x.share + '/' + x.path)}</span><span class="ut-spacer"></span>
      <button class="ut-btn ut-btn--ghost ut-btn--sm" data-up="${i}" aria-label="Move up">↑</button><button class="ut-btn ut-btn--ghost ut-btn--sm" data-rm="${i}" aria-label="Remove">✕</button></div>`).join('') : '<p class="muted">Empty: add files or folders on the left with +.</p>';
    $$('[data-rm]', d).forEach(x => x.onclick = () => { items.splice(+x.dataset.rm, 1); drawList(); });
    $$('[data-up]', d).forEach(x => x.onclick = () => { const i = +x.dataset.up; if (i) { items.splice(i - 1, 0, items.splice(i, 1)[0]); drawList(); } });
  };
  const browse = async () => {
    const r = await api('files?' + new URLSearchParams(cur)), parts = cur.path ? cur.path.split('/') : [];
    $('#tvc', d).innerHTML = `<button data-p="" translate="no">${esc(cur.share)}</button>` + parts.map((x, i) => ` / <button data-p="${esc(parts.slice(0, i + 1).join('/'))}" translate="no">${esc(x)}</button>`).join('');
    const ok = e => e.dir || /^(audio|video)$/.test(mediaKind(e.name));
    $('#tvb', d).innerHTML = (cur.path ? `<div class="ut-tvedit__it"><span>📁 + ${esc(UTI18N.tr('this folder'))}</span><span class="ut-spacer"></span><button class="ut-btn ut-btn--ghost ut-btn--sm" data-add="">+</button></div>` : '') +
      r.entries.filter(ok).map(e => `<div class="ut-tvedit__it"><span translate="no" ${e.dir ? `data-open="${esc(e.name)}" class="ut-link"` : ''}>${e.dir ? '📁 ' : '🎞 '}${esc(e.name)}</span><span class="ut-spacer"></span><button class="ut-btn ut-btn--ghost ut-btn--sm" data-add="${esc(e.name)}">+</button></div>`).join('') || '<p class="muted">No media here.</p>';
    $$('[data-p]', $('#tvc', d)).forEach(x => x.onclick = () => { cur.path = x.dataset.p; browse().catch(fail); });
    $$('[data-open]', d).forEach(x => x.onclick = () => { cur.path = (cur.path ? cur.path + '/' : '') + x.dataset.open; browse().catch(fail); });
    $$('[data-add]', d).forEach(x => x.onclick = () => { const p = x.dataset.add ? (cur.path ? cur.path + '/' : '') + x.dataset.add : cur.path; if (!items.some(y => y.share === cur.share && y.path === p)) items.push({ share: cur.share, path: p }); drawList(); });
  };
  $('#tvs', d).onchange = e => { cur = { share: e.target.value, path: '' }; browse().catch(fail); };
  drawList(); if (cur.share) browse().catch(fail);
}

/* watching: channel list + live player (hls.js where the browser lacks HLS) */
const TVW = { id: null, hls: null };
VIEWS.tv = async b => {
  const t = await api('tv'), ch = t.channels;
  if (!TVW.id || !ch.some(c => c.id === TVW.id)) TVW.id = ch.length ? ch[0].id : null;
  b.innerHTML = `<div class="ut-pl"><div class="ut-pl__main">
      <div class="ut-pl__stage"><video id="tvv" controls playsinline autoplay poster="${ICON('tv')}"></video></div>
      <div class="ut-pl__bar"><b id="tvt" class="ut-pl__title" translate="no"></b><span class="muted" id="tvn"></span></div>
      <div class="muted" id="tvm">${ch.length ? '' : ME.admin ? 'No channels yet: Media server → Channels → “New channel”.' : 'No channels set up yet.'}</div></div>
    <aside class="ut-pl__list" translate="no">${ch.map(c => `<button class="ut-pl__item" data-c="${c.id}">${c.profile === 'radio' ? '📻' : '📺'} ${esc(c.name)}</button>`).join('')}</aside></div>`;
  $$('[data-c]', b).forEach(x => x.onclick = () => { TVW.id = x.dataset.c; tvTune(b, ch); });
  CLEANUP.tv = () => { if (TVW.hls) { TVW.hls.destroy(); TVW.hls = null; } };
  if (TVW.id) tvTune(b, ch);
};
async function tvTune(b, ch) {
  const c = ch.find(x => x.id === TVW.id), v = $('#tvv', b), url = '/tv/' + c.id + '/index.m3u8';
  $$('[data-c]', b).forEach(x => x.toggleAttribute('aria-current', x.dataset.c === c.id));
  $('#tvt', b).textContent = c.name; $('#tvn', b).textContent = c.now ? '· ' + c.now : '';
  $('#tvm', b).textContent = UTI18N.tr('Tuning in …');
  if (TVW.hls) { TVW.hls.destroy(); TVW.hls = null; }
  const done = () => { $('#tvm', b).textContent = ''; };
  const bad = msg => { $('#tvm', b).textContent = msg; };
  try { await loadOnce('script', { src: '/desk/vendor/hls/hls.light.min.js' }); } catch (e) { }
  if (!window.Hls || !Hls.isSupported()) {     // iPhone/iPad Safari: no MSE, but HLS built in
    if (!v.canPlayType('application/vnd.apple.mpegurl')) return bad('hls.js is missing.');
    v.src = url; v.onplaying = done; v.onerror = () => bad(UTI18N.tr('The channel does not start.')); v.play().catch(() => { }); return;
  }
  const h = TVW.hls = new Hls({ liveSyncDurationCount: 2, manifestLoadingTimeOut: 25000, manifestLoadingMaxRetry: 2 });
  h.on(Hls.Events.MANIFEST_PARSED, () => { done(); v.play().catch(() => { }); });
  h.on(Hls.Events.ERROR, async (_e, x) => {
    if (!x.fatal) return;
    let msg = UTI18N.tr('The channel does not start.'), code = x.response && x.response.code;
    if (code) { try { const r = await fetch(url); code = r.status; msg = (await r.json()).error || msg; } catch (e) { } }
    bad(msg);
    // still preparing (durations being read): try again until it is ready
    if (code === 503 && /being prepared/.test(msg)) setTimeout(() => { if (wins.tv && TVW.id === c.id && TVW.hls === h) tvTune(b, ch); }, 5000);
  });
  h.loadSource(url); h.attachMedia(v);
}


/* ad filter (DNS, like Pi-hole) -------------------------------------------- */
VIEWS.adblock = async (b, sel = 'overview') => {
  const a = await api('adblock'), st = a.stats || { queries: 0, blocked: 0, percent: 0, clients: 0, top_blocked: [], top_allowed: [], top_clients: [], hist: [] };
  const n = x => (x || 0).toLocaleString(UTI18N.locale);
  const nav = sidebar('adblock', [['overview', 'Overview'], ['log', 'Log'], ['lists', 'Lists'], ['rules', 'Own rules'], ['setup', 'Setup']], sel);
  const top = (rows, act) => rows.length ? `<table class="ut-table"><tbody>${rows.map(r => `<tr><td translate="no" class="mono">${esc(r.name)}</td><td class="num">${n(r.n)}</td>${act ? `<td class="ut-rowbtns"><button class="ut-btn ut-btn--ghost ut-btn--sm" data-${act}="${esc(r.name)}">${act === 'al' ? 'Allow' : 'Block'}</button></td>` : ''}</tr>`).join('')}</tbody></table>` : '<p class="muted">No data yet.</p>';
  let main = '';
  if (sel === 'overview') {
    const mx = Math.max(1, ...st.hist.map(h => h[0]));
    main = `<div class="row"><h2 style="margin:0">Ad filter</h2><span class="ut-pill ${a.running ? 'ut-pill--ok' : a.active ? 'ut-pill--warn' : ''}">${a.running ? 'active' : a.active ? 'starting …' : 'off'}</span><span class="ut-spacer"></span>
        ${sw('abon', a.active, a.active ? 'on' : 'off')}</div>
      <p class="muted">Blocks ads and trackers for all devices in the home network that use the NAS as DNS server (see Setup). ${n(a.count)} blocked domains${a.updated ? ' · Lists from ' + esc(new Date(a.updated * 1000).toLocaleString(UTI18N.locale)) : ''}.</p>
      <div class="ut-media-stats ut-ab-stats">${[[n(st.queries), 'Queries (24 h)'], [n(st.blocked), 'blocked'], [st.percent + ' %', 'Share blocked'], [n(st.clients), 'Devices']].map(([v, l]) => `<div class="ut-card"><div class="ut-media-stat__n">${v}</div><div class="muted">${l}</div></div>`).join('')}</div>
      <div class="ut-section-title">Last 24 hours</div>
      <div class="ut-ab-hist">${st.hist.map(h => `<i title="${h[0]} / ${h[1]}"><b style="height:${100 * h[0] / mx}%"></b><em style="height:${100 * h[1] / mx}%"></em></i>`).join('')}</div>
      <div class="ut-ab-cols"><div><div class="ut-section-title">Most blocked</div>${top(st.top_blocked, 'al')}</div>
        <div><div class="ut-section-title">Most requested</div>${top(st.top_allowed, 'bl')}</div>
        <div><div class="ut-section-title">Devices</div>${top(st.top_clients)}</div></div>`;
  } else if (sel === 'log') {
    main = `<div class="row" style="gap:8px"><input class="ut-input" id="abq" placeholder="Filter by domain or device" style="flex:1">${sw('abbl', false, 'blocked only')}</div><div id="abl"><span class="ut-spinner"></span></div>`;
  } else if (sel === 'lists') {
    main = `<div class="row"><h2 style="margin:0">Block lists</h2><span class="ut-spacer"></span><button class="ut-btn ut-btn--sm" id="abup"${a.updating ? ' disabled' : ''}>${a.updating ? 'updating …' : 'Update now'}</button></div>
      <p class="muted">The lists are reloaded automatically every week. More lists block more, but also more likely something wanted; then “Allow” helps.</p>
      ${a.errors.length ? `<div class="ut-callout ut-callout--danger" translate="no">${a.errors.map(esc).join('<br>')}</div>` : ''}
      <table class="ut-table"><tbody>${a.lists.map((l, i) => `<tr><td><input type="checkbox" data-li="${i}"${l.on ? ' checked' : ''}></td><td><b translate="no">${esc(l.name)}</b><div class="muted mono" translate="no">${esc(l.url)}</div></td><td><button class="ut-btn ut-btn--ghost ut-btn--sm" data-lrm="${i}">Remove</button></td></tr>`).join('')}</tbody></table>
      <div class="row" style="gap:8px;margin-top:10px">${field('abln', 'Name')}${field('ablu', 'List address (hosts or domain format)', '', 'placeholder="https://…"')}</div>
      <div class="row" style="gap:8px"><button class="ut-btn" id="abla">Add list</button><button class="ut-btn ut-btn--primary" id="abls">Save</button></div>`;
  } else if (sel === 'rules') {
    main = `<h2>Own rules</h2><p class="muted">One domain per line. Blocked also covers all subdomains; allowed takes precedence over the lists.</p>
      <div class="ut-ab-cols ut-ab-cols--2"><div class="ut-field"><label for="abal">Always allow</label><textarea class="ut-input mono" id="abal" rows="12" translate="no">${esc(a.allow.join('\n'))}</textarea></div>
        <div class="ut-field"><label for="abbk">Always block</label><textarea class="ut-input mono" id="abbk" rows="12" translate="no">${esc(a.block.join('\n'))}</textarea></div></div>
      <button class="ut-btn ut-btn--primary" id="abrs">Save</button>`;
  } else {
    main = `<h2>Setup</h2>
      <p>For the filter to work, devices must ask the NAS as their DNS server. Easiest for all at once in the router:</p>
      <ol><li>Open the DNS settings for the home network in the router (FRITZ!Box: Home Network → Network → Network Settings → IPv4 Settings → “Local DNS server”).</li>
        <li>Enter the address of the NAS there: <b class="mono" translate="no">${esc(a.dns_ip || '?')}</b></li>
        <li>Reconnect the devices (Wi-Fi off/on); they get the new DNS server via DHCP.</li></ol>
      <div class="ut-callout">The NAS needs a fixed address for this (in the router “always assign the same IPv4 address” or Network → static IP). While the NAS is off, devices ask in vain until the router falls back to its own DNS; some routers do not.</div>
      <p class="muted">Single devices can also be switched without the router: enter the address above as DNS server in their network settings.</p>`;
  }
  b.innerHTML = nav + `<div class="ut-window__main">${main}</div>`;
  navBind(b, 'adblock');
  const reload = () => render('adblock', sel);
  const setRule = async (k, d) => { const cur = (await api('adblock'))[k]; if (!cur.includes(d)) await api('adblock/save', { [k]: cur.concat(d) }); toast(k === 'allow' ? 'Allowed' : 'Blocked', d); };
  const on = $('#abon', b); if (on) on.onchange = () => api('adblock/save', { active: on.checked }).then(() => { toast(on.checked ? 'Ad filter on' : 'Ad filter off'); setTimeout(reload, 1500); }).catch(fail);
  $$('[data-al]', b).forEach(x => x.onclick = () => setRule('allow', x.dataset.al).then(reload).catch(fail));
  $$('[data-bl]', b).forEach(x => x.onclick = () => setRule('block', x.dataset.bl).then(reload).catch(fail));
  if (sel === 'log') {
    const draw = async () => {
      const r = await api('adblock/log?' + new URLSearchParams({ q: $('#abq', b).value, blocked: $('#abbl', b).checked ? '1' : '', n: 300 }));
      $('#abl', b).innerHTML = r.rows.length ? `<table class="ut-table"><thead><tr><th>Time</th><th>Device</th><th>Domain</th><th>Typ</th><th></th></tr></thead><tbody>${r.rows.map(x => `<tr class="${x.status === 'blocked' ? 'ut-ab-blocked' : ''}">
        <td>${esc(new Date(x.t * 1000).toLocaleTimeString(UTI18N.locale))}</td><td class="mono" translate="no">${esc(x.client)}</td><td class="mono" translate="no">${esc(x.name)}</td><td translate="no">${esc(x.type)}</td>
        <td class="ut-rowbtns">${x.status === 'blocked' ? `<span class="ut-pill ut-pill--danger">blocked</span><button class="ut-btn ut-btn--ghost ut-btn--sm" data-al="${esc(x.name)}">Allow</button>` : `<button class="ut-btn ut-btn--ghost ut-btn--sm" data-bl="${esc(x.name)}">Block</button>`}</td></tr>`).join('')}</tbody></table>` : '<p class="muted">No queries.</p>';
      $$('[data-al]', b).forEach(x => x.onclick = () => setRule('allow', x.dataset.al).catch(fail));
      $$('[data-bl]', b).forEach(x => x.onclick = () => setRule('block', x.dataset.bl).catch(fail));
    };
    let tm; $('#abq', b).oninput = () => { clearTimeout(tm); tm = setTimeout(() => draw().catch(fail), 300); };
    $('#abbl', b).onchange = () => draw().catch(fail);
    await draw();
  }
  if (sel === 'lists') {
    const lists = a.lists.map(l => Object.assign({}, l));
    $$('[data-li]', b).forEach(x => x.onchange = () => { lists[+x.dataset.li].on = x.checked; });
    $$('[data-lrm]', b).forEach(x => x.onclick = () => api('adblock/save', { lists: lists.filter((_, i) => i !== +x.dataset.lrm) }).then(reload).catch(fail));
    $('#abla', b).onclick = () => { const u = $('#ablu', b).value.trim(); if (!u) return; api('adblock/save', { lists: lists.concat({ name: $('#abln', b).value.trim() || u, url: u, on: true }) }).then(() => api('adblock/update', {})).then(reload).catch(fail); };
    $('#abls', b).onclick = () => api('adblock/save', { lists }).then(() => api('adblock/update', {})).then(() => { toast('Saved', 'Loading lists …'); setTimeout(reload, 1500); }).catch(fail);
    $('#abup', b).onclick = () => api('adblock/update', {}).then(() => { toast('Loading lists …'); setTimeout(reload, 1500); }).catch(fail);
    if (a.updating) { const t = setTimeout(() => wins.adblock && reload(), 5000); CLEANUP.adblock = () => clearTimeout(t); }
  }
  if (sel === 'rules') {
    const lines = id => $(id, b).value.split(/\s+/).map(x => x.trim()).filter(Boolean);
    $('#abrs', b).onclick = () => save('adblock/save', { allow: lines('#abal'), block: lines('#abbk') }, 'adblock', 'rules');
  }
};
