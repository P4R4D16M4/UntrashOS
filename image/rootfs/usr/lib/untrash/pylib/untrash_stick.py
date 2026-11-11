"""The UntrashOS stick, kept by the installed system.

The installer stores what a new stick needs in the system state, so the NAS
can make more sticks later: a replacement, or an UntrashKey for a second
user (docs/architecture/untrashkey.md).

/var/lib/untrash/stick/
  tree/      the release files of the stick (the ones its SHA256SUMS lists),
             without UNTRASH/INSTALL: a stick made from it never starts the
             installer; it boots the system only when nothing else can
  stock/<install-run>/   the completed PartnerKey install run of THIS NAS:
             flash backup, device.env, etc-zyxel.tar (way D, loader updates)
  meta.json  {"version", "stock", "time", "bytes"}

  archive_from(stick_dir, dest)   copy a mounted stick into an archive
  info(root)                      what the archive holds (None if there is none)
  refresh_system(utslot, version) a newer system (verified update) for new sticks
  make_stick(disk, issue, progress)  erase a USB disk and write a stick from
                                  the archive; issue(mnt) writes its key file

Test hooks: ZT_STICK_ARCHIVE (archive directory), ZT_STICK_MNT (directory
standing in for the mounted new partition; disk commands are then only
recorded in ZT_STICK_CMDLOG), ZT_STICK_SYS (sysfs block root).
"""
import datetime
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

ARCHIVE = os.environ.get("ZT_STICK_ARCHIVE", "/var/lib/untrash/stick")
FAKE_MNT = os.environ.get("ZT_STICK_MNT")
CMDLOG = os.environ.get("ZT_STICK_CMDLOG")
SYSBLOCK = os.environ.get("ZT_STICK_SYS", "/sys/class/block")
MARKERS = ("UNTRASH/INSTALL",)       # in the release SHA256SUMS, never on a stick made here
PART_START_MIB = 32                  # as install/mk-stick-image.sh: MBR + blackbox, FAT32 from 32 MiB


class StickFail(Exception):
    pass


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _du(path):
    n = 0
    for d, _ds, fs in os.walk(path):
        for f in fs:
            try:
                n += os.path.getsize(os.path.join(d, f))
            except OSError:
                pass
    return n


def _sums(path):
    """[(sha, relative path)] of a SHA256SUMS file."""
    out = []
    for line in open(path, errors="replace"):
        m = re.match(r"^([0-9a-f]{64}) [ *]?(?:\./)?(.+)$", line.rstrip("\n"))
        if m and ".." not in m.group(2).split("/"):
            out.append((m.group(1), m.group(2)))
    return out


def stock_run(stick_dir):
    """The newest completed install run of the PartnerKey on the stick."""
    best = None
    for d in sorted(glob.glob(os.path.join(stick_dir, "UNTRASH", "install-2*"))):
        try:
            done = "RESULT DONE" in open(os.path.join(d, "install.log"), errors="replace").read()
        except OSError:
            done = False
        if done and os.path.isfile(os.path.join(d, "device.env")) and os.path.isfile(os.path.join(d, "flash", "SHA256SUMS")):
            best = d
    return best


