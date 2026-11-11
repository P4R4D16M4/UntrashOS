#!/usr/bin/env python3
"""PC test of UntrashKey (pylib/untrash_key.py, untrash-key): fake sysfs
with a USB stick, a directory standing in for its FAT, the systemctl/pkill
calls recorded.  Pairing only after a replug, presence bound to the attach
(diskseq), forged sticks, enforcement of SSH, configuration rules."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash")
W = tempfile.mkdtemp()
STICK = W + "/stick"
SYSLOG = W + "/sys.log"
os.environ.update(ZT_KEY_ROOT=W + "/root", ZT_KEY_STICKDIR=STICK, ZT_KEY_SYSLOG=SYSLOG)
sys.path.insert(0, os.path.join(LIB, "pylib"))
import untrash_key as K  # noqa: E402

R = W + "/root"
fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


def plug(seq, usb=True, dev="sdb"):
    """Attach the stick: /dev/<dev>1 with label UNTRASHPK, disk attach number SEQ."""
    unplug()
    os.makedirs(R + "/dev/disk/by-label", exist_ok=True)
    open(R + "/dev/%s1" % dev, "w").close()
    os.symlink("../../%s1" % dev, R + "/dev/disk/by-label/UNTRASHPK")
    d = R + "/sys/devices/platform/xhci/%s/host2/target2:0:0/2:0:0:0/block/%s" % ("usb1/1-1/1-1:1.0" if usb else "ata1", dev)
    os.makedirs(d + "/%s1" % dev, exist_ok=True)
    open(d + "/diskseq", "w").write("%d\n" % seq)
    os.makedirs(R + "/sys/class/block", exist_ok=True)
    for n, t in ((dev, d), (dev + "1", d + "/%s1" % dev)):
        if os.path.lexists(R + "/sys/class/block/" + n):
            os.remove(R + "/sys/class/block/" + n)
        os.symlink(t, R + "/sys/class/block/" + n)


def unplug():
    for p in (R + "/dev/disk/by-label/UNTRASHPK", R + "/dev/sdb1"):
        if os.path.lexists(p):
            os.remove(p)


def log():
    try:
        return open(SYSLOG).read()
    except OSError:
        return ""


def fails_with(fn, *a):
    try:
        fn(*a)
    except K.KeyFail as e:
        return str(e)
    return None


os.makedirs(STICK + "/UNTRASH")
check("vanilla: off, everything allowed without a stick", not K.load()["enabled"] and K.allow("ssh") and K.allow("terminal"))
check("no keys: switching on refused", fails_with(K.configure, {"enabled": True}) == "Pair a stick first.")

plug(5)
check("the plugged UntrashOS stick is seen", K.stick() == {"dev": "/dev/sdb1", "seq": "5"})
s = K.pair_start("Keyring")
check("pairing waits", s["pairing"]["state"] == "waiting")
s = K.pair_poll()
check("a stick already plugged in is not paired (no replug)", s["pairing"]["state"] == "waiting" and not s["keys"])
plug(6)
s = K.pair_poll()
check("replugged: paired", s["pairing"]["state"] == "done" and [k["name"] for k in s["keys"]] == ["Keyring"])
cfg = json.load(open(R + "/etc/untrash/untrashkey.json"))
kf = STICK + "/UNTRASH/untrashkey/%s.key" % cfg["nas"]
secret = open(kf).read().split()[2]
check("the stick holds the secret, the NAS only its SHA-256", os.path.isfile(kf) and secret not in json.dumps(cfg)
      and len(cfg["keys"][0]["hash"]) == 64)
check("config root-only", os.stat(R + "/etc/untrash/untrashkey.json").st_mode & 0o077 == 0)
check("paired stick present, UntrashKey still off", K.present() and not K.load()["enabled"])

open(SYSLOG, "w").close()
s = K.configure({"enabled": True})
check("switched on with the key plugged in; default areas", s["enabled"] and s["protect"] == K.DEFAULT_PROTECT)
check("SSH started while the key is in", "systemctl start --no-block ssh.service" in log())
check("allowed with the key: ssh, terminal", K.allow("ssh") and K.allow("terminal"))

open(SYSLOG, "w").close()
unplug()
check("pulled: ssh and terminal refused, data (not protected) still allowed",
      not K.allow("ssh") and not K.allow("terminal") and K.allow("data"))
check("pulled: sshd stopped and its sessions ended", "systemctl stop ssh.service" in log() and "pkill -x sshd" in log())
check("CLI allow ssh: exit 1 without the key",
      subprocess.run([sys.executable, LIB + "/untrash-key", "allow", "ssh"], stderr=subprocess.DEVNULL).returncode == 1)
check("changes refused without the key", fails_with(K.configure, {"enabled": False}) == "Plug in your UntrashKey.")

plug(7)
check("plugged in again (new attach): verified, allowed", K.allow("ssh"))
check("CLI allow ssh: exit 0 with the key", subprocess.run([sys.executable, LIB + "/untrash-key", "allow", "ssh"]).returncode == 0)
open(kf, "w").write("UNTRASHKEY1 %s %s\n" % (cfg["nas"], "0" * 64))
check("same attach keeps its verification (stick is read once)", K.present())
plug(8)
check("another stick with the label but a wrong secret: no key", not K.present())
open(kf, "w").write("UNTRASHKEY1 %s %s\n" % (cfg["nas"], secret))
plug(9, usb=False)
check("a non-USB disk with the label never counts", K.stick() is None and not K.present())

plug(10)
check("remove the last key while on: refused", fails_with(K.remove, cfg["keys"][0]["id"]) ==
      "Switch UntrashKey off before removing the last key.")
check("unknown area refused", fails_with(K.configure, {"protect": ["ssh", "root"]}) == "Unknown area.")
s = K.configure({"protect": ["ssh", "terminal", "data"]})
check("areas configurable", s["protect"] == ["ssh", "terminal", "data"])
unplug()
check("unprotected area works without the key, protected not", K.allow("system") and not K.allow("data"))

# SSH keys on the stick: root logs in with them only while it is plugged in
plug(11)
pub = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyForTheUntrashKeyTest000000000000 test@pc"
check("bad SSH key line refused", fails_with(K.ssh_keys, ["command=\"sh\" " + pub]) is not None)
K.ssh_keys([pub, ""])
sk = R + "/run/untrash/servicekey/authorized_keys"
check("SSH key written to the stick and active for root", K.ssh_keys()["keys"] == [pub] and open(sk).read() == pub + "\n")
unplug()
K.present()
check("pulled: the stick's SSH keys are gone from the NAS", not os.path.exists(sk))

# a second key; pairing the same stick again replaces its old secret
plug(12)
K.pair_start("Spare")
plug(13)
s = K.pair_poll()
check("same stick paired again: still one key, new name", [k["name"] for k in s["keys"]] == ["Spare"] and K.present())
K.pair_start("Late")
k = json.load(open(R + "/run/untrash/untrashkey-pair.json"))
k["expires"] = 1
json.dump(k, open(R + "/run/untrash/untrashkey-pair.json", "w"))
check("pairing window expires", K.pair_poll()["pairing"]["state"] == "expired")
check("switched off with the key", not K.configure({"enabled": False})["enabled"])
unplug()
check("off: everything allowed again", K.allow("ssh") and K.allow("terminal"))

shutil.rmtree(W)
print("FAILURES %d" % fails)
sys.exit(1 if fails else 0)
