#!/usr/bin/env python3
"""Decode a QR symbol given as a module matrix (JSON [[0/1]] on stdin) and
print the text, or exit 1 with the reason.  A second, separate reading of
ISO/IEC 18004 for test_qr.js: it checks finder and timing patterns, both
format copies, the version information, the Reed-Solomon syndromes of every
block and the byte segment, so a wrong placement or interleaving in qr.js
cannot pass.  Only what the Desk produces is supported (byte mode)."""
import json
import sys

# EC codewords per block and blocks per version, levels L M Q H (table 9)
ECC = [
    [0, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    [0, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    [0, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30]]
NB = [
    [0, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
    [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
    [0, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
    [0, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81]]
# alignment pattern centres (annex E, table E.1), versions 2..40
ALIGN = {2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46],
         10: [6, 28, 50], 11: [6, 30, 54], 12: [6, 32, 58], 13: [6, 34, 62], 14: [6, 26, 46, 66], 15: [6, 26, 48, 70],
         16: [6, 26, 50, 74], 17: [6, 30, 54, 78], 18: [6, 30, 56, 82], 19: [6, 30, 58, 86], 20: [6, 34, 62, 90],
         21: [6, 28, 50, 72, 94], 22: [6, 26, 50, 74, 98], 23: [6, 30, 54, 78, 102], 24: [6, 28, 54, 80, 106],
         25: [6, 32, 58, 84, 110], 26: [6, 30, 58, 86, 114], 27: [6, 34, 62, 90, 118], 28: [6, 26, 50, 74, 98, 122],
         29: [6, 30, 54, 78, 102, 126], 30: [6, 26, 52, 78, 104, 130], 31: [6, 30, 56, 82, 108, 134],
         32: [6, 34, 60, 86, 112, 138], 33: [6, 30, 58, 86, 114, 142], 34: [6, 34, 62, 90, 118, 146],
         35: [6, 30, 54, 78, 102, 126, 150], 36: [6, 24, 50, 76, 102, 128, 154], 37: [6, 28, 54, 80, 106, 132, 158],
         38: [6, 32, 58, 84, 110, 136, 162], 39: [6, 26, 54, 82, 110, 138, 166], 40: [6, 30, 58, 86, 114, 142, 170]}


def fail(msg):
    print(msg)
    sys.exit(1)


def bch_ok(word, gen, gen_deg, total):
    """Remainder of WORD (TOTAL bits) by GEN is zero."""
    for i in range(total - 1, gen_deg - 1, -1):
        if word >> i & 1:
            word ^= gen << (i - gen_deg)
    return word == 0


EXP = [0] * 512
x = 1
for i in range(255):
    EXP[i] = x
    x <<= 1
    if x & 0x100:
        x ^= 0x11d
for i in range(255, 512):
    EXP[i] = EXP[i - 255]
LOG = {EXP[i]: i for i in range(255)}


def syndromes_zero(cw, n_ec):
    """The block polynomial (first codeword = highest power) vanishes at
    alpha^0 .. alpha^(n_ec-1)."""
    for j in range(n_ec):
        s = 0
        for c in cw:
            s = (EXP[LOG[s] + j] if s else 0) ^ c
        if s:
            return False
    return True


def main():
    m = json.load(sys.stdin)
    n = len(m)
    v = (n - 17) // 4
    if n != v * 4 + 17 or not 1 <= v <= 40 or any(len(r) != n for r in m):
        fail("not a QR matrix")
    func = [[False] * n for _ in range(n)]

    def mark(x, y):
        if 0 <= x < n and 0 <= y < n:
            func[y][x] = True
    # finder patterns + separators, checked module by module
    for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
        for dy in range(-4, 5):
            for dx in range(-4, 5):
                x, y = cx + dx, cy + dy
                if 0 <= x < n and 0 <= y < n:
                    ring = max(abs(dx), abs(dy))
                    if m[y][x] != (ring not in (2, 4)):
                        fail("finder pattern wrong at %d,%d" % (x, y))
                    mark(x, y)
    for i in range(8, n - 8):
        if m[6][i] != (i % 2 == 0) or m[i][6] != (i % 2 == 0):
            fail("timing pattern wrong at %d" % i)
        mark(i, 6)
        mark(6, i)
    al = ALIGN.get(v, [])
    for cy in al:
        for cx in al:
            if (cx, cy) in ((6, 6), (6, n - 7), (n - 7, 6)):
                continue
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    if m[cy + dy][cx + dx] != (max(abs(dx), abs(dy)) != 1):
                        fail("alignment pattern wrong at %d,%d" % (cx, cy))
                    mark(cx + dx, cy + dy)
    # format information: copy 1 around the top-left finder, copy 2 split
    f1 = [m[i][8] for i in range(6)] + [m[7][8], m[8][8], m[8][7]] + [m[8][14 - i] for i in range(9, 15)]
    f2 = [m[8][n - 1 - i] for i in range(8)] + [m[n - 15 + i][8] for i in range(8, 15)]
    for i in range(9):
        mark(8, i)
        mark(i, 8)
    for i in range(8):
        mark(n - 1 - i, 8)
    for i in range(8):
        mark(8, n - 1 - i)
    if not m[n - 8][8]:
        fail("dark module missing")
    if f1 != f2:
        fail("the two format copies differ")
    fw = sum(b << i for i, b in enumerate(f1)) ^ 0x5412
    if not bch_ok(fw, 0x537, 10, 15):
        fail("format BCH wrong")
    level = {1: 0, 0: 1, 3: 2, 2: 3}[fw >> 13]
    mask = fw >> 10 & 7
    if v >= 7:
        for blk in ((lambda i: (n - 11 + i % 3, i // 3)), (lambda i: (i // 3, n - 11 + i % 3))):
            word = 0
            for i in range(18):
                x, y = blk(i)
                word |= m[y][x] << i
                mark(x, y)
            if word >> 12 != v or not bch_ok(word, 0x1f25, 12, 18):
                fail("version information wrong")
    masks = [lambda x, y: (x + y) % 2 == 0, lambda x, y: y % 2 == 0, lambda x, y: x % 3 == 0, lambda x, y: (x + y) % 3 == 0,
             lambda x, y: (x // 3 + y // 2) % 2 == 0, lambda x, y: x * y % 2 + x * y % 3 == 0,
             lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0, lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0]
    bits = []
    col, up = n - 1, True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(n - 1, -1, -1) if up else range(n)
        for y in rows:
            for x in (col, col - 1):
                if not func[y][x]:
                    bits.append(m[y][x] ^ masks[mask](x, y))
        col -= 2
        up = not up
    total = len(bits) // 8
    cws = [int("".join(str(int(b)) for b in bits[i * 8:i * 8 + 8]), 2) for i in range(total)]
    nb, ne = NB[level][v], ECC[level][v]
    short = total // nb
    nshort = nb - total % nb
    dlen = [short - ne + (1 if i >= nshort else 0) for i in range(nb)]
    blocks = [[] for _ in range(nb)]
    k = 0
    for i in range(max(dlen)):
        for b in range(nb):
            if i < dlen[b]:
                blocks[b].append(cws[k])
                k += 1
    ecs = [[] for _ in range(nb)]
    for i in range(ne):
        for b in range(nb):
            ecs[b].append(cws[k])
            k += 1
    for b in range(nb):
        if not syndromes_zero(blocks[b] + ecs[b], ne):
            fail("Reed-Solomon syndromes of block %d not zero" % b)
    data = [c for blk in blocks for c in blk]
    s = "".join("{:08b}".format(c) for c in data)
    if s[:4] != "0100":
        fail("not a byte segment")
    nbits = 8 if v < 10 else 16
    count = int(s[4:4 + nbits], 2)
    raw = bytes(int(s[4 + nbits + 8 * i:12 + nbits + 8 * i], 2) for i in range(count))
    rest = s[4 + nbits + 8 * count:]
    if rest[:4].strip("0"):
        fail("no terminator")
    print(json.dumps({"text": raw.decode("utf-8"), "version": v, "level": "LMQH"[level], "mask": mask}))


main()