def archive_from(stick_dir, dest=None, log=lambda m: None, stock=True):
    """Copy the release files (checked against the stick's SHA256SUMS) and
    (STOCK) the stock install run of a mounted stick into DEST (atomic)."""
    dest = dest or ARCHIVE
    sums = os.path.join(stick_dir, "SHA256SUMS")
    if not os.path.isfile(sums):
        raise StickFail("Not an UntrashOS stick (no SHA256SUMS).")
    new = dest + ".new"
    shutil.rmtree(new, ignore_errors=True)
    tree = os.path.join(new, "tree")
    os.makedirs(tree)
    keep = []
    for sha, rel in _sums(sums):
        if rel in MARKERS:
            continue
        src = os.path.join(stick_dir, rel)
        if not os.path.isfile(src) or _sha(src) != sha:
            shutil.rmtree(new, ignore_errors=True)
            raise StickFail("Stick file %s is missing or damaged." % rel)
        os.makedirs(os.path.dirname(os.path.join(tree, rel)), exist_ok=True)
        shutil.copy2(src, os.path.join(tree, rel))
        keep.append("%s  %s\n" % (sha, rel))
    with open(os.path.join(tree, "SHA256SUMS"), "w") as f:
        f.write("".join(keep))
    run = stock_run(stick_dir) if stock else None
    if run:
        shutil.copytree(run, os.path.join(new, "stock", os.path.basename(run)), symlinks=False)
        log("Stock backup %s stored" % os.path.basename(run))
    else:
        log("No completed stock install run on the stick: new sticks cannot go back to stock")
    try:
        ver = open(os.path.join(tree, "UNTRASH", "system", "version")).read().strip()
    except OSError:
        ver = "?"
    meta = {"version": ver, "stock": os.path.basename(run) if run else None,
            "time": datetime.datetime.now().isoformat(timespec="seconds"), "bytes": _du(new)}
    with open(os.path.join(new, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    old = dest + ".old"
    shutil.rmtree(old, ignore_errors=True)
    if os.path.isdir(dest):
        os.rename(dest, old)
    os.rename(new, dest)
    shutil.rmtree(old, ignore_errors=True)
    os.chmod(dest, 0o700)              # the flash backup carries the device's MAC addresses
    log("Stick archive %s stored (%d MB)" % (ver, meta["bytes"] // 1000000))
    return meta


def info(dest=None):
    dest = dest or ARCHIVE
    try:
        m = json.load(open(os.path.join(dest, "meta.json")))
    except (OSError, ValueError):
        return None
    return m if os.path.isfile(os.path.join(dest, "tree", "SHA256SUMS")) else None


def refresh_system(utslot, version, dest=None):
    """New sticks get the newest system: the verified update image."""
    dest = dest or ARCHIVE
    sysd = os.path.join(dest, "tree", "UNTRASH", "system")
    if not info(dest) or not os.path.isdir(sysd):
        return False
    shutil.copyfile(utslot, os.path.join(sysd, "slot.utslot.new"))
    os.replace(os.path.join(sysd, "slot.utslot.new"), os.path.join(sysd, "slot.utslot"))
    size = os.path.getsize(os.path.join(sysd, "slot.utslot"))
    with open(os.path.join(sysd, "slot.utslot"), "rb") as f:     # head + 8 KiB signed trailer
        head = hashlib.sha256()
        left = size - 8192
        while left > 0:
            b = f.read(min(left, 1 << 20))
            head.update(b)
            left -= len(b)
        trailer = hashlib.sha256(f.read()).hexdigest()
    whole = _sha(os.path.join(sysd, "slot.utslot"))
    with open(os.path.join(sysd, "slot.sha256"), "w") as f:
        f.write("%s slot.utslot\n%s slot.head\n%s slot.trailer\n%d slot.head.length\n" % (whole, head.hexdigest(), trailer, size - 8192))
    with open(os.path.join(sysd, "version"), "w") as f:
        f.write(version + "\n")
    rels = ("UNTRASH/system/slot.utslot", "UNTRASH/system/slot.sha256", "UNTRASH/system/version")
    sums = os.path.join(dest, "tree", "SHA256SUMS")
    lines = [l for l in open(sums) if l.split()[-1] not in rels]
    lines += ["%s  %s\n" % (_sha(os.path.join(dest, "tree", r)), r) for r in rels]
    with open(sums, "w") as f:
        f.write("".join(sorted(lines, key=lambda l: l.split()[-1])))
    meta = json.load(open(os.path.join(dest, "meta.json")))
    meta.update(version=version, bytes=_du(dest))
    with open(os.path.join(dest, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1, sort_keys=True)
    return True


# ------------------------------------------------------------- new stick

def _run(cmd, **kw):
    if CMDLOG:
        with open(CMDLOG, "a") as f:
            f.write(" ".join(cmd) + "\n")
        return ""
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, **kw)
    if r.returncode:
        raise StickFail("%s: %s" % (cmd[0], (r.stderr or r.stdout).strip()[-300:]))
    return r.stdout


def usb_disks(since=0):
    """Whole USB disks attached after diskseq SINCE: [{"dev", "seq", "bytes", "parts"}]."""
    out = []
    for n in sorted(os.listdir(SYSBLOCK)) if os.path.isdir(SYSBLOCK) else []:
        p = os.path.realpath(os.path.join(SYSBLOCK, n))
        if "/usb" not in p or os.path.exists(os.path.join(p, "partition")):
            continue
        try:
            seq = int(open(os.path.join(p, "diskseq")).read())
            size = int(open(os.path.join(p, "size")).read()) * 512
        except (OSError, ValueError):
            continue
        if seq > since and size > 0:
            parts = sorted(x for x in os.listdir(p) if x.startswith(n) and os.path.exists(os.path.join(p, x, "partition")))
            out.append({"dev": "/dev/" + n, "seq": seq, "bytes": size, "parts": ["/dev/" + x for x in parts]})
    return out


def need_bytes(dest=None):
    m = info(dest)
    return (m["bytes"] if m else 0) + (PART_START_MIB + 256) * 1024 * 1024


def make_stick(disk, issue, progress=lambda m: None, dest=None):
    """Erase DISK (a dict of usb_disks) and write a stick from the archive:
    MBR with the blackbox header, FAT32 "UNTRASHPK" from 32 MiB, the release
    files, the stock install run; issue(mnt) adds the key.  Checks the files
    read back."""
    dest = dest or ARCHIVE
    if not info(dest):
        raise StickFail("No stick archive on this NAS.")
    if disk["bytes"] < need_bytes(dest):
        raise StickFail("The stick is too small: %d MB needed." % (need_bytes(dest) // 1000000))
    dev = disk["dev"]
    if not FAKE_MNT:
        for line in open("/proc/mounts"):
            if line.split()[0].startswith(dev):          # its own USB volume: unmount it first
                for p in disk["parts"]:
                    subprocess.run(["systemctl", "stop", "untrash-usb@%s.service" % os.path.basename(p)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
        for line in open("/proc/mounts"):
            if line.split()[0].startswith(dev):
                raise StickFail("%s is still in use (%s)." % (dev, line.split()[1]))
    progress("Erasing the stick")
    _run(["wipefs", "-a", dev])
    _run(["parted", "-s", dev, "mklabel", "msdos", "mkpart", "primary", "fat32", "%dMiB" % PART_START_MIB, "100%",
          "set", "1", "lba", "on"])
    if not CMDLOG:
        with open(dev, "r+b") as f:              # blackbox (nas-tools/zt-blackbox): header + empty slots
            f.write(b"ZTBLACKBOX1" + b"\0" * 9)
            f.seek(1024 * 1024)
            f.write(b"\0" * (16 * 1024 * 1024))
            f.flush()
            os.fsync(f.fileno())
    _run(["partprobe", dev])
    _run(["udevadm", "settle"])
    part = dev + ("p1" if dev[-1].isdigit() else "1")
    _run(["mkfs.vfat", "-F", "32", "-n", "UNTRASHPK", part])
    mnt = FAKE_MNT or tempfile.mkdtemp(prefix="untrash-stick.", dir="/run")
    if not FAKE_MNT:
        _run(["mount", "-t", "vfat", "-o", "rw,flush,nosuid,nodev,noexec", part, mnt])
    try:
        tree = os.path.join(dest, "tree")
        files = [r for _s, r in _sums(os.path.join(tree, "SHA256SUMS"))] + ["SHA256SUMS"]
        progress("Copying the system")
        for rel in files:
            os.makedirs(os.path.dirname(os.path.join(mnt, rel)) or mnt, exist_ok=True)
            shutil.copyfile(os.path.join(tree, rel), os.path.join(mnt, rel))
        runs = glob.glob(os.path.join(dest, "stock", "*"))
        for r in runs:
            progress("Copying the stock backup")
            shutil.copytree(r, os.path.join(mnt, "UNTRASH", os.path.basename(r)))
        progress("Writing the key")
        kid = issue(mnt)
        progress("Checking what was written")
        if not FAKE_MNT:
            _run(["sync"])
        for sha, rel in _sums(os.path.join(mnt, "SHA256SUMS")):
            if _sha(os.path.join(mnt, rel)) != sha:
                raise StickFail("Read-back of %s does not match." % rel)
        for r in runs:
            fl = os.path.join(mnt, "UNTRASH", os.path.basename(r), "flash")
            for sha, rel in _sums(os.path.join(fl, "SHA256SUMS")) if os.path.isfile(os.path.join(fl, "SHA256SUMS")) else []:
                if _sha(os.path.join(fl, rel)) != sha:
                    raise StickFail("Read-back of the stock backup (%s) does not match." % rel)
        return kid
    finally:
        if not FAKE_MNT:
            subprocess.run(["umount", mnt], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                os.rmdir(mnt)
            except OSError:
                pass
