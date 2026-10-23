#!/usr/bin/env python3
"""PC test of untrash-copybtn (stock COPY/SYNC button), no root:
  python3 image/tests/test-copybtn-host.py RCLONEROOT
Real rsync (host) and rclone (RCLONEROOT, extracted deb).  A fake mount table
puts two USB partitions under e-data; checks: copy USB -> NAS into
<date>/Extvolume<N> for every partition, the stock "choose" flag limits the
source, copy NAS -> USB, backup of replaced files, mirror sync2Vol with
deletion (deleted file kept in the backup folder), two-way sync, missing
share reported (and the alert hook called), LED states."""
import glob
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-copybtn")
fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name, flush=True)
    fails += 0 if cond else 1


def main():
    rclone_dir = os.path.join(os.path.abspath(sys.argv[1]), "usr/bin")
    with tempfile.TemporaryDirectory() as W:
        ed, share, bak = W + "/e-data", W + "/i-data/vol/Daten", W + "/i-data/vol/Sicherung"
        u1, u2 = ed + "/aaaa", ed + "/bbbb"
        for d in (u1 + "/Fotos", u2, share, bak, W + "/leds/copy-green", W + "/leds/copy-red"):
            os.makedirs(d)
        open(u1 + "/Fotos/a.jpg", "w").write("A")
        open(u2 + "/b.txt", "w").write("B")
        open(W + "/mounts", "w").write("/dev/sda1 / ext4 rw 0 0\n/dev/sdc1 %s vfat rw 0 0\n/dev/sdc2 %s exfat rw 0 0\n" % (u1, u2))
        notified = W + "/notified"
        open(W + "/notify", "w").write("#!/bin/sh\necho \"$*\" >> %s\n" % notified)
        os.chmod(W + "/notify", 0o755)
        settings = W + "/settings.json"

        def cfg(copy=None, sync=None):
            json.dump({"copybtn": {"copy": copy or {}, "sync": sync or {}}}, open(settings, "w"))
        env = dict(os.environ, ZT_SETTINGS=settings, ZT_COPYBTN_EDATA=ed, ZT_COPYBTN_MOUNTS=W + "/mounts",
                   ZT_COPYBTN_STATUS=W + "/status.json", ZT_COPYBTN_LEDS=W + "/leds", ZT_NOTIFY_TOOL=W + "/notify",
                   ZT_COPYBTN_WORK=W + "/work", PATH=rclone_dir + ":" + os.environ["PATH"])

        def run(kind):
            r = subprocess.run([TOOL, kind], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            return r.returncode, r.stdout, json.load(open(W + "/status.json"))

        cfg()
        rc, out, st = run("copy")
        check("no share set: refused, alert hook called, red LED", rc == 1 and not st["ok"] and os.path.exists(notified)
              and open(W + "/leds/copy-red/brightness").read() == "1")
        cfg(copy={"share_path": share, "bak_path": "", "direction": "cp2Vol", "newdir": True})
        rc, out, st = run("copy")
        got = sorted(os.path.relpath(p, share) for p in glob.glob(share + "/*/*/**", recursive=True) if os.path.isfile(p))
        check("copy USB -> NAS: <date>/Extvolume1 + Extvolume2", rc == 0 and st["ok"] and len(got) == 2 and
              got[0].endswith("Extvolume1/Fotos/a.jpg") and got[1].endswith("Extvolume2/b.txt"))
        check("green LED on after success", open(W + "/leds/copy-green/brightness").read() == "1")
        open(u2 + "/.ZyXELchooseCopy.txt", "w").write("x")
        for d in glob.glob(share + "/*"):
            subprocess.run(["rm", "-rf", d])
        rc, out, st = run("copy")
        got = [os.path.relpath(p, share) for p in glob.glob(share + "/**", recursive=True) if os.path.isfile(p)]
        check("choose flag: only that partition, flag file not copied", rc == 0 and len(got) == 1 and got[0].endswith("Extvolume2/b.txt"))
        os.unlink(u2 + "/.ZyXELchooseCopy.txt")
        open(share + "/neu.txt", "w").write("N")
        cfg(copy={"share_path": share, "bak_path": "", "direction": "cp2USB", "newdir": False})
        rc, out, st = run("copy")
        check("copy NAS -> USB (no new folder)", rc == 0 and open(u1 + "/neu.txt").read() == "N" and open(u2 + "/neu.txt").read() == "N")
        open(u1 + "/neu.txt", "w").write("OLD")
        cfg(copy={"share_path": share, "bak_path": bak, "direction": "cp2USB", "newdir": False})
        rc, out, st = run("copy")
        kept = glob.glob(bak + "/*/neu.txt")
        check("replaced file kept in the backup folder", rc == 0 and open(u1 + "/neu.txt").read() == "N" and kept and open(kept[0]).read() == "OLD")
        os.unlink(u2 + "/neu.txt")
        open(W + "/mounts", "w").write("/dev/sdc2 %s exfat rw 0 0\n" % u2)
        for d in glob.glob(bak + "/*"):
            subprocess.run(["rm", "-rf", d])
        cfg(sync={"share_path": share, "bak_path": bak, "direction": "sync2Vol"})
        rc, out, st = run("sync")
        check("sync2Vol mirrors USB -> NAS, deletions into the backup", rc == 0 and sorted(os.listdir(share)) == sorted(os.listdir(u2))
              and not os.path.exists(share + "/neu.txt") and glob.glob(bak + "/backup-*/neu.txt"))
        open(u2 + "/usb-only.txt", "w").write("U")
        open(share + "/nas-only.txt", "w").write("S")
        cfg(sync={"share_path": share, "bak_path": "", "direction": "twoWay"})
        rc, out, st = run("sync")
        check("two-way sync (rclone bisync): both sides have both files", rc == 0 and os.path.isfile(share + "/usb-only.txt")
              and os.path.isfile(u2 + "/nas-only.txt"))
        os.unlink(share + "/nas-only.txt")
        rc, out, st = run("sync")
        check("two-way second run: deletion mirrored", rc == 0 and not os.path.exists(u2 + "/nas-only.txt"))
    print("COPYBTN TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
