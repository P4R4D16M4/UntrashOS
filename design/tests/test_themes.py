#!/usr/bin/env python3
"""PC test of the Desk themes in design/untrash.css (WCAG + colour vision).

For every theme (dark, light, contrast) and colour-vision setting (none,
protan, deutan, tritan, achroma) the tokens are resolved as the browser
would (the :root block, then the matching [data-theme] / [data-cvd] blocks):

- text: fg and fg-2 on the window and panel backgrounds >= 4.5:1 (contrast
  theme 7:1); fg-3 (hints) and the accent text >= 4.5:1
- states (ok, info, warn, danger) as pill text on their tint >= 4.5:1
  (contrast theme 7:1)
- states stay apart: CIEDE2000 between every two states >= 18 for normal
  vision; with a deficiency set, >= 18 under that deficiency (simulated,
  Machado 2009; about 10 is already a clear difference) and >= 5 for
  achromatopsia, where only lightness is left: with 7:1 on black every state
  is light, so the symbols (always on with a deficiency set) carry it
"""
import itertools
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from colorcheck import blend, contrast, de2000, rgb, simulate  # noqa: E402

CSS = os.path.join(HERE, "..", "untrash.css")
THEMES = ("dark", "light", "contrast")
CVDS = ("none", "protan", "deutan", "tritan", "achroma")
STATES = ("ok", "info", "warn", "danger")
fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += not ok


def blocks(css):
    """[(selector, {token: value})] of the token blocks."""
    out = []
    for m in re.finditer(r"(:root[^{,]*)\{([^}]*)\}", css):
        toks = dict(re.findall(r"(--ut-[\w-]+)\s*:\s*([^;]+);", m.group(2)))
        if toks:
            out.append((m.group(1).strip(), toks))
    return out


def resolve(bl, theme, cvd):
    t = {}
    for sel, toks in bl:
        attrs = dict(re.findall(r"\[data-(\w+)=(\w+)\]", sel))
        if sel.startswith(":root:") or any(k not in ("theme", "cvd") for k in attrs):
            continue
        if attrs.get("theme", theme) == theme and attrs.get("cvd", cvd) == cvd:
            t.update(toks)
    return t


def colour(t, name):
    v = t["--ut-" + name].strip()
    while v.startswith("var("):
        v = t[re.match(r"var\((--ut-[\w-]+)\)", v).group(1)].strip()
    assert v.startswith("#"), (name, v)
    return rgb(v)


bl = blocks(open(CSS, encoding="utf-8").read())
for theme in THEMES:
    for cvd in CVDS:
        t = resolve(bl, theme, cvd)
        tag = "%s/%s" % (theme, cvd)
        need = 7.0 if theme == "contrast" else 4.5
        bg1, bg2 = colour(t, "bg-1"), colour(t, "bg-2")
        if cvd == "none":
            for fg in ("fg", "fg-2"):
                c = min(contrast(colour(t, fg), bg1), contrast(colour(t, fg), bg2))
                check("%s: %s on window/panel %.1f:1" % (tag, fg, c), c >= need)
            for fg in ("fg-3", "accent-fg"):
                c = min(contrast(colour(t, fg), bg1), contrast(colour(t, fg), bg2))
                check("%s: %s on window/panel %.1f:1" % (tag, fg, c), c >= 4.5)
        st = {s: colour(t, s) for s in STATES}
        low = min((contrast(c, blend(c, bg2, .12)), s) for s, c in st.items())
        check("%s: state text on its tint, lowest %s %.1f:1" % (tag, low[1], low[0]), low[0] >= need)
        normal = min((de2000(st[a], st[b]), a + "/" + b) for a, b in itertools.combinations(STATES, 2))
        check("%s: states apart for normal vision, closest %s dE %.1f" % (tag, normal[1], normal[0]), normal[0] >= 18)
        if cvd != "none":
            sim = {s: simulate(c, cvd) for s, c in st.items()}
            d = min((de2000(sim[a], sim[b]), a + "/" + b) for a, b in itertools.combinations(STATES, 2))
            check("%s: states apart under %s, closest %s dE %.1f" % (tag, cvd, d[1], d[0]), d[0] >= (5 if cvd == "achroma" else 18))
print("FAILURES %d" % fails)
sys.exit(1 if fails else 0)
