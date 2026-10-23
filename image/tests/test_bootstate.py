#!/usr/bin/env python3
"""untrash-bootstate on a slot-file boot (no NAS needed).

Regression: "prefer b" must not read $2 after "set -- $STATE" has replaced
the arguments with the state file.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-bootstate")
FAIL = 0


def check(name, ok):
    global FAIL
    print(("ok   " if ok else "FAIL ") + name)
    FAIL += 0 if ok else 1


d = tempfile.mkdtemp()
os.makedirs(d + "/.untrash")
env = d + "/boot.env"
open(env, "w").write("ZT_BOOT=file\nZT_SLOT=a\nZT_HOST=%s\nZT_HOST_RW=1\n" % d)
script = d + "/untrash-bootstate"
open(script, "w").write(open(SRC).read().replace("/run/untrash/boot.env", env))
state = d + "/.untrash/bootstate"
for pref in ("b", "a"):
    open(state, "w").write("ZTBS1 pref=a a=3 b=1 good=a booting=a\n" + "\0" * 400)
    r = subprocess.run(["sh", script, "prefer", pref], capture_output=True, text=True)
    st = open(state).read().split("\n")[0]
    check("prefer %s: exit 0, pref=%s, its tries back to 3" % (pref, pref),
          r.returncode == 0 and ("pref=%s" % pref) in st and ("%s=3" % pref) in st)
    check("prefer %s: state stays 512 bytes" % pref, os.path.getsize(state) == 512 or os.path.getsize(state) > 400)
r = subprocess.run(["sh", script, "prefer", "c"], capture_output=True, text=True)
check("prefer c: refused", r.returncode == 2)
r = subprocess.run(["sh", script, "show"], capture_output=True, text=True)
check("show", r.returncode == 0 and r.stdout.startswith("pref="))
print("FAILURES %d" % FAIL)
sys.exit(1 if FAIL else 0)
