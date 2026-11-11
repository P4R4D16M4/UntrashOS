#!/usr/bin/env python3
"""PC test of the stick archive and key sticks (pylib/untrash_stick.py with
untrash_key.py): archive from a fake installer stick (release files checked,
no INSTALL marker, the completed stock run), a newer system from an update,
a new stick on a fake USB disk (disk commands recorded, a directory as its
FAT), the key bound to an administrator."""
import hashlib
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
W = tempfile.mkdtemp()
os.environ.update(ZT_KEY_ROOT=W + "/root", ZT_KEY_STICKDIR=W + "/oldstick", ZT_KEY_SYSLOG=W + "/sys.log",
                  ZT_STICK_ARCHIVE=W + "/archive", ZT_STICK_MNT=W + "/newstick", ZT_STICK_CMDLOG=W + "/cmd.log",
                  ZT_STICK_SYS=W + "/root/sys/class/block")
sys.path.insert(0, os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "pylib"))
import untrash_key as K  # noqa: E402
import untrash_stick as S  # noqa: E402

fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


def put(base, rel, data):
    os.makedirs(os.path.dirname(os.path.join(base, rel)), exist_ok=True)
    open(os.path.join(base, rel), "wb").write(data if isinstance(data, bytes) else data.encode())


def sums(base, rels):
    put(base, "SHA256SUMS", "".join("%s  %s\n" % (hashlib.sha256(open(os.path.join(base, r), "rb").read()).hexdigest(), r)
                                   for r in rels))


