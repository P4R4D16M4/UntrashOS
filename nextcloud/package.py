#!/usr/bin/env python3
"""Release archives of the Nextcloud app "untrash" and its tunnel helper.

  nextcloud/package.py [OUTDIR]          (default build/nextcloud)

writes
  untrash-<version>.tar.gz          the app: one folder "untrash/", the layout
                                    Nextcloud's apps/ folder and its app store expect
  untrash-cloud-wg-<version>.tar.gz the optional root helper (cloud-api.md §4)
  SHA256SUMS

<version> is the one in appinfo/info.xml.  The archives are reproducible: sorted
names, owner root, modes 644/755, every mtime the time of the last commit
that touched nextcloud/ (or SOURCE_DATE_EPOCH), gzip without name or time.
"""
import gzip
import hashlib
import io
import os
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "untrash")
SERVER = os.path.join(HERE, "server")
HELPER = ["untrash-cloud-wg", "untrash-cloud-wg.service"]


def version():
    return ET.parse(os.path.join(APP, "appinfo", "info.xml")).findtext("version").strip()


def source_epoch():
    env = os.environ.get("SOURCE_DATE_EPOCH")
    if env:
        return int(env)
    try:
        out = subprocess.run(["git", "-C", HERE, "log", "-1", "--format=%ct", "--", "."],
                             capture_output=True, text=True, check=True).stdout.strip()
        if out:
            return int(out)
    except (OSError, subprocess.CalledProcessError):
        pass
    sys.exit("package: no git history here; set SOURCE_DATE_EPOCH")


def skip(name):
    return name.startswith(".") or name == "__pycache__" or name.endswith(".pyc")


def app_files():
    """(path on disk, name in the archive) for the app, sorted."""
    out = []
    for root, dirs, files in os.walk(APP):
        dirs[:] = sorted(d for d in dirs if not skip(d))
        for f in sorted(files):
            if not skip(f):
                p = os.path.join(root, f)
                out.append((p, "untrash/" + os.path.relpath(p, APP).replace(os.sep, "/")))
    return out


def write_tgz(path, entries, epoch):
    """entries: (path on disk, name in archive); parent folders are added."""
    dirs = set()
    for _, name in entries:
        parts = name.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
        def info(name, mode, kind, size=0):
            ti = tarfile.TarInfo(name)
            ti.type, ti.mode, ti.size, ti.mtime = kind, mode, size, epoch
            ti.uid = ti.gid = 0
            ti.uname = ti.gname = "root"
            return ti
        items = [(d, None) for d in dirs] + [(n, p) for p, n in entries]
        for name, src in sorted(items):
            if src is None:
                tar.addfile(info(name, 0o755, tarfile.DIRTYPE))
            else:
                with open(src, "rb") as fh:
                    data = fh.read()
                mode = 0o755 if os.access(src, os.X_OK) else 0o644
                tar.addfile(info(name, mode, tarfile.REGTYPE, len(data)), io.BytesIO(data))
    with open(path, "wb") as out:
        with gzip.GzipFile(filename="", mode="wb", fileobj=out, mtime=0, compresslevel=9) as gz:
            gz.write(raw.getvalue())


def main():
    outdir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "build", "nextcloud")
    os.makedirs(outdir, exist_ok=True)
    ver, epoch = version(), source_epoch()
    made = {
        "untrash-%s.tar.gz" % ver: app_files(),
        "untrash-cloud-wg-%s.tar.gz" % ver:
            [(os.path.join(SERVER, f), "untrash-cloud-wg/" + f) for f in HELPER],
    }
    sums = []
    for name, entries in made.items():
        path = os.path.join(outdir, name)
        write_tgz(path, entries, epoch)
        with open(path, "rb") as fh:
            sums.append("%s  %s\n" % (hashlib.sha256(fh.read()).hexdigest(), name))
        print(path)
    with open(os.path.join(outdir, "SHA256SUMS"), "w") as fh:
        fh.writelines(sums)


if __name__ == "__main__":
    main()
