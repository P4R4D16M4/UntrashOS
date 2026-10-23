#!/usr/bin/env node
/* PC test of the sound editor's renderer (usr/share/untrash/desk/sound-render.js).
 *   node image/tests/test_sound_render.js
 * The built-in event scores come from untrash-sound itself ("show"). */
'use strict';
const path = require('path'), { execFileSync } = require('child_process');
const R = path.join(__dirname, '..', 'rootfs');
const S = require(path.join(R, 'usr/share/untrash/desk/sound-render.js'));
let fails = 0;
const check = (n, ok) => { console.log((ok ? 'ok   ' : 'FAIL ') + n); if (!ok) fails++; };
const eq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// what the player hears from an old note list: tones, rests, and its 15 ms gap between two tones
const heard = notes => {
  const out = [];
  notes.forEach(([hz, ms, tie], i) => {
    const l = out[out.length - 1];
    if (!hz && l && !l[0]) l[1] += ms; else out.push([hz, ms]);
    const nx = notes[i + 1];
    if (hz && !tie && nx && nx[0]) out.push([0, S.GAP]);
  });
  return out;
};

const show = JSON.parse(execFileSync(path.join(R, 'usr/lib/untrash/untrash-sound'), ['show'], { env: Object.assign({}, process.env, { ZT_SOUND_USER: '/nonexistent' }) }));
for (const [ev, notes] of Object.entries(show.builtin)) {
  const r = S.render(S.fromNotes(notes, 1));
  check(ev + ': built-in score sounds the same from the editor', eq(heard(r), heard(notes)));
}
check('tempo 2 doubles every length', eq(S.render(S.fromNotes([[440, 100], [0, 50], [880, 100]], 2)), [[440, 200], [0, 100], [880, 200]]));

const s = S.blank();
s.patterns[0].notes = [{ t: 0, d: 250, hz: 523 }, { t: 250, d: 250, hz: 659 }];
check('touching notes: the 15 ms articulation rest lies inside the first note', eq(S.render(s), [[523, 235], [0, 15], [659, 250]]));
check('length on the grid: player time = 500 ms', S.total(S.render(s)) === 500);
s.arrangement = [{ p: 0, n: 3 }];
s.patterns[0].len = 1000;
const r3 = S.render(s);
const lp = S.blank(); lp.patterns[0].notes = [{ t: 0, d: 250, hz: 523 }, { t: 250, d: 250, hz: 659 }]; lp.arrangement = [{ p: 0, n: 2 }];
check('pattern x2 without a rest at its end: exactly 2 x 500 ms (articulation at the loop seam too)', S.total(S.render(lp)) === 1000);
check('pattern x3 with its length (rest at the end of each pass, not after the last)', S.total(r3) === 2500 && r3.filter(n => n[0] === 523).length === 3);

const one = mod => S.parts({ t: 0, d: 400, hz: 440, mod });
for (const [k, mod] of [['vibrato', { k: 'vibrato', depth: 1, rate: 6 }], ['slide', { k: 'slide', st: 12 }], ['fall', { k: 'fall' }], ['arpeggio', { k: 'arp', chord: 'major', ms: 50 }]]) {
  const p = one(mod);
  const sum = p.reduce((a, x) => a + x[1], 0);
  check(k + ': parts tied, last one ends, 400 ms in total, in 100..4000 Hz',
    sum === 400 && p.slice(0, -1).every(x => x[2] === 1) && p[p.length - 1][2] === 0 && p.every(x => x[0] >= 100 && x[0] <= 4000) && p.length > 2);
}
check('slide +12 ends within 2 % of 880 Hz', Math.abs(one({ k: 'slide', st: 12 }).slice(-1)[0][0] - 880) < 18);
check('arpeggio major cycles 440, 554, 659, 880', eq(one({ k: 'arp', chord: 'major', ms: 50 }).slice(0, 4).map(x => x[0]), [440, 554, 659, 880]));
const st = one({ k: 'staccato', g: 0.5 });
check('staccato 50 %: 200 ms tone, 200 ms rest', eq(st, [[440, 200, 0], [0, 200, 0]]));
check('frequencies clamp to what the buzzer plays', one({ k: 'slide', st: 48 }).every(x => x[0] <= 4000));

check('C major rows: 37 notes in range, high first', S.rows(S.blank()).length === 37 && S.rows(S.blank())[0] > S.rows(S.blank())[36]);
check('chromatic rows: every semitone (64)', S.rows(Object.assign(S.blank(), { scale: 'chromatic' })).length === 64);
check('note names: 60 = C4, 69 = A4', S.name(60) === 'C4' && S.name(69) === 'A4' && Math.round(S.midi2hz(69)) === 440);
check('step: 120 BPM, 1/16 = 125 ms', S.stepMs(S.blank()) === 125);
const m = S.motif('chime', S.blank(), 72, 0);
check('motif chime: 4 notes on the grid, in the scale', m.length === 4 && m.every(n => n.t % 125 === 0) &&
  m.every(n => S.rows(S.blank()).includes(Math.round(S.hz2midi(n.hz)))));
check('limits: 4001 notes or more than 60 s do not fit', !S.fits(new Array(4001).fill([440, 10])) && !S.fits([[440, 30000], [440, 30001]]) && S.fits([[440, 1000]]));
console.log('SOUND RENDER TEST ' + (fails ? 'FAIL' : 'PASS') + ' (' + fails + ' failures)');
process.exit(fails ? 1 : 0);
