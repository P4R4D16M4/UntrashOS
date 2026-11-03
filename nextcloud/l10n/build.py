#!/usr/bin/env python3
"""Translations of the Nextcloud app "untrash": nextcloud/l10n/catalog.py
(English -> German, French) to untrash/l10n/{de,de_DE,fr}.{js,json}, the
format Nextcloud loads (OC.L10N.register / {"translations"}).

  build.py           write the files; exit 1 if a text has no translation
  build.py --check   only check that every text is translated and the files are current (make test)

Texts are collected from the app: $l->t('...') / $this->l->t('...') in PHP
and templates, T('...') / t('untrash', '...') in js/.  German uses the
neutral form (infinitives, no du/Sie), so de and de_DE are the same.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "..", "untrash")
sys.path.insert(0, HERE)
from catalog import T  # noqa: E402

PLURAL = {"de": "nplurals=2; plural=(n != 1);", "de_DE": "nplurals=2; plural=(n != 1);", "fr": "nplurals=2; plural=(n > 1);"}
COL = {"de": 0, "de_DE": 0, "fr": 1}


def unq(s, q):
    return s.replace("\\" + q, q).replace("\\\\", "\\")


def texts():
    out = set()
    for f in glob.glob(APP + "/lib/**/*.php", recursive=True) + glob.glob(APP + "/templates/*.php"):
        src = open(f).read()
        out |= {unq(m, "'") for m in re.findall(r"\$(?:this->)?l->t\('((?:[^'\\]|\\.)*)'", src)}
    for f in glob.glob(APP + "/js/*.js"):
        src = open(f).read()
        out |= {unq(m, "'") for m in re.findall(r"\bT\('((?:[^'\\]|\\.)*)'", src)}
        out |= {unq(m, "'") for m in re.findall(r"\bt\('untrash', '((?:[^'\\]|\\.)*)'", src)}
    return out


def render(lang):
    tr = {k: v[COL[lang]] for k, v in sorted(T.items())}
    js = 'OC.L10N.register(\n    "untrash",\n    %s,\n"%s");\n' % (json.dumps(tr, ensure_ascii=False, indent=4), PLURAL[lang])
    js_json = json.dumps({"translations": tr, "pluralForm": PLURAL[lang]}, ensure_ascii=False, indent=4) + "\n"
    return js, js_json


def main():
    want = texts()
    missing = sorted(want - set(T))
    unused = sorted(set(T) - want)
    for m in missing:
        print("MISSING " + m)
    for u in unused:
        print("UNUSED  " + u)
    bad = [k for k, v in T.items() if len(v) != 2 or not all(v)]
    for k in bad:
        print("INCOMPLETE " + k)
    stale = []
    for lang in PLURAL:
        js, js_json = render(lang)
        for ext, body in (("js", js), ("json", js_json)):
            p = os.path.join(APP, "l10n", "%s.%s" % (lang, ext))
            cur = open(p).read() if os.path.exists(p) else None
            if cur != body:
                if "--check" in sys.argv:
                    stale.append(p)
                else:
                    os.makedirs(os.path.dirname(p), exist_ok=True)
                    open(p, "w").write(body)
    for p in stale:
        print("STALE   %s (run nextcloud/l10n/build.py)" % os.path.relpath(p, HERE))
    print("nextcloud l10n: %d texts, %d missing" % (len(want), len(missing)))
    return 1 if missing or bad or stale or unused else 0


if __name__ == "__main__":
    sys.exit(main())
