#!/usr/bin/env python3
"""untrash-data-mount (way A ut-data at /i-data/utdata): without a mirror the
partition, with an UntrashMesh mirror its DRBD device (btrfs pinned with
device=), and the partition itself when the mirror does not start."""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "../rootfs/usr/lib/untrash/untrash-data-mount")
fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += not ok


def run(mesh_out, fail_dev=""):
    w = tempfile.mkdtemp(prefix="ut-dm-")
    bindir, log = os.path.join(w, "bin"), os.path.join(w, "mount.log")
    os.makedirs(bindir)
    open(os.path.join(w, "sdb5"), "w").close()
    os.symlink(os.path.join(w, "sdb5"), os.path.join(w, "ut-data"))
    stubs = {"mountpoint": "exit 1",                                   # nothing mounted yet
             "mount": 'echo "$*" >>%s; case "$*" in *"%s"*) [ -n "%s" ] && exit 32;; esac; exit 0' % (log, fail_dev or "@@", fail_dev)}
    for n, body in stubs.items():
        open(os.path.join(bindir, n), "w").write("#!/bin/sh\n" + body + "\n")
        os.chmod(os.path.join(bindir, n), 0o755)
    mesh = os.path.join(w, "mesh")
    open(mesh, "w").write("#!/bin/sh\necho '%s'\n" % mesh_out)
    os.chmod(mesh, 0o755)
    env = dict(os.environ, PATH=bindir + ":" + os.environ["PATH"], ZT_IDATA=os.path.join(w, "i-data"),
               ZT_UTDATA_DEV=os.path.join(w, "ut-data"), ZT_MESH_TOOL=mesh)
    r = subprocess.run(["sh", SCRIPT], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = open(log).read().splitlines() if os.path.exists(log) else []
    return r, [l for l in lines if "btrfs" in l], os.path.join(w, "sdb5"), w


r, m, part, w = run('{"device": null}')
check("no mirror: the partition is mounted", r.returncode == 0 and len(m) == 1 and m[0].endswith("%s %s/i-data/utdata" % (part, w)))
r, m, part, w = run('{"device": "/dev/drbd0"}')
check("mirror: the DRBD device is mounted, btrfs pinned to it", len(m) == 1 and "device=/dev/drbd0 /dev/drbd0 " in m[0])
r, m, part, w = run('{"error": "mirror not started: no metadata"}')
check("mirror does not start: the partition, with a note", len(m) == 1 and part in m[0] and "mounted directly" in r.stdout)
r, m, part, w = run('{"device": "/dev/drbd0"}', fail_dev="/dev/drbd0")
check("DRBD device does not mount: falls back to the partition", len(m) == 2 and part in m[1] and "mounting" in r.stdout)
check("sysvol link to utdata", os.readlink(os.path.join(w, "i-data", "sysvol")) == "utdata")
print("DATA MOUNT TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", fails))
sys.exit(1 if fails else 0)
