#!/usr/bin/env node
/* Test of the Desk's QR encoder (usr/share/untrash/desk/qr.js):
 * reference values from ISO/IEC 18004 and every symbol decoded again by the
 * separate reader image/tests/qr_decode.py.  Run: node image/tests/test_qr.js */
'use strict';
const path = require('path'), cp = require('child_process');
const Q = require(path.join(__dirname, '../rootfs/usr/share/untrash/desk/qr.js'));
let fails = 0;
const check = (name, ok) => { console.log((ok ? 'ok   ' : 'FAIL ') + name); if (!ok) fails++; };
const bin = (v, n) => v.toString(2).padStart(n, '0');

// Reed-Solomon: the 1-Q "HELLO WORLD" example (data and EC codewords from the standard's worked example)
check('RS: 1-Q HELLO WORLD EC codewords', Q.rs([32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17], 10).join(',')
  === '196,35,39,119,235,215,231,226,93,23');
// format information table (annex C), level index 0..3 = L M Q H
const FMT = { '0,0': '111011111000100', '0,1': '111001011110011', '0,2': '111110110101010', '0,3': '111100010011101',
  '0,4': '110011000101111', '0,5': '110001100011000', '0,6': '110110001000001', '0,7': '110100101110110',
  '1,0': '101010000010010', '1,1': '101000100100101', '2,0': '011010101011111', '3,0': '001011010001001' };
check('format bits match the table', Object.entries(FMT).every(([k, want]) => { const [e, m] = k.split(',').map(Number); return bin(Q.formatBits(e, m), 15) === want; }));
check('version bits 7 and 40 (annex D)', bin(Q.versionBits(7), 18) === '000111110010010100' && bin(Q.versionBits(40), 18) === '101000110001101001');
// byte capacities (table 7): data codewords minus the segment header
const CAP = { '1,0': 17, '1,1': 14, '1,2': 11, '1,3': 7, '2,1': 26, '10,3': 119, '20,0': 858, '40,0': 2953, '40,1': 2331, '40,2': 1663, '40,3': 1273 };
check('byte capacities match the table', Object.entries(CAP).every(([k, want]) => { const [v, e] = k.split(',').map(Number); return Q.dataCodewords(v, e) - (v < 10 ? 2 : 3) === want; }));
check('alignment positions 7, 32, 40 (annex E)', Q.alignPositions(7).join() === '6,22,38' && Q.alignPositions(32).join() === '6,34,60,86,112,138'
  && Q.alignPositions(40).join() === '6,30,58,86,114,142,170');

const decode = q => {
  const r = cp.spawnSync('python3', [path.join(__dirname, 'qr_decode.py')], { input: JSON.stringify(q.modules.map(r => r.map(Number))) });
  try { return JSON.parse(r.stdout.toString()); } catch (e) { return { error: r.stdout.toString().trim() }; }
};
const texts = ['UntrashOS', 'x', 'Grüße aus dem Keller ✓',
  'eyJ2IjoxLCJpIjoiMGExYjJjM2QiLCJzIjoiMDAxMTIyMzM0NDU1NjY3Nzg4OTlhYWJiY2NkZGVlZmYiLCJtIjoiZmVlZGZhY2UxMjM0NTY3OCIsIm4iOiJob21lIiwiaCI6WyIxOTIuMC4yLjEwIl0sInAiOjczNDEsImUiOjE3OTI4NzYwMDAsImsiOiJhcHAifQ',
  'A'.repeat(300), 'B'.repeat(1200), 'Z'.repeat(2331)];
for (const t of texts) {
  for (const ecl of ['L', 'M', 'Q', 'H']) {
    let q;
    try { q = Q.encode(t, ecl); } catch (e) { if (t.length > 1273) continue; throw e; }
    const d = decode(q);
    check(`decode ${ecl} v${q.version} mask ${q.mask} (${t.length} chars)`, d.text === t && d.level === ecl && d.version === q.version || (console.log('     ', d.error), false));
  }
}
// every mask decodes (the penalty choice is not the only one tested)
for (let m = 0; m < 8; m++) { const q = Q.encode('mask test ' + m, 'M', m); check('mask ' + m, decode(q).text === 'mask test ' + m && q.mask === m); }
// every version from 1 to 40 at level M
let allv = true;
for (let v = 1; v <= 40; v++) {
  const n = Q.dataCodewords(v, 1) - (v < 10 ? 2 : 3), q = Q.encode('v'.repeat(n), 'M');
  if (q.version !== v || decode(q).text !== 'v'.repeat(n)) { allv = false; console.log('      version', v, decode(q).error); }
}
check('versions 1..40 at full capacity decode', allv);
{ const q = Q.encode('UntrashOS pairing', 'M'), y = q.size - 1, x = q.size - 1;      // bottom-right corner: always data
  q.modules[y][x] = !q.modules[y][x];
  check('negative: one flipped data module is caught', /syndromes/.test(decode(q).error || ''));
  const r = Q.encode('UntrashOS pairing', 'M'); r.modules[0][8] = !r.modules[0][8];
  check('negative: a broken format copy is caught', !!decode(r).error); }
let tooLong = false;
try { Q.encode('x'.repeat(2954), 'L'); } catch (e) { tooLong = true; }
check('too long text refused', tooLong);
check('svg: quiet zone and only black on white', /viewBox="0 0 29 29"/.test(Q.svg('x', 'M')) && /fill="#000"/.test(Q.svg('x')));
console.log(`QR TEST ${fails ? 'FAIL' : 'PASS'} (${fails} failures)`);
process.exit(fails ? 1 : 0);
