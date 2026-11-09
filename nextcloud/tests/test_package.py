#!/usr/bin/env python3
"""nextcloud/package.py: reproducible archives with exactly the app's files."""
import os
import subprocess
import sys
import tarfile
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, NC)
import package  # noqa: E402

fails = 0


def check(ok, what):
    global fails
    print(("ok   " if ok else "FAIL ") + what)
    fails += not ok


def build(out):
    env = dict(os.environ, SOURCE_DATE_EPOCH="1790000000")
    subprocess.run([sys.executable, os.path.join(NC, "package.py"), out],
                   check=True, env=env, capture_output=True)
    return sorted(os.listdir(out))


ver = package.version()
with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
    names = build(a)
    build(b)
    app, helper = "untrash-%s.tar.gz" % ver, "untrash-cloud-wg-%s.tar.gz" % ver
    check(names == sorted([app, helper, "SHA256SUMS"]), "archives named after the info.xml version " + ver)
    check(all(open(os.path.join(a, n), "rb").read() == open(os.path.join(b, n), "rb").read()
              for n in names), "two builds are byte-identical")

    with tarfile.open(os.path.join(a, app)) as t:
        members = t.getmembers()
        files = {m.name for m in members if m.isfile()}
    check(all(m.name == "untrash" or m.name.startswith("untrash/") for m in members),
          "app archive holds the one folder untrash/")
    check("untrash/appinfo/info.xml" in files and "untrash/l10n/de.json" in files,
          "... with appinfo/info.xml and the translations")
    check(all(m.uid == 0 and m.gid == 0 and m.mtime == 1790000000 for m in members),
          "... owner root, fixed mtime")
    check(not any("__pycache__" in n or n.endswith(".pyc") or "/." in n for n in files),
          "... no caches or hidden files")
    try:
        tracked = subprocess.run(["git", "-C", NC, "ls-files", "untrash"], capture_output=True,
                                 text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        tracked = None
    if tracked:
        check(files == set(tracked), "... exactly the tracked files of nextcloud/untrash")

    with tarfile.open(os.path.join(a, helper)) as t:
        hm = {m.name: m for m in t.getmembers() if m.isfile()}
    check(set(hm) == {"untrash-cloud-wg/untrash-cloud-wg", "untrash-cloud-wg/untrash-cloud-wg.service"},
          "helper archive: the helper and its unit")
    check(hm["untrash-cloud-wg/untrash-cloud-wg"].mode == 0o755
          and hm["untrash-cloud-wg/untrash-cloud-wg.service"].mode == 0o644, "... helper executable, unit 644")

    sums = open(os.path.join(a, "SHA256SUMS")).read()
    check(app in sums and helper in sums, "SHA256SUMS lists both archives")

print("all ok" if not fails else "%d failed" % fails)
sys.exit(1 if fails else 0)
