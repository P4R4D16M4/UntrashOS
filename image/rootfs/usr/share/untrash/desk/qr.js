/* UntrashOS QR code encoder (ISO/IEC 18004), byte mode, versions 1..40.
 *
 *   UTQR.encode(text, ecl = 'M') -> { size, version, mask, modules: [[bool]] }
 *   UTQR.svg(text, ecl)          -> an SVG string (dark modules, 4-module quiet zone)
 *
 * Used by the Desk to show UntrashApp pairing invitations; no network, no
 * library.  The internals (rs, formatBits, versionBits) are exported for
 * image/tests/test_qr.js, which checks them against the standard's tables
 * and decodes every symbol again with image/tests/qr_decode.py.
 */
(function (root) {
  'use strict';
  const ECL = { L: 0, M: 1, Q: 2, H: 3 }, FORMAT_ECL = [1, 0, 3, 2];
  // per version (index 1..40): EC codewords per block, number of blocks (ISO 18004 table 9)
  const ECC_PER_BLOCK = [
    [-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    [-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    [-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30]];
  const BLOCKS = [
    [-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
    [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
    [-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
    [-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81]];

  /* modules that carry data and EC codewords (and remainder bits) */
  function rawModules(v) {
    let r = (16 * v + 128) * v + 64;
    if (v >= 2) { const n = Math.floor(v / 7) + 2; r -= (25 * n - 10) * n - 55; if (v >= 7) r -= 36; }
    return r;
  }
  const dataCodewords = (v, e) => Math.floor(rawModules(v) / 8) - ECC_PER_BLOCK[e][v] * BLOCKS[e][v];

  /* GF(256), polynomial x^8+x^4+x^3+x^2+1 */
  function gmul(a, b) {
    let z = 0;
    for (let i = 7; i >= 0; i--) { z = (z << 1) ^ ((z >>> 7) * 0x11d); z ^= ((b >>> i) & 1) * a; }
    return z & 0xff;
  }
  /* Reed-Solomon EC codewords of DATA (array of bytes), DEG of them */
  function rs(data, deg) {
    const div = new Array(deg).fill(0); div[deg - 1] = 1;
    let r = 1;
    for (let i = 0; i < deg; i++) {
      for (let j = 0; j < deg; j++) { div[j] = gmul(div[j], r); if (j + 1 < deg) div[j] ^= div[j + 1]; }
      r = gmul(r, 2);
    }
    const out = new Array(deg).fill(0);
    for (const b of data) {
      const f = b ^ out.shift(); out.push(0);
      for (let i = 0; i < deg; i++) out[i] ^= gmul(div[i], f);
    }
    return out;
  }
  function formatBits(e, mask) {
    const d = (FORMAT_ECL[e] << 3) | mask;
    let r = d;
    for (let i = 0; i < 10; i++) r = (r << 1) ^ ((r >>> 9) * 0x537);
    return ((d << 10) | r) ^ 0x5412;
  }
  function versionBits(v) {
    let r = v;
    for (let i = 0; i < 12; i++) r = (r << 1) ^ ((r >>> 11) * 0x1f25);
    return (v << 12) | r;
  }
  function alignPositions(v) {
    if (v === 1) return [];
    const n = Math.floor(v / 7) + 2, size = v * 4 + 17;
    const step = v === 32 ? 26 : Math.ceil((v * 4 + 4) / (n * 2 - 2)) * 2;
    const out = [6];
    for (let p = size - 7; out.length < n; p -= step) out.splice(1, 0, p);
    return out;
  }
  const MASKS = [
    (x, y) => (x + y) % 2 === 0, (x, y) => y % 2 === 0, (x, y) => x % 3 === 0, (x, y) => (x + y) % 3 === 0,
    (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0, (x, y) => x * y % 2 + x * y % 3 === 0,
    (x, y) => (x * y % 2 + x * y % 3) % 2 === 0, (x, y) => ((x + y) % 2 + x * y % 3) % 2 === 0];

  function utf8(text) {
    return Array.from(unescape(encodeURIComponent(text)), c => c.charCodeAt(0));
  }

  /* codewords of the symbol: data in blocks, then EC, interleaved */
  function codewords(bytes, v, e) {
    const bits = [], put = (val, n) => { for (let i = n - 1; i >= 0; i--) bits.push((val >>> i) & 1); };
    const cap = dataCodewords(v, e) * 8;
    put(4, 4); put(bytes.length, v < 10 ? 8 : 16);
    bytes.forEach(b => put(b, 8));
    put(0, Math.min(4, cap - bits.length));
    put(0, (8 - bits.length % 8) % 8);
    for (let p = 0xec; bits.length < cap; p ^= 0xec ^ 0x11) put(p, 8);
    const data = [];
    for (let i = 0; i < bits.length; i += 8) data.push(bits.slice(i, i + 8).reduce((a, b) => a * 2 + b, 0));
    const nb = BLOCKS[e][v], ecl = ECC_PER_BLOCK[e][v], raw = Math.floor(rawModules(v) / 8);
    const nshort = nb - raw % nb, shortLen = Math.floor(raw / nb);
    const blocks = [];
    for (let i = 0, k = 0; i < nb; i++) {
      const n = shortLen - ecl + (i < nshort ? 0 : 1), d = data.slice(k, k + n);
      k += n;
      blocks.push({ d, e: rs(d, ecl) });
    }
    const out = [];
    for (let i = 0; i < shortLen - ecl + 1; i++) blocks.forEach(b => { if (i < b.d.length) out.push(b.d[i]); });
    for (let i = 0; i < ecl; i++) blocks.forEach(b => out.push(b.e[i]));
    return out;
  }

  function penalty(m) {
    const n = m.length;
    let p = 0, dark = 0;
    const line = get => {           // runs of 5+ and finder-like 1:1:3:1:1 with 4 light modules
      let run = 1, s = '';
      for (let i = 0; i < n; i++) {
        s += get(i) ? '1' : '0';
        if (i && get(i) === get(i - 1)) { run++; if (run === 5) p += 3; else if (run > 5) p++; } else run = 1;
      }
      for (const pat of ['10111010000', '00001011101']) for (let i = s.indexOf(pat); i >= 0; i = s.indexOf(pat, i + 1)) p += 40;
    };
    for (let y = 0; y < n; y++) line(x => m[y][x]);
    for (let x = 0; x < n; x++) line(y => m[y][x]);
    for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
      if (m[y][x]) dark++;
      if (x + 1 < n && y + 1 < n && m[y][x] === m[y][x + 1] && m[y][x] === m[y + 1][x] && m[y][x] === m[y + 1][x + 1]) p += 3;
    }
    return p + Math.floor(Math.abs(dark * 20 - n * n * 10) / (n * n)) * 10;
  }

  function encode(text, eclName = 'M', forceMask) {
    const e = ECL[eclName], bytes = utf8(text);
    let v = 1;
    while (v <= 40 && bytes.length + (v < 10 ? 2 : 3) > dataCodewords(v, e)) v++;
    if (v > 40) throw new Error('too long for a QR code');
    const size = v * 4 + 17;
    const mod = Array.from({ length: size }, () => new Array(size).fill(false));
    const fn = Array.from({ length: size }, () => new Array(size).fill(false));
    const set = (x, y, d) => { mod[y][x] = d; fn[y][x] = true; };
    for (let i = 0; i < size; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
    const finder = (cx, cy) => {
      for (let dy = -4; dy <= 4; dy++) for (let dx = -4; dx <= 4; dx++) {
        const x = cx + dx, y = cy + dy, d = Math.max(Math.abs(dx), Math.abs(dy));
        if (x >= 0 && x < size && y >= 0 && y < size) set(x, y, d !== 2 && d !== 4);
      }
    };
    finder(3, 3); finder(size - 4, 3); finder(3, size - 4);
    const al = alignPositions(v), na = al.length;
    for (let i = 0; i < na; i++) for (let j = 0; j < na; j++) {
      if ((i === 0 && j === 0) || (i === 0 && j === na - 1) || (i === na - 1 && j === 0)) continue;
      for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) set(al[i] + dx, al[j] + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
    }
    const drawFormat = mask => {
      const b = formatBits(e, mask), bit = i => ((b >>> i) & 1) === 1;
      for (let i = 0; i <= 5; i++) set(8, i, bit(i));
      set(8, 7, bit(6)); set(8, 8, bit(7)); set(7, 8, bit(8));
      for (let i = 9; i < 15; i++) set(14 - i, 8, bit(i));
      for (let i = 0; i < 8; i++) set(size - 1 - i, 8, bit(i));
      for (let i = 8; i < 15; i++) set(8, size - 15 + i, bit(i));
      set(8, size - 8, true);                      // the dark module
    };
    drawFormat(0);                                 // reserves the format areas
    if (v >= 7) {
      const b = versionBits(v);
      for (let i = 0; i < 18; i++) { const d = ((b >>> i) & 1) === 1, a = size - 11 + i % 3, c = Math.floor(i / 3); set(a, c, d); set(c, a, d); }
    }
    const cw = codewords(bytes, v, e);
    let k = 0;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < size; vert++) for (let j = 0; j < 2; j++) {
        const x = right - j, up = ((right + 1) & 2) === 0, y = up ? size - 1 - vert : vert;
        if (!fn[y][x] && k < cw.length * 8) { mod[y][x] = ((cw[k >>> 3] >>> (7 - (k & 7))) & 1) === 1; k++; }
      }
    }
    const apply = mask => { for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) if (!fn[y][x] && MASKS[mask](x, y)) mod[y][x] = !mod[y][x]; };
    let best = forceMask, bestP = Infinity;
    if (best === undefined) {
      for (let m = 0; m < 8; m++) {
        apply(m); drawFormat(m);
        const pp = penalty(mod);
        if (pp < bestP) { bestP = pp; best = m; }
        apply(m);                                  // XOR again: back to unmasked
      }
    }
    apply(best); drawFormat(best);
    return { size, version: v, mask: best, modules: mod };
  }

  function svg(text, ecl) {
    const q = encode(text, ecl), n = q.size + 8;
    let d = '';
    q.modules.forEach((row, y) => row.forEach((on, x) => { if (on) d += `M${x + 4} ${y + 4}h1v1h-1z`; }));
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${n} ${n}" shape-rendering="crispEdges" role="img">` +
      `<rect width="${n}" height="${n}" fill="#fff"/><path d="${d}" fill="#000"/></svg>`;
  }

  const api = { encode, svg, rs, formatBits, versionBits, alignPositions, dataCodewords, codewords };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else root.UTQR = api;
})(typeof window !== 'undefined' ? window : this);
