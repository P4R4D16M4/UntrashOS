#!/usr/bin/env python3
"""Collect the German UI texts of Untrash Desk, the installer page and the
messages the Desk backend shows (Fail(...)), for the EN/FR catalogs.

  extract.py            print the texts (one per line, sorted)
  extract.py --missing  only those without an entry in every catalog

Texts are the pieces of string/template literals between HTML tags and
${...} expressions, plus title/placeholder/aria-label/alt attributes; code
(identifiers, CSS classes, paths, units) is filtered out."""
import html
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
F = os.path.join(ROOT, "image/rootfs")
SOURCES = ["usr/share/untrash/desk/desk.js", "usr/lib/untrash/untrash-installer", "usr/lib/untrash/untrash-desk"]
CAT = os.path.join(ROOT, "design/i18n")
WORD = re.compile(r"[A-Za-zÄÖÜäöüß]{2,}")
GERMAN = re.compile(r"[äöüÄÖÜß]|\b(der|die|das|den|dem|des|und|oder|nicht|kein|keine|ein|eine|einen|mit|für|auf|von|zu|zum|zur|im|in|ist|sind|wird|werden|bitte|Bitte|alle|nur|noch|neu|neue|neuer|als|wie|bei|nach|vor|aus|an|ab|aus|über|unter|bis|jetzt|hier|dieser|diese|dieses|sich|wenn|dann|Sie|du|dein|deine|ihr|ihre)\b")
CODEY = re.compile(r"^[\w.#:/-]+$|^[a-z]+[A-Z]\w*$|^ut-|\[data-|[{}<>=;\\]|^\$|^https?:|^/|\.(js|css|png|svg|json|ko|img|utslot)$")


# capitalised single words that are code, not UI text
CODE_NAMES = {"Promise", "Error", "Date", "Map", "Set", "Object", "Array", "Number", "String", "Math", "Blob", "Terminal",
              "Uint", "Content", "Accept", "Range", "Cookie", "Location", "Host", "Origin", "Upgrade", "Connection",
              "None", "True", "False", "Name", "Type", "Value", "Basic", "Bearer", "Authorization", "Escape",
              "Enter", "Backspace", "Tab", "Delete", "Insert", "Home", "End", "Control", "Shift", "Alt", "Meta"}


def js_strings(src):
    """String contents of a JS source: '...', "...", template text segments
    (split at ${...}); expressions inside templates are scanned recursively.
    Comments and regex literals are skipped well enough for this code base."""
    out, i, n = [], 0, len(src)

    def template(i):            # src[i] is just after the backtick
        seg = ""
        while i < n:
            c = src[i]
            if c == "\\":
                seg += src[i:i + 2]; i += 2; continue
            if c == "`":
                out.append(seg); return i + 1
            if c == "$" and i + 1 < n and src[i + 1] == "{":
                out.append(seg); seg = "\x00"
                i = expr(i + 2)
                continue
            seg += c; i += 1
        out.append(seg); return i

    def expr(i):                # until the matching }
        depth = 0
        while i < n:
            c = src[i]
            if c in "'\"":
                i = quoted(i); continue
            if c == "`":
                i = template(i + 1); continue
            if c == "{":
                depth += 1
            elif c == "}":
                if depth == 0:
                    return i + 1
                depth -= 1
            i += 1
        return i

    def quoted(i):
        q, j, s = src[i], i + 1, ""
        while j < n and src[j] != q and src[j] != "\n":
            if src[j] == "\\":
                s += src[j:j + 2]; j += 2; continue
            s += src[j]; j += 1
        out.append(s); return j + 1

    while i < n:
        c = src[i]
        if src.startswith("//", i) and (i == 0 or src[i - 1] in " \t\n;{}(),"):
            i = src.find("\n", i); i = n if i < 0 else i; continue
        if src.startswith("/*", i):
            i = src.find("*/", i); i = n if i < 0 else i + 2; continue
        if c in "'\"":
            i = quoted(i); continue
        if c == "`":
            i = template(i + 1); continue
        if c == "/" and src[:i].rstrip()[-1:] in ("(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";") :
            j = i + 1          # regex literal
            while j < n and src[j] != "/" and src[j] != "\n":
                j += 2 if src[j] == "\\" else 1
            i = j + 1; continue
        i += 1
    return out


def pieces(lit):
    """Text pieces of one literal: attributes for people, then split at tags."""
    out = [m.group(1) for m in re.finditer(r'(?:title|placeholder|aria-label|alt)="([^"]*)"', lit)]
    lit = re.sub(r"<[^>]*>", "\x00", lit)
    return out + lit.split("\x00")


def literals(src, py=False):
    if py:
        for m in re.finditer(r'(?:Fail|JOB\.add|problems\.append|steps\.append)\(\s*"((?:[^"\\]|\\.)*)"', src):
            yield m.group(1)
        m = re.search(r'PAGE = r?"""(.*?)"""', src, re.S)
        if not m:
            return
        src = m.group(1)
        # the HTML around the script: text between tags, title/aria attributes
        html = re.sub(r"<script>.*?</script>|<style>.*?</style>", "\x00", src, flags=re.S)
        yield html
        src = "".join(re.findall(r"<script>(.*?)</script>", src, re.S))
    yield from js_strings(src)


def clean(t):
    t = html.unescape(t)          # the browser shows "<Freigabe>", not "&lt;Freigabe&gt;"
    t = re.sub(r"\\r|\\x1b\[[0-9;]*m", "", t)
    t = t.replace("\\n", " ").strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"^[\s·,:;()%–—+•*-]+|[\s·,:(–—•*]+$", "", t)
    return t


def collect():
    found = set()
    for rel in SOURCES:
        src = open(os.path.join(F, rel), encoding="utf-8").read()
        py = not rel.endswith(".js")
        for lit in literals(src, py):
            if py and "%" in lit and not GERMAN.search(lit):
                continue
            for p in pieces(lit):
                t = clean(p)
                capword = re.fullmatch(r"[A-ZÄÖÜ][a-zäöüß]{2,}", t) and t not in CODE_NAMES
                if re.fullmatch(r"ut-[\w-]+", t) or len(WORD.findall(t)) == 0 or CODEY.search(t) and not GERMAN.search(t) and not capword:
                    continue
                if not GERMAN.search(t) and len(t) < 4:
                    continue
                if re.fullmatch(r"[A-Z0-9_ -]+", t) or re.fullmatch(r"[a-z_]+", t):
                    continue
                # CSS selectors, API paths, code
                if re.match(r"^[\[.#\]]|^tr\[|^input,|^use strict$|^[\w/-]+\?$|^\w+\(\)$|^built-in$|^calc\(|^ui-monospace|ut-pill--|^placeholder=|^(info|warn|ok|danger) ut-", t):
                    continue
                t = re.sub(r'^[">]+', "", t).strip()
                while t.endswith(")") and t.count(")") > t.count("("):
                    t = t[:-1].rstrip()
                if not WORD.search(t):
                    continue
                found.add(t)
    return sorted(found)


if __name__ == "__main__":
    texts = collect()
    if "--missing" in sys.argv:
        cats = {}
        for lang in ("en", "fr"):
            try:
                cats[lang] = json.load(open(os.path.join(CAT, lang + ".json"), encoding="utf-8"))
            except OSError:
                cats[lang] = {}
        texts = [t for t in texts if any(t not in c.get("text", {}) for c in cats.values())]
    print("\n".join(texts))
