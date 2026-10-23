#!/usr/bin/env python3
"""Cut the UntrashOS base graphics (project root) into web assets.

Inputs: design/source/untrash-logo.png, untrash-icons.png,
untrash-wallpaper.png.  Output: design/assets/.  Re-run after the source
graphics change; the crop boxes below are measured on the current versions.
"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "source")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# icon sheet: 4 x 3 tiles, ~250 px, labels below each tile
ICONS = ["files", "shares", "storage", "raid",
         "network", "users", "updates", "backup",
         "terminal", "apps", "monitor", "power"]
COLS = [69, 358, 647, 936]
ROWS = [137, 467, 798]
TILE = 249
RADIUS = 0.19          # corner radius / tile size, measured
SIZES = [256, 128, 64]


def rounded_mask(size, r, scale=4):
    m = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size * scale - 1, size * scale - 1),
                                        radius=int(r * size * scale), fill=255)
    return m.resize((size, size), Image.LANCZOS)


def color_to_alpha(img, bg):
    """GIMP-style colour-to-alpha against the sampled background colour."""
    a = np.asarray(img.convert("RGB")).astype(np.float64) / 255.0
    b = np.array(bg, dtype=np.float64) / 255.0
    with np.errstate(divide="ignore", invalid="ignore"):
        up = np.where(a > b, (a - b) / (1.0 - b), 0.0)
        dn = np.where(a < b, (b - a) / b, 0.0)
    alpha = np.clip(np.max(np.maximum(up, dn), axis=2), 0.0, 1.0)
    al = np.where(alpha > 0, alpha, 1.0)[..., None]
    rgb = np.clip((a - b * (1.0 - al)) / al, 0.0, 1.0)
    out = np.dstack([rgb, alpha]) * 255.0
    return Image.fromarray(out.round().astype(np.uint8), "RGBA")


def save_sizes(img, base, sizes):
    for s in sizes:
        img.resize((s, int(img.height * s / img.width)), Image.LANCZOS).save(
            "%s-%d.png" % (base, s), optimize=True)


def icons():
    sheet = Image.open(os.path.join(ROOT, "untrash-icons.png")).convert("RGB")
    mask = rounded_mask(TILE, RADIUS)
    for i, name in enumerate(ICONS):
        x, y = COLS[i % 4], ROWS[i // 4]
        t = sheet.crop((x, y, x + TILE, y + TILE)).convert("RGBA")
        t.putalpha(mask)
        save_sizes(t, os.path.join(OUT, "icons", name), SIZES)


def status_icon():
    """"status" = the monitor tile with its pulse curve replaced by a magnifier
    (no icon is used twice; the overview keeps "monitor")."""
    src = Image.open(os.path.join(OUT, "icons", "monitor-256.png")).convert("RGBA")
    a = np.array(src).astype(int)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    y0, y1, x0, x1 = 52, 178, 38, 218                  # screen area of the 256 px tile
    box = np.zeros(r.shape, bool)
    box[y0:y1, x0:x1] = True
    curve = box & (g > 70) & (g > r + 30)              # teal/green pulse line + glow
    curve = np.array(Image.fromarray((curve * 255).astype("uint8")).filter(ImageFilter.MaxFilter(5))) > 0
    out = a.copy()
    for y in range(y0, y1):                            # fill from the nearest clean pixels in the row
        xs = np.where(curve[y, x0:x1])[0] + x0
        for x in xs:
            for d in range(1, 30):
                for xx in (x - d, x + d):
                    if x0 <= xx < x1 and not curve[y, xx]:
                        out[y, x, :3] = a[y, xx, :3]
                        break
                else:
                    continue
                break
    base = Image.fromarray(out.astype("uint8"), "RGBA")
    S = 4
    big = Image.new("RGBA", (256 * S, 256 * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    cx, cy, rad = 118 * S, 108 * S, 34 * S
    hx0, hy0 = cx + int(rad * .72), cy + int(rad * .72)
    hx1, hy1 = cx + int(rad * 1.75), cy + int(rad * 1.75)
    teal, cyan = (5, 199, 175, 255), (64, 224, 240, 255)
    d.line((hx0, hy0, hx1, hy1), fill=teal, width=13 * S)
    d.ellipse((hx1 - 6 * S, hy1 - 6 * S, hx1 + 6 * S, hy1 + 6 * S), fill=teal)
    d.ellipse((cx - rad, cy - rad, cx + rad, cy + rad), outline=cyan, width=9 * S)
    d.ellipse((cx - rad + 9 * S, cy - rad + 9 * S, cx + rad - 9 * S, cy + rad - 9 * S), fill=(40, 200, 210, 38))
    d.arc((cx - rad + 16 * S, cy - rad + 16 * S, cx + rad - 16 * S, cy + rad - 16 * S), 200, 260,
          fill=(220, 255, 250, 200), width=4 * S)
    mag = big.resize((256, 256), Image.LANCZOS)
    glow = Image.new("RGBA", mag.size, (5, 199, 175, 0))
    glow.putalpha(mag.getchannel("A").filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * .55)))
    img = Image.alpha_composite(Image.alpha_composite(base, glow), mag)
    img.putalpha(src.getchannel("A"))                  # keep the rounded tile shape
    save_sizes(img, os.path.join(OUT, "icons", "status"), SIZES)


def blank_tile():
    """Empty tile in the sheet's style: background per row from the free edge
    strip of an existing icon, its rounded alpha mask."""
    src = Image.open(os.path.join(OUT, "icons", "files-256.png")).convert("RGBA")
    a = np.array(src).astype(int)
    out = a.copy()
    for y in range(256):
        row = a[y, 14:30]
        row = row[row[:, 3] == 255]
        if len(row):
            out[y, :, :3] = np.median(row[:, :3], axis=0)
    out[..., 3] = a[..., 3]
    return Image.fromarray(out.astype("uint8"), "RGBA")


def _grad(size, c0, c1, horizontal=False):
    w, h = size
    t = np.linspace(0, 1, w if horizontal else h)
    g = np.array(c0)[None, :] * (1 - t[:, None]) + np.array(c1)[None, :] * t[:, None]
    img = np.repeat(g[None, :, :], h, 0) if horizontal else np.repeat(g[:, None, :], w, 1)
    return Image.fromarray(img.astype("uint8"), "RGBA")


def _paint(base, mask_img, fill):
    """Composite fill (an RGBA image) through an L mask onto base."""
    layer = fill.copy()
    layer.putalpha(Image.fromarray((np.array(mask_img).astype(int) * np.array(fill.getchannel("A")).astype(int) // 255).astype("uint8")))
    return Image.alpha_composite(base, layer)


def _glow(base, mask_img, rgb=(5, 199, 175), blur=7, k=.6):
    g = Image.new("RGBA", base.size, rgb + (0,))
    g.putalpha(mask_img.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * k)))
    return Image.alpha_composite(base, g)


METAL = ((168, 173, 179, 255), (74, 79, 85, 255))
ACCENT = ((5, 199, 175, 255), (70, 226, 240, 255))


def app_icons():
    """Player (disc + play) and synthesizer (keys + square wave): new tiles in
    the sheet's style, so that no app shows another app's icon."""
    S = 4
    # ---- player
    t = blank_tile()
    m = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(m)
    d.ellipse((46 * S, 46 * S, 210 * S, 210 * S), fill=255)
    d.ellipse((112 * S, 112 * S, 144 * S, 144 * S), fill=0)
    disc = m.resize((256, 256), Image.LANCZOS)
    t = _paint(t, disc, _grad((256, 256), *METAL))
    r = Image.new("L", (256 * S, 256 * S), 0)
    ImageDraw.Draw(r).ellipse((52 * S, 52 * S, 204 * S, 204 * S), outline=255, width=2 * S)
    ImageDraw.Draw(r).ellipse((72 * S, 72 * S, 184 * S, 184 * S), outline=255, width=2 * S)
    t = _paint(t, r.resize((256, 256), Image.LANCZOS), Image.new("RGBA", (256, 256), (40, 44, 48, 150)))
    tri = Image.new("L", (256 * S, 256 * S), 0)
    ImageDraw.Draw(tri).polygon([(104 * S, 80 * S), (104 * S, 176 * S), (184 * S, 128 * S)], fill=255)
    tri = tri.resize((256, 256), Image.LANCZOS)
    t = _glow(t, tri)
    t = _paint(t, tri, _grad((256, 256), *ACCENT, horizontal=True))
    save_sizes(t, os.path.join(OUT, "icons", "player"), SIZES)
    # ---- synthesizer
    t = blank_tile()
    keys = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(keys)
    x0, y0, y1, n, w = 44, 120, 206, 7, 24
    for i in range(n):
        d.rounded_rectangle(((x0 + i * w + 1) * S, y0 * S, (x0 + (i + 1) * w - 1) * S, y1 * S), radius=4 * S, fill=255)
    t = _paint(t, keys.resize((256, 256), Image.LANCZOS), _grad((256, 256), *METAL))
    blk = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(blk)
    for i in (1, 2, 4, 5, 6):
        cx = x0 + i * w
        d.rounded_rectangle(((cx - 8) * S, y0 * S, (cx + 8) * S, (y0 + 52) * S), radius=3 * S, fill=255)
    t = _paint(t, blk.resize((256, 256), Image.LANCZOS), Image.new("RGBA", (256, 256), (22, 25, 28, 255)))
    wave = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(wave)
    pts, x, hi = [], 44, True
    for seg in (22, 22, 14, 14, 30, 22, 22, 22):
        y = 62 if hi else 98
        pts += [(x * S, y * S), ((x + seg) * S, y * S)]
        x += seg
        hi = not hi
    d.line(pts, fill=255, width=7 * S, joint="curve")
    wave = wave.resize((256, 256), Image.LANCZOS)
    t = _glow(t, wave)
    t = _paint(t, wave, _grad((256, 256), *ACCENT, horizontal=True))
    save_sizes(t, os.path.join(OUT, "icons", "synth"), SIZES)
    # ---- feedback: speech bubble with an exclamation mark
    t = blank_tile()
    bub = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(bub)
    d.rounded_rectangle((44 * S, 52 * S, 212 * S, 166 * S), radius=30 * S, fill=255)
    d.polygon([(84 * S, 160 * S), (76 * S, 206 * S), (124 * S, 162 * S)], fill=255)
    t = _paint(t, bub.resize((256, 256), Image.LANCZOS), _grad((256, 256), *METAL))
    mark = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(mark)
    d.rounded_rectangle((119 * S, 72 * S, 137 * S, 124 * S), radius=8 * S, fill=255)
    d.ellipse((118 * S, 134 * S, 138 * S, 154 * S), fill=255)
    mark = mark.resize((256, 256), Image.LANCZOS)
    t = _glow(t, mark)
    t = _paint(t, mark, _grad((256, 256), *ACCENT))
    save_sizes(t, os.path.join(OUT, "icons", "feedback"), SIZES)
    # ---- media server: server unit with media tiles, sending arcs above
    t = blank_tile()
    box = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(box)
    d.rounded_rectangle((48 * S, 118 * S, 208 * S, 206 * S), radius=16 * S, fill=255)
    t = _paint(t, box.resize((256, 256), Image.LANCZOS), _grad((256, 256), *METAL))
    slots = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(slots)
    for i in range(3):
        x = 66 + i * 44
        d.rounded_rectangle((x * S, 136 * S, (x + 34) * S, 172 * S), radius=5 * S, fill=255)
    t = _paint(t, slots.resize((256, 256), Image.LANCZOS), Image.new("RGBA", (256, 256), (22, 25, 28, 255)))
    acc = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(acc)
    d.polygon([(77 * S, 146 * S), (77 * S, 162 * S), (91 * S, 154 * S)], fill=255)
    d.ellipse((190 * S, 186 * S, 198 * S, 194 * S), fill=255)
    for r in (22, 44, 66):
        d.arc(((128 - r) * S, (100 - r) * S, (128 + r) * S, (100 + r) * S), 215, 325, fill=255, width=9 * S)
    acc = acc.resize((256, 256), Image.LANCZOS)
    t = _glow(t, acc)
    t = _paint(t, acc, _grad((256, 256), *ACCENT, horizontal=True))
    save_sizes(t, os.path.join(OUT, "icons", "mediaserver"), SIZES)
    # ---- broadcast channels ("Sender"): TV set with antenna and play mark
    t = blank_tile()
    tv = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(tv)
    d.rounded_rectangle((40 * S, 80 * S, 216 * S, 196 * S), radius=18 * S, fill=255)
    d.rounded_rectangle((104 * S, 196 * S, 152 * S, 212 * S), radius=4 * S, fill=255)
    t = _paint(t, tv.resize((256, 256), Image.LANCZOS), _grad((256, 256), *METAL))
    scr = Image.new("L", (256 * S, 256 * S), 0)
    ImageDraw.Draw(scr).rounded_rectangle((54 * S, 94 * S, 202 * S, 182 * S), radius=10 * S, fill=255)
    t = _paint(t, scr.resize((256, 256), Image.LANCZOS), Image.new("RGBA", (256, 256), (16, 19, 22, 255)))
    acc = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(acc)
    d.line([(128 * S, 78 * S), (92 * S, 40 * S)], fill=255, width=7 * S)
    d.line([(128 * S, 78 * S), (164 * S, 40 * S)], fill=255, width=7 * S)
    d.ellipse((86 * S, 34 * S, 98 * S, 46 * S), fill=255)
    d.ellipse((158 * S, 34 * S, 170 * S, 46 * S), fill=255)
    d.polygon([(114 * S, 114 * S), (114 * S, 162 * S), (154 * S, 138 * S)], fill=255)
    acc = acc.resize((256, 256), Image.LANCZOS)
    t = _glow(t, acc)
    t = _paint(t, acc, _grad((256, 256), *ACCENT, horizontal=True))
    save_sizes(t, os.path.join(OUT, "icons", "tv"), SIZES)
    # ---- ad filter: shield with a crossed-out "Ad" bubble
    t = blank_tile()
    sh = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(sh)
    d.polygon([(128 * S, 36 * S), (206 * S, 66 * S), (200 * S, 140 * S), (128 * S, 220 * S), (56 * S, 140 * S), (50 * S, 66 * S)], fill=255)
    t = _paint(t, sh.resize((256, 256), Image.LANCZOS), _grad((256, 256), *METAL))
    inner = Image.new("L", (256 * S, 256 * S), 0)
    ImageDraw.Draw(inner).polygon([(128 * S, 54 * S), (190 * S, 78 * S), (185 * S, 136 * S), (128 * S, 199 * S), (71 * S, 136 * S), (66 * S, 78 * S)], fill=255)
    t = _paint(t, inner.resize((256, 256), Image.LANCZOS), Image.new("RGBA", (256, 256), (18, 21, 24, 255)))
    acc = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(acc)
    d.ellipse((90 * S, 86 * S, 166 * S, 162 * S), outline=255, width=12 * S)
    d.line([(100 * S, 152 * S), (156 * S, 96 * S)], fill=255, width=12 * S)
    acc = acc.resize((256, 256), Image.LANCZOS)
    t = _glow(t, acc)
    t = _paint(t, acc, _grad((256, 256), *ACCENT, horizontal=True))
    save_sizes(t, os.path.join(OUT, "icons", "adblock"), SIZES)
    # ---- manual: open book with lined pages and a bookmark
    t = blank_tile()
    bk = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(bk)
    d.polygon([(40 * S, 70 * S), (124 * S, 82 * S), (124 * S, 204 * S), (40 * S, 192 * S)], fill=255)
    d.polygon([(132 * S, 82 * S), (216 * S, 70 * S), (216 * S, 192 * S), (132 * S, 204 * S)], fill=255)
    t = _paint(t, bk.resize((256, 256), Image.LANCZOS), _grad((256, 256), *METAL))
    ln = Image.new("L", (256 * S, 256 * S), 0)
    d = ImageDraw.Draw(ln)
    for i in range(5):
        y = 102 + i * 18
        d.line([(56 * S, (y - 2) * S), (110 * S, (y + 6) * S)], fill=255, width=5 * S)
        d.line([(146 * S, (y + 6) * S), (200 * S, (y - 2) * S)], fill=255, width=5 * S)
    t = _paint(t, ln.resize((256, 256), Image.LANCZOS), Image.new("RGBA", (256, 256), (22, 25, 28, 255)))
    acc = Image.new("L", (256 * S, 256 * S), 0)
    ImageDraw.Draw(acc).polygon([(168 * S, 60 * S), (192 * S, 60 * S), (192 * S, 124 * S), (180 * S, 112 * S), (168 * S, 124 * S)], fill=255)
    acc = acc.resize((256, 256), Image.LANCZOS)
    t = _glow(t, acc)
    t = _paint(t, acc, _grad((256, 256), *ACCENT))
    save_sizes(t, os.path.join(OUT, "icons", "manual"), SIZES)


def logo():
    src = Image.open(os.path.join(ROOT, "untrash-logo.png")).convert("RGB")
    bg = (13, 16, 21)
    mark = color_to_alpha(src.crop((40, 360, 345, 675)), bg)
    mark = mark.crop(mark.getbbox())
    save_sizes(mark, os.path.join(OUT, "logo-mark"), [512, 192, 96, 48])
    full = color_to_alpha(src.crop((40, 360, 1050, 675)), bg)
    full = full.crop(full.getbbox())
    save_sizes(full, os.path.join(OUT, "logo"), [1000, 480, 240])
    word = color_to_alpha(src.crop((360, 465, 1050, 590)), bg)
    word = word.crop(word.getbbox())
    save_sizes(word, os.path.join(OUT, "wordmark"), [600, 300])
    # favicon: mark on transparent, 32/16 inside one .ico
    fav = mark.resize((256, int(256 * mark.height / mark.width)), Image.LANCZOS)
    sq = Image.new("RGBA", (256, 256))
    sq.paste(fav, (0, (256 - fav.height) // 2), fav)
    sq.save(os.path.join(OUT, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)])


def wallpaper():
    src = Image.open(os.path.join(ROOT, "untrash-wallpaper.png")).convert("RGB")
    src.save(os.path.join(OUT, "wallpaper.jpg"), quality=86, optimize=True, progressive=True)
    src.resize((960, 540), Image.LANCZOS).save(os.path.join(OUT, "wallpaper-960.jpg"),
                                              quality=82, optimize=True, progressive=True)
    # blurred variant: background for login and modal backdrops
    src.resize((480, 270), Image.LANCZOS).filter(ImageFilter.GaussianBlur(10)).save(
        os.path.join(OUT, "wallpaper-blur.jpg"), quality=80, optimize=True)


if __name__ == "__main__":
    for f in ("untrash-logo.png", "untrash-icons.png", "untrash-wallpaper.png"):
        if not os.path.exists(os.path.join(ROOT, f)):
            sys.exit("missing source graphic: %s" % f)
    os.makedirs(os.path.join(OUT, "icons"), exist_ok=True)
    icons()
    status_icon()
    app_icons()
    logo()
    wallpaper()
    print("assets written to", OUT)
