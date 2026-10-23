/* UntrashOS sound editor: score model and renderer (Desk "Sounds").
 *
 * A score is what the editor shows:
 *   { v: 1, bpm, grid, key, scale,
 *     patterns: [{ name, len?, notes: [{ t, d, hz, mod? }] }],   t, d in ms
 *     arrangement: [{ p: pattern index, n: repeats }] }
 * mod = { k: 'none' | 'staccato' | 'vibrato' | 'slide' | 'fall' | 'arp', ... }.
 *
 * render(score) gives what the buzzer plays (untrash-sound): [[hz, ms], ...]
 * with [hz, ms, 1] for parts tied into the next one (slides, vibrato,
 * arpeggios).  The buzzer has one square-wave voice, 100..4000 Hz.  Between
 * two touching notes the renderer puts the 15 ms articulation rest itself, so
 * the timing is exactly the grid's.  Used by desk.js and, without a browser,
 * by image/tests/test_sound_render.js.
 */
(function (root) {
  'use strict';
  const MIN_HZ = 100, MAX_HZ = 4000, GAP = 15, MOD_STEP = 20, MAX_NOTES = 4000, MAX_MS = 60000;
  const KEYS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
  const SCALES = {
    major: [0, 2, 4, 5, 7, 9, 11], minor: [0, 2, 3, 5, 7, 8, 10], pentatonic: [0, 2, 4, 7, 9],
    'minor pentatonic': [0, 3, 5, 7, 10], blues: [0, 3, 5, 6, 7, 10], chromatic: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
  };
  const CHORDS = { major: [0, 4, 7, 12], minor: [0, 3, 7, 12], fifth: [0, 7, 12], octave: [0, 12] };
  const LOW = 44, HIGH = 107;          // MIDI range inside 100..4000 Hz (G#2 .. B7)

  const midi2hz = m => 440 * Math.pow(2, (m - 69) / 12);
  const hz2midi = hz => 69 + 12 * Math.log2(hz / 440);
  const name = m => KEYS[((m % 12) + 12) % 12] + (Math.floor(m / 12) - 1);
  const clampHz = hz => Math.round(Math.min(MAX_HZ, Math.max(MIN_HZ, hz)));
  const stepMs = s => 60000 / s.bpm * 4 / s.grid;          // grid 16 = sixteenth notes

  /* MIDI notes of the score's key and scale inside the buzzer's range, high first */
  function rows(s) {
    const k = KEYS.indexOf(s.key), deg = SCALES[s.scale] || SCALES.major, out = [];
    for (let m = HIGH; m >= LOW; m--) if (deg.includes(((m - k) % 12 + 12) % 12)) out.push(m);
    return out;
  }

  function blank() {
    return { v: 1, bpm: 120, grid: 16, key: 'C', scale: 'major', patterns: [{ name: 'A', notes: [] }], arrangement: [{ p: 0, n: 1 }] };
  }

  /* the old note list ([hz, ms], tempo, the player's 15 ms gap) as one pattern */
  function fromNotes(notes, tempo) {
    const s = blank(), p = s.patterns[0];
    let t = 0;
    (notes || []).forEach(([hz, ms, tie], i) => {
      const d = Math.max(1, Math.round(ms * (tempo || 1)));
      if (hz) p.notes.push({ t, d, hz });
      t += d;
      const nx = notes[i + 1];
      if (hz && !tie && nx && nx[0]) t += GAP;
    });
    p.len = t;
    // the key and scale that hold every note (major first, then minor), else chromatic
    const pcs = new Set(p.notes.map(n => ((Math.round(hz2midi(n.hz)) % 12) + 12) % 12));
    found: for (const sc of ['major', 'minor']) {
      for (const k of [0, 7, 5, 2, 10, 9, 3, 4, 8, 11, 1, 6]) {     // C, G, F, D, Bb, A, Eb, ... (common keys first)
        if ([...pcs].every(pc => SCALES[sc].includes((pc - k + 12) % 12))) { s.key = KEYS[k]; s.scale = sc; break found; }
      }
      if (sc === 'minor') s.scale = 'chromatic';
    }
    return s;
  }

  const patLen = p => Math.max(p.len || 0, ...p.notes.map(n => n.t + n.d), 0);

  /* one note as buzzer parts [hz, ms, tie]; the last part is not tied */
  function parts(n) {
    const m = n.mod || { k: 'none' }, d = Math.max(1, Math.round(n.d)), hz = n.hz;
    const sweep = f => {           // f(t in ms) -> hz, in MOD_STEP pieces
      const out = [];
      for (let t = 0; t < d; t += MOD_STEP) { const l = Math.min(MOD_STEP, d - t); out.push([clampHz(f(t + l / 2)), l, 1]); }   // pitch at the middle of each piece
      return out;
    };
    let out;
    switch (m.k) {
      case 'staccato': {
        const g = Math.min(0.8, Math.max(0.1, m.g ?? 0.5)), on = Math.max(10, Math.round(d * (1 - g)));
        out = [[clampHz(hz), on, 0]];
        if (d - on > 0) out.push([0, d - on, 0]);
        return out;
      }
      case 'vibrato': {
        const dep = m.depth ?? 0.5, rate = m.rate ?? 6;
        out = sweep(t => hz * Math.pow(2, dep / 12 * Math.sin(2 * Math.PI * rate * t / 1000)));
        break;
      }
      case 'slide': {
        const st = m.st ?? 12;
        out = sweep(t => hz * Math.pow(2, st / 12 * t / d));
        break;
      }
      case 'fall':
        out = sweep(t => t < d * 0.6 ? hz : hz * Math.pow(2, -12 / 12 * (t - d * 0.6) / (d * 0.4)));
        break;
      case 'arp': {
        const ch = CHORDS[m.chord] || CHORDS.major, sp = Math.max(30, m.ms ?? 60);
        out = [];
        for (let t = 0, i = 0; t < d; t += sp, i++) out.push([clampHz(hz * Math.pow(2, ch[i % ch.length] / 12)), Math.min(sp, d - t), 1]);
        break;
      }
      default:
        out = [[clampHz(hz), d, 0]];
    }
    // equal neighbours become one part; the last part ends the note
    const merged = [];
    for (const x of out) {
      const l = merged[merged.length - 1];
      if (l && l[0] === x[0] && l[2]) l[1] += x[1]; else merged.push(x.slice());
    }
    merged[merged.length - 1][2] = 0;
    return merged;
  }

  function renderPattern(p, out) {
    const notes = p.notes.slice().sort((a, b) => a.t - b.t);
    let cur = 0;
    notes.forEach((n, i) => {
      if (n.t > cur) out.push([0, n.t - cur, 0]);
      const ps = parts(n), next = notes[i + 1], last = ps[ps.length - 1];
      // a note that runs straight into the next one gets the player's articulation
      // rest inside its own length, so the grid timing holds
      if (next && next.t <= n.t + n.d + 0.5 && last[0] && last[1] > GAP + 10) {
        last[1] -= GAP;
        ps.push([0, GAP, 0]);
      }
      out.push(...ps);
      cur = Math.max(cur, n.t + n.d);
    });
    const len = patLen(p);
    if (len > cur) out.push([0, len - cur, 0]);
  }

  function render(s) {
    const raw = [];
    for (const c of s.arrangement || []) {
      const p = s.patterns[c.p];
      if (!p) continue;
      for (let r = 0; r < Math.max(1, c.n || 1); r++) renderPattern(p, raw);
    }
    const out = [];
    for (const [hz, ms0, tie] of raw) {
      const ms = Math.round(ms0);
      if (ms <= 0) continue;
      const l = out[out.length - 1];
      if (l && !hz && !l[0]) { l[1] += ms; continue; }          // rests merge
      out.push(tie && hz ? [hz, ms, 1] : [hz, ms]);
    }
    // two touching tones across a pattern boundary: the articulation rest goes
    // inside the first one too, so repeats keep the grid timing
    for (let i = 0; i + 1 < out.length; i++) {
      const [hz, ms, tie] = out[i];
      if (hz && !tie && out[i + 1][0] && ms > GAP + 10) { out[i] = [hz, ms - GAP]; out.splice(i + 1, 0, [0, GAP]); i++; }
    }
    while (out.length && !out[out.length - 1][0]) out.pop();    // no rest at the end
    while (out.length && !out[0][0]) out.shift();               // nor at the start
    return out;
  }

  const total = notes => notes.reduce((a, n) => a + n[1], 0) + notes.reduce((a, n, i) =>
    a + (n[0] && !n[2] && notes[i + 1] && notes[i + 1][0] ? GAP : 0), 0);
  const fits = notes => notes.length <= MAX_NOTES && total(notes) <= MAX_MS;

  /* motifs for the palette: notes relative to a root (MIDI) on the score's grid */
  function motif(kind, s, root, t0) {
    const r = rows(s).slice().reverse(), i0 = Math.max(0, r.findIndex(m => m >= root));
    const at = k => r[Math.min(r.length - 1, Math.max(0, i0 + k))];
    const st = stepMs(s), mk = (k, t, len, mod) => ({ t: t0 + t * st, d: len * st, hz: midi2hz(at(k)), mod });
    switch (kind) {
      case 'chime': return [mk(0, 0, 1), mk(2, 1, 1), mk(4, 2, 1), mk(7, 3, 3)];
      case 'rise': return [0, 1, 2, 3, 4].map(k => mk(k, k, 1));
      case 'fall': return [4, 3, 2, 1, 0].map((k, i) => mk(k, i, 1));
      case 'alarm': return [0, 1, 2, 3].map(i => mk(i % 2 ? 3 : 0, i * 2, 2));
      case 'trill': return [mk(0, 0, 4, { k: 'vibrato', depth: 1, rate: 10 })];
      case 'beep': return [mk(0, 0, 1), mk(0, 2, 1)];
      default: return [];
    }
  }

  const api = { MIN_HZ, MAX_HZ, GAP, MAX_NOTES, MAX_MS, KEYS, SCALES, CHORDS, midi2hz, hz2midi, name, rows, stepMs, blank, fromNotes, patLen, parts, render, total, fits, motif };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.UTSOUND = api;
})(typeof window !== 'undefined' ? window : this);