def fails_with(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except (S.StickFail, K.KeyFail) as e:
        return str(e)
    return None


# an installer stick after a completed install: release files, INSTALL marker, stock run
OLD = W + "/oldstick"
rel = {"nas5xx_check_file": "x", "usb_key_func.sh": "#!/bin/sh\n", "README.txt": "UntrashOS 1.2\n",
       "UNTRASH/loader.uImage": b"\x27\x05\x19\x56loader", "UNTRASH/manifest.env": "VERSION=1.2\n",
       "UNTRASH/system/slot.utslot": b"S" * 20000, "UNTRASH/system/slot.sha256": "x\n", "UNTRASH/system/version": "1.2\n",
       "UNTRASH/INSTALL": "install\n"}
for r, d in rel.items():
    put(OLD, r, d)
sums(OLD, sorted(rel))
run = "UNTRASH/install-20261101-120000"
put(OLD, run + "/device.env", "ETH0_MAC=02:5A:54:00:00:01\nACTIVE_SLOT=1\nMODEL_ID=B403\n")
put(OLD, run + "/install.log", "...\nRESULT DONE loader in kernel2\n")
put(OLD, run + "/flash/mtd2.raw.bin", b"E" * 4096)
sums(OLD + "/" + run + "/flash", ["mtd2.raw.bin"])
put(OLD, "UNTRASH/install-20261101-110000/install.log", "RESULT FAILED\n")       # an earlier failed run
put(OLD, "UNTRASH/ssh/authorized_keys", "ssh-ed25519 AAAA dev@pc\n")            # never copied

m = S.archive_from(OLD, log=print)
A = W + "/archive"
check("archive: version and stock run", m["version"] == "1.2" and m["stock"] == "install-20261101-120000")
check("archive: release files, no INSTALL marker, no dev keys",
      os.path.isfile(A + "/tree/UNTRASH/loader.uImage") and not os.path.exists(A + "/tree/UNTRASH/INSTALL")
      and not os.path.exists(A + "/tree/UNTRASH/ssh") and "UNTRASH/INSTALL" not in open(A + "/tree/SHA256SUMS").read())
check("archive: only the completed stock run", os.listdir(A + "/stock") == ["install-20261101-120000"])
check("archive: root only (MAC addresses in the backup)", os.stat(A).st_mode & 0o077 == 0)
put(OLD, "UNTRASH/loader.uImage", b"damaged")
check("a damaged stick file is refused, the archive stays", fails_with(S.archive_from, OLD) and S.info()["version"] == "1.2")
put(OLD, "UNTRASH/loader.uImage", b"\x27\x05\x19\x56loader")
check("without stock (other NAS): archive without backup", S.archive_from(OLD, stock=False)["stock"] is None)
S.archive_from(OLD)

upd = W + "/u.utslot"
open(upd, "wb").write(b"N" * 30000)
check("newer system from a verified update", S.refresh_system(upd, "1.3") and S.info()["version"] == "1.3"
      and open(A + "/tree/UNTRASH/system/slot.utslot", "rb").read() == b"N" * 30000
      and "30000" not in open(A + "/tree/UNTRASH/system/slot.sha256").read() and "21808 slot.head.length" in open(A + "/tree/UNTRASH/system/slot.sha256").read())

# a new USB disk appears
SYS = W + "/root/sys"


def disk(n, seq, mib, usb=True):
    d = SYS + "/devices/%s/block/%s" % ("usb2/2-1" if usb else "ata3", n)
    os.makedirs(d, exist_ok=True)
    open(d + "/diskseq", "w").write(str(seq))
    open(d + "/size", "w").write(str(mib * 2048))
    os.makedirs(SYS + "/class/block", exist_ok=True)
    os.symlink(d, SYS + "/class/block/" + n)


disk("sda", 3, 4000000, usb=False)
disk("sdc", 9, 64)
check("only USB disks attached after the request count", [x["dev"] for x in S.usb_disks(8)] == ["/dev/sdc"] and S.usb_disks(9) == [])
check("a stick that is too small is refused", "too small" in (fails_with(S.make_stick, S.usb_disks(8)[0], lambda m: "x") or ""))
disk("sdd", 10, 2000)

K.pair_start("Anna's key", "anna", mode="create", since=9)
started = []
st = K.pair_poll(start_create=lambda d, p: started.append((d, p)))
check("create mode hands the new disk over", st["pairing"]["state"] == "writing" and started and started[0][0]["dev"] == "/dev/sdd")
d, p = started[0]
steps = []
kid = S.make_stick(d, lambda mnt: K.issue(mnt, p["name"], p["user"]), progress=steps.append)
N = W + "/newstick"
cmds = open(W + "/cmd.log").read()
check("disk erased and FAT32 UNTRASHPK made", "wipefs -a /dev/sdd" in cmds and "parted -s /dev/sdd mklabel msdos" in cmds
      and "mkfs.vfat -F 32 -n UNTRASHPK /dev/sdd1" in cmds)
check("new stick: system 1.3, no INSTALL marker", open(N + "/UNTRASH/system/version").read() == "1.3\n"
      and not os.path.exists(N + "/UNTRASH/INSTALL"))
check("new stick: stock backup for the way back", os.path.isfile(N + "/UNTRASH/install-20261101-120000/flash/mtd2.raw.bin"))
cfg = json.load(open(W + "/root/etc/untrash/untrashkey.json"))
k = [x for x in cfg["keys"] if x["id"] == kid]
check("new stick: key file, key bound to anna", k and k[0]["user"] == "anna" and k[0]["name"] == "Anna's key"
      and os.path.isfile(N + "/UNTRASH/untrashkey/%s.key" % cfg["nas"]))
check("progress reported", steps[0] == "Erasing the stick" and steps[-1] == "Checking what was written")

# the key opens only for its administrator (sshd: any key)
K.pair_update(state="done", key=kid)
os.makedirs(W + "/root/dev/disk/by-label", exist_ok=True)
open(W + "/root/dev/sdd1", "w").close()
os.symlink("../../sdd1", W + "/root/dev/disk/by-label/UNTRASHPK")
os.makedirs(SYS + "/devices/usb2/2-1/block/sdd/sdd1", exist_ok=True)
os.symlink(SYS + "/devices/usb2/2-1/block/sdd/sdd1", SYS + "/class/block/sdd1")
os.environ["ZT_KEY_STICKDIR"] = N
K.STICKDIR = N
check("anna's key is plugged in", (K.current() or {}).get("key") == kid)
K.configure({"enabled": True}, user="anna")
check("on: opens for anna and for sshd, not for admin",
      K.allow("terminal", user="anna") and K.allow("ssh") and not K.allow("terminal", user="admin"))
check("admin cannot change UntrashKey with anna's key", fails_with(K.configure, {"enabled": False}, user="admin") == "Plug in your UntrashKey.")
check("anna can", K.configure({"enabled": False}, user="anna")["enabled"] is False)

shutil.rmtree(W)
print("FAILURES %d" % fails)
sys.exit(1 if fails else 0)
