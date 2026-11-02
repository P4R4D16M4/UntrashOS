#!/usr/bin/env python3
"""untrash-cloudlink with the real fanotify feed on an ext4 loop image.
Needs root (filesystem marks, open_by_handle_at, mount); not part of make test.

  sudo unshare -m --propagation private python3 image/tests/test_cloudlink_fanotify_root.py

Checked: create, write+close, mkdir, rename (both names), delete, a change
deep in a new folder tree (no watch per folder), a folder deleted before its
event is read (rescan), a share on the filesystem the cloud does not follow.
"""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OS = os.path.abspath(os.path.join(HERE, "..", ".."))
CLOUDLINK = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-cloudlink")
if os.geteuid():
    print("skip: needs root (sudo unshare -m --propagation private python3 %s)" % sys.argv[0])
    sys.exit(0)
fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += not ok


W = tempfile.mkdtemp(prefix="ut-fan-")
SIG = os.path.join(W, "zt-sig")
subprocess.run(["gcc", "-O2", "-I" + os.path.join(OS, "third_party/tweetnacl"), "-o", SIG,
                os.path.join(OS, "slot/zt-sig.c"), os.path.join(OS, "third_party/tweetnacl/tweetnacl.c")], check=True)
R = W + "/root"
VOL = R + "/i-data/v1"
os.makedirs(VOL)
subprocess.run(["truncate", "-s", "64M", W + "/vol.img"], check=True)
subprocess.run(["mkfs.ext4", "-q", "-F", W + "/vol.img"], check=True)
subprocess.run(["mount", "-o", "loop", W + "/vol.img", VOL], check=True)
proc = None
try:
    for s in ("Photos", "Music"):
        os.makedirs(VOL + "/" + s)
    os.makedirs(R + "/etc/untrash/zyxel/stock-config")
    db = sqlite3.connect(R + "/etc/untrash/zyxel/stock-config/ugs_conf.db")
    db.execute("CREATE TABLE smb_share (s_name, s_path, s_enable)")
    db.executemany("INSERT INTO smb_share VALUES (?,?,?)", [("Photos", "/i-data/v1/Photos", "y"), ("Music", "/i-data/v1/Music", "y")])
    db.commit()
    db.close()
    md = W + "/mesh"
    os.makedirs(md)
    subprocess.run([SIG, "keygen", md + "/cloud.sec", md + "/cloud.pub"], check=True)
    pub = open(md + "/cloud.pub", "rb").read().hex()
    nc = hashlib.sha256(bytes.fromhex(pub)).hexdigest()[:16]
    json.dump({"mesh": {"id": "0" * 16, "name": "t"}, "roster": {"members": {nc: {"pub": pub, "kind": "cloud", "name": "nc"}}}},
              open(md + "/mesh.json", "w"))
    json.dump({nc: {"shares": ["Photos"]}}, open(md + "/clouds.json", "w"))
    port = 30000 + os.getpid() % 2000
    proc = subprocess.Popen([CLOUDLINK, "run"], env=dict(os.environ, ZT_CLOUDLINK_ROOT=R, ZT_MESH_DIR=md, ZT_SIG=SIG,
                                                         ZT_CLOUDLINK_PORT=str(port)),
                            stdout=open(W + "/log", "w"), stderr=subprocess.STDOUT)

    def call(path):
        ts, nonce = str(int(time.time())), os.urandom(16).hex()
        open(W + "/m", "wb").write("\n".join(["UTCL1", "GET", path, ts, nonce, hashlib.sha256(b"").hexdigest()]).encode())
        subprocess.run([SIG, "sign", md + "/cloud.sec", W + "/m", W + "/s"], check=True)
        hdr = "UntrashCloud node=%s, ts=%s, nonce=%s, sig=%s" % (nc, ts, nonce, open(W + "/s", "rb").read().hex())
        try:
            with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d%s" % (port, path),
                                                               headers={"Authorization": hdr}), timeout=30) as r:
                return json.load(r)
        except (OSError, urllib.error.URLError):
            return {}

    cur = None
    for _ in range(50):
        cur = call("/v1/changes?since=").get("cursor")
        if cur and "watching" in open(W + "/log").read():
            break
        time.sleep(0.2)
    # the mark itself asks for a rescan; take it
    cur = call("/v1/changes?since=" + cur)["cursor"]

    def changes_after(fn, wait=3):
        global cur
        fn()
        got, rescan, end = [], set(), time.time() + wait
        while time.time() < end:
            r = call("/v1/changes?since=%s&wait=1" % cur)
            cur = r["cursor"]
            got += [c["path"] for c in r["changes"]]
            rescan |= set(r["rescan"])
        return got, rescan

    P = VOL + "/Photos/"
    got, _ = changes_after(lambda: open(P + "a.jpg", "w").write("x" * 1000))
    check("create + write + close: a.jpg", "a.jpg" in got)
    got, _ = changes_after(lambda: os.makedirs(P + "2026/trip/day1"))
    check("mkdir -p: every new folder", {"2026", "2026/trip", "2026/trip/day1"} <= set(got))
    got, _ = changes_after(lambda: open(P + "2026/trip/day1/img.jpg", "w").write("y"))
    check("a file deep in a new tree (no per-folder watch needed)", "2026/trip/day1/img.jpg" in got)
    got, _ = changes_after(lambda: os.rename(P + "a.jpg", P + "2026/b.jpg"))
    check("rename: old and new name", "a.jpg" in got and "2026/b.jpg" in got)
    got, _ = changes_after(lambda: os.remove(P + "2026/b.jpg"))
    check("delete", "2026/b.jpg" in got)
    got, _ = changes_after(lambda: open(VOL + "/Music/x.mp3", "w").write("z"))
    check("a share the cloud does not follow: nothing", got == [])

    def vanish():
        os.makedirs(P + "tmp/sub")
        open(P + "tmp/sub/f", "w").write("1")
        shutil.rmtree(P + "tmp")
    got, rescan = changes_after(vanish)
    check("a folder gone before its event is read: change or rescan, never lost", "tmp" in got or "Photos" in rescan)
    st = json.loads(subprocess.run([CLOUDLINK, "status"], env=dict(os.environ, ZT_CLOUDLINK_ROOT=R, ZT_MESH_DIR=md),
                                   stdout=subprocess.PIPE, text=True).stdout)
    check("status: the filesystem of Photos", st["filesystems"] == [P.rstrip("/")])
finally:
    if proc:
        proc.terminate()
        proc.wait(5)
    subprocess.run(["umount", VOL])
    if fails:
        print("log:", open(W + "/log").read()[-2000:])
    shutil.rmtree(W, ignore_errors=True)
print("%d failed" % fails if fails else "all ok")
sys.exit(1 if fails else 0)
