/* UntrashOS UI translation (Untrash Desk and installer), German is the source.
 *
 * Catalogs /ut/i18n/<lang>.json: {"text": {"<German>": "<translation>"}}.
 * Every visible text is translated where it appears (MutationObserver): text
 * nodes and the title/placeholder/aria-label/alt attributes.  Order:
 *   1. the whole text (trimmed) is a catalog key
 *   2. a key with %s/%d (backend messages) matches as a pattern
 *   3. otherwise every catalog phrase (2+ words) inside the text is replaced
 * Nothing inside [translate="no"] (file, share and user names, logs, the
 * terminal) is touched.  Language: ?lang=, localStorage "ut-lang", the
 * system default (<html data-lang>), the browser, German.
 */
(function () {
  'use strict';
  const LANGS = { de: 'Deutsch', en: 'English', fr: 'Français' };
  const SKIP = 'script,style,textarea,code,[translate="no"],.xterm';
  const ATTRS = ['title', 'placeholder', 'aria-label', 'alt'];
  let lang = 'de', exact = null, pats = [], frag = null;
  const done = new WeakMap();

  const pick = () => {
    const q = new URLSearchParams(location.search).get('lang');
    let st = null; try { st = localStorage.getItem('ut-lang'); } catch (e) { }
    const sys = document.documentElement.dataset.lang;
    const nav = (navigator.language || 'de').slice(0, 2);
    return [q, st, sys, nav, 'de'].find(l => l && LANGS[l]);
  };
  const reEsc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

  function build(cat) {
    exact = new Map(Object.entries(cat.text || {}));
    pats = []; const phrases = [];
    for (const [k, v] of exact) {
      if (/%(\.\d)?[sdf]/.test(k)) {
        pats.push([new RegExp('^' + k.split(/%(?:\.\d)?[sdf]/).map(reEsc).join('(.+?)') + '$'), v]);
      } else if (k.length >= 3) phrases.push(k);   // words too: "120 GB frei" (data is translate="no")
    }
    phrases.sort((a, b) => b.length - a.length);
    // word boundaries only where the phrase itself starts/ends with a letter or digit
    const edge = p => (/^[\p{L}\p{N}]/u.test(p) ? '(?<![\\p{L}\\p{N}])' : '') + reEsc(p) + (/[\p{L}\p{N}]$/u.test(p) ? '(?![\\p{L}\\p{N}])' : '');
    frag = phrases.length ? new RegExp(phrases.map(edge).join('|'), 'gu') : null;
  }

  function tr(s) {
    if (!exact || !s || !/\p{L}/u.test(s)) return s;
    const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(s), core = m[2];
    let out = exact.get(core);
    if (out === undefined) {
      for (const [re, v] of pats) {
        const g = re.exec(core);
        // %1, %2 … when a language needs another order, else in order
        if (g) { let i = 1; out = /%\d/.test(v) ? v.replace(/%(\d)/g, (_, n) => g[+n]) : v.replace(/%(\.\d)?[sdf]/g, () => g[i++]); break; }
      }
    }
    if (out === undefined && frag) out = core.replace(frag, p => exact.has(p) ? exact.get(p) : p);
    return m[1] + (out === undefined ? core : out) + m[3];
  }

  // a textarea's content is the user's, but its placeholder is UI text
  function ph(n) {
    if (n.tagName !== 'TEXTAREA' || !n.hasAttribute('placeholder') || n.closest('[translate="no"]')) return;
    const v = n.getAttribute('placeholder'), t = tr(v);
    if (t !== v) n.setAttribute('placeholder', t);
  }

  function node(n) {
    if (!exact) return;
    if (n.nodeType === 3) {
      const p = n.parentElement;
      if (!p || p.closest(SKIP)) return;
      if (done.get(n) === n.data) return;
      const t = tr(n.data);
      if (t !== n.data) n.data = t;
      done.set(n, n.data);
    } else if (n.nodeType === 1) {
      ph(n);
      if (n.closest(SKIP)) return;
      for (const a of ATTRS) if (n.hasAttribute(a)) { const v = n.getAttribute(a), t = tr(v); if (t !== v) n.setAttribute(a, t); }
      if ((n.tagName === 'INPUT' && /^(button|submit)$/.test(n.type)) && n.value) n.value = tr(n.value);
      const w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT,
        { acceptNode: c => c.nodeType === 1 && c.matches(SKIP) ? (ph(c), NodeFilter.FILTER_REJECT) : NodeFilter.FILTER_ACCEPT });
      for (let c = w.nextNode(); c; c = w.nextNode()) {
        if (c.nodeType === 3) node(c);
        else for (const a of ATTRS) if (c.hasAttribute(a)) { const v = c.getAttribute(a), t = tr(v); if (t !== v) c.setAttribute(a, t); }
      }
    }
  }

  const obs = new MutationObserver(ms => {
    for (const m of ms) {
      if (m.type === 'characterData') node(m.target);
      else if (m.type === 'attributes') node(m.target);
      else m.addedNodes.forEach(node);
    }
  });

  async function set(l, remember) {
    lang = LANGS[l] ? l : 'de';
    if (remember) try { localStorage.setItem('ut-lang', lang); } catch (e) { }
    document.documentElement.lang = lang;
    if (lang === 'de') { exact = null; return; }
    try { build(await (await fetch('/ut/i18n/' + lang + '.json', { cache: 'no-cache' })).json()); }
    catch (e) { exact = null; return; }
    if (document.body) node(document.body);
  }

  window.UTI18N = {
    langs: LANGS, tr, get lang() { return lang; },
    get locale() { return { de: 'de-DE', en: 'en-GB', fr: 'fr-FR' }[lang] || 'de-DE'; },
    // switch: German needs the original texts again, so the page reloads
    set: l => { try { if (l) localStorage.setItem('ut-lang', l); else localStorage.removeItem('ut-lang'); } catch (e) { } location.reload(); },
    get own() { try { return localStorage.getItem('ut-lang') || ''; } catch (e) { return ''; } },
    ready: (async () => {
      await set(pick(), false);
      const go = () => { if (document.body) { node(document.body); obs.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS }); } };
      if (document.body) go(); else document.addEventListener('DOMContentLoaded', go);
    })(),
  };
})();
