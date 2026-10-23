#!/usr/bin/env python3
"""Write design/i18n/{de,fr}.json from tools/i18n/catalog_*.py and report
English UI texts (tools/i18n/extract.py) that have no translation yet.

  build.py           write the catalogs, list missing texts, exit 1 if any
  build.py --check   only check (used by make test)
"""
import glob
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import extract  # noqa: E402

OUT = extract.CAT
LANGS = ("de", "fr")


def load():
    t = {}
    for f in sorted(glob.glob(os.path.join(HERE, "catalog_*.py"))):
        spec = importlib.util.spec_from_file_location(os.path.basename(f)[:-3], f)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        for k, v in m.T.items():
            if k in t and t[k] != v:
                sys.exit("%s: %r translated twice differently" % (os.path.basename(f), k))
            if len(v) != len(LANGS) or not all(v):
                sys.exit("%s: %r needs %d translations" % (os.path.basename(f), k, len(LANGS)))
            t[k] = v
    return t


def main():
    t = load()
    if "--check" not in sys.argv:
        os.makedirs(OUT, exist_ok=True)
        for i, lang in enumerate(LANGS):
            with open(os.path.join(OUT, lang + ".json"), "w", encoding="utf-8") as f:
                json.dump({"lang": lang, "text": {k: v[i] for k, v in sorted(t.items())}}, f, ensure_ascii=False, indent=0)
    # a piece of a composed text ('Connect ' + name) is covered by a pattern key ("Connect %s")
    parts = {p.strip() for k in t if "%" in k for p in re.split(r"%(?:\.\d)?[sdf]", k)}
    missing = [x for x in extract.collect() if x not in t and x not in parts]
    for x in missing:
        print("MISSING " + x)
    print("i18n: %d texts, %d translated, %d missing" % (len(t) + len([x for x in missing]), len(t), len(missing)))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
