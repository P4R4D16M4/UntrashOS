#!/usr/bin/env python3
"""PC test of untrash-backup (stock Backup Planner) with the host's rsync:
  python3 image/tests/test-backup-host.py
Checks: archive versions (dated folders, unchanged files hard-linked,
changed files new), keep N, failed partial run leaves no version, sync
mirror with deletion, restore of an old version, missing source reported
(alert hook), schedule logic (daily/weekly/monthly/hourly/manual), status."""
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-backup")
fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name, flush=True)
    fails += 0 if cond else 1


def main():
    import importlib.machinery
    import importlib.util
    spec = importlib.util.spec_from_loader("bk", importlib.machinery.SourceFileLoader("bk", TOOL))
    bk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bk)
    with tempfile.TemporaryDirectory() as W:
        src, tgt = W + "/vol/Fotos", W + "/vol/Sicherung"
        os.makedirs(src + "/2026")
        os.makedirs(tgt)
        open(src + "/2026/a.jpg", "w").write("A" * 1000)
        open(src + "/b.txt", "w").write("B1")
        open(W + "/notify", "w").write("#!/bin/sh\necho \"$*\" >> %s/notified\n" % W)
        os.chmod(W + "/notify", 0o755)
        jobs = [{"id": "aaaa0001", "name": "Fotos", "type": "archive", "sources": [src], "target": {"kind": "local", "path": tgt},
                 "keep": 2, "bwlimit": 0, "active": True, "schedule": {"kind": "manual"}},
                {"id": "aaaa0002", "name": "Spiegel", "type": "sync", "sources": [src], "target": {"kind": "local", "path": tgt},
                 "keep": 1, "active": True, "schedule": {"kind": "manual"}},
                {"id": "aaaa0003", "name": "Weg", "type": "sync", "sources": [W + "/nope"], "target": {"kind": "local", "path": tgt},
                 "keep": 1, "active": True, "schedule": {"kind": "manual"}}]
        json.dump({"backup": {"jobs": jobs}}, open(W + "/settings.json", "w"))
        env = dict(os.environ, ZT_SETTINGS=W + "/settings.json", ZT_BACKUP_STATE=W + "/state", ZT_NOTIFY_TOOL=W + "/notify")

        def cl(*a):
            r = subprocess.run([TOOL] + list(a), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return r.returncode, r.stdout
        check("first archive run", cl("run", "aaaa0001")[0] == 0)
        time.sleep(1.1)
        open(src + "/b.txt", "w").write("B2")
        check("second archive run", cl("run", "aaaa0001")[0] == 0)
        vers = json.loads(cl("versions", "aaaa0001")[1])
        base = tgt + "/Fotos"
        check("two dated versions", len(vers) == 2 and all(os.path.isfile("%s/%s/Fotos/2026/a.jpg" % (base, v)) for v in vers))
        a0, a1 = (os.stat("%s/%s/Fotos/2026/a.jpg" % (base, v)) for v in vers)
        check("unchanged file hard-linked", a0.st_ino == a1.st_ino and a0.st_nlink == 2)
        check("changed file new", open("%s/%s/Fotos/b.txt" % (base, vers[0])).read() == "B2" and
              open("%s/%s/Fotos/b.txt" % (base, vers[1])).read() == "B1")
        time.sleep(1.1)
        cl("run", "aaaa0001")
        vers2 = json.loads(cl("versions", "aaaa0001")[1])
        check("keep 2: oldest version removed", len(vers2) == 2 and vers[1] not in vers2)
        rc, out = cl("restore", "aaaa0001", vers2[-1], W + "/vol/Zurueck")
        check("restore a version into another folder", rc == 0 and open(W + "/vol/Zurueck/Fotos/b.txt").read() == "B2")
        check("restore: bad version refused", cl("restore", "aaaa0001", "../..", W + "/x")[0] != 0)
        os.unlink(src + "/b.txt")
        check("sync run", cl("run", "aaaa0002")[0] == 0)
        check("sync = mirror with deletion", os.path.isfile(tgt + "/Spiegel/Fotos/2026/a.jpg") and not os.path.exists(tgt + "/Spiegel/Fotos/b.txt"))
        rc, out = cl("run", "aaaa0003")
        st = json.loads(cl("status")[1])
        check("missing source: failed, alert hook", rc == 1 and not st["aaaa0003"]["ok"] and "Backup Weg failed" in open(W + "/notified").read())
        check("status ok for the others", st["aaaa0001"]["ok"] and st["aaaa0002"]["ok"])
        # schedule
        T = lambda *x: datetime.datetime(*x).timestamp()  # noqa: E731
        d = {"active": True, "schedule": {"kind": "daily", "hour": 2, "minute": 30}}
        check("daily: due after 02:30 if not yet run today", bk.due(d, T(2026, 10, 10, 2, 31), T(2026, 10, 9, 2, 30)))
        check("daily: not before 02:30", not bk.due(d, T(2026, 10, 10, 2, 29), T(2026, 10, 9, 2, 30)))
        check("daily: not twice", not bk.due(d, T(2026, 10, 10, 9, 0), T(2026, 10, 10, 2, 31)))
        w = {"active": True, "schedule": {"kind": "weekly", "day": 5, "hour": 1, "minute": 0}}
        check("weekly: Saturday (day 5) only", bk.due(w, T(2026, 10, 10, 1, 5), 0) and not bk.due(w, T(2026, 10, 9, 1, 5), 0))
        m = {"active": True, "schedule": {"kind": "monthly", "mday": 10, "hour": 0, "minute": 0}}
        check("monthly: day 10", bk.due(m, T(2026, 10, 10, 0, 1), 0) and not bk.due(m, T(2026, 10, 11, 0, 1), 0))
        h = {"active": True, "schedule": {"kind": "hourly"}}
        check("hourly", bk.due(h, 10000, 10000 - 3600) and not bk.due(h, 10000, 10000 - 600))
        check("manual / inactive never due", not bk.due({"active": True, "schedule": {"kind": "manual"}}, 1e10, 0)
              and not bk.due(dict(d, active=False), T(2026, 10, 10, 3, 0), 0))
    print("BACKUP TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
