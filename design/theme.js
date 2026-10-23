/* UntrashOS appearance: theme, colour vision, motion (design/untrash.css, themes).
 *
 * Load it in <head> before the stylesheet paints: it sets data-theme,
 * data-cvd and data-motion on <html> at once.  Preferences:
 *   theme  auto | dark | light | contrast   (auto: the system's light/dark
 *          and "more contrast" setting, followed live)
 *   cvd    none | protan | deutan | tritan | achroma
 *   motion auto | reduce
 * The Desk keeps them per user on the NAS (/api/prefs) and calls
 * UTTHEME.set(); this browser keeps a copy (localStorage "ut-theme") so the
 * sign-in page and the next load show the same theme before anyone signs in.
 */
(function () {
  'use strict';
  const DEF = { theme: 'dark', cvd: 'none', motion: 'auto' };
  const OK = { theme: ['auto', 'dark', 'light', 'contrast'], cvd: ['none', 'protan', 'deutan', 'tritan', 'achroma'], motion: ['auto', 'reduce'] };
  const mq = q => (window.matchMedia ? window.matchMedia(q) : { matches: false, addEventListener() { } });
  const dark = mq('(prefers-color-scheme: dark)'), more = mq('(prefers-contrast: more)');
  let cur = Object.assign({}, DEF);

  const clean = p => {
    const o = Object.assign({}, DEF);
    for (const k in OK) if (p && OK[k].includes(p[k])) o[k] = p[k];
    return o;
  };
  const resolved = () => cur.theme !== 'auto' ? cur.theme : more.matches ? 'contrast' : dark.matches ? 'dark' : 'light';

  function apply() {
    const h = document.documentElement;
    h.dataset.theme = resolved();
    if (cur.cvd === 'none') delete h.dataset.cvd; else h.dataset.cvd = cur.cvd;
    if (cur.motion === 'reduce') h.dataset.motion = 'reduce'; else delete h.dataset.motion;
  }

  try { cur = clean(JSON.parse(localStorage.getItem('ut-theme') || 'null')); } catch (e) { }
  apply();
  const live = () => { if (cur.theme === 'auto') apply(); };
  dark.addEventListener('change', live);
  more.addEventListener('change', live);

  window.UTTHEME = {
    options: OK,
    get prefs() { return Object.assign({}, cur); },
    get theme() { return resolved(); },
    set(p) {
      cur = clean(Object.assign({}, cur, p));
      try { localStorage.setItem('ut-theme', JSON.stringify(cur)); } catch (e) { }
      apply();
      return cur;
    },
  };
})();
