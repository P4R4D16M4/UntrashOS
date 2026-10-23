"""UntrashOS slot files (*.utslot): read and verify, as the loader does.

A slot file is the head of a slot (erofs + verity tree, kernel, DTB, initrd)
plus an 8 KiB trailer: a text manifest in the first 4 KiB, up to 8 Ed25519
signatures of 64 bytes in the second (image/mkslot-erofs.sh).  The manifest
pins kernel, DTB and initrd by SHA-256 and the root file system by its
dm-verity root hash, so a valid signature over the manifest plus matching
payload hashes is what the loader accepts.

Used by the Desk (uploaded images) and untrash-update (downloaded images).
"""
import glob
import hashlib
import os
import re
import subprocess
import tempfile

KEYS = os.environ.get("ZT_SLOT_KEYS", "/usr/lib/untrash/keys")
ZT_SIG = os.environ.get("ZT_SIG", "/usr/lib/untrash/zt-sig")
MAX_SIZE = 1536 * 1024 * 1024


class SlotError(Exception):
    pass


def trailer(path):
    """(manifest dict, manifest text, [signatures]) of a slot file."""
    size = os.path.getsize(path)
    if size <= 8192 or size > MAX_SIZE or (size - 8192) % 4096:
        raise SlotError("Not a system image file.")
    with open(path, "rb") as f:
        f.seek(size - 8192)
        text = f.read(4096).rstrip(b"\0").decode("utf-8", "replace")
        block = f.read(4096)
    sigs = [block[i:i + 64] for i in range(0, 512, 64) if block[i:i + 64].strip(b"\0")]
    m = dict(l.split("=", 1) for l in text.splitlines() if "=" in l)
    if m.get("format") != "untrash-slot-2":
        raise SlotError("Not an UntrashOS system image (format).")
    return m, text, sigs


def signed(text, sigs, keys=None):
    """True when one of the signatures is valid for one of the trusted keys."""
    keys = sorted(glob.glob(os.path.join(keys or KEYS, "*.pub")))
    with tempfile.TemporaryDirectory() as d:
        man = os.path.join(d, "manifest")
        with open(man, "w") as f:
            f.write(text)
        for i, s in enumerate(sigs):
            sig = os.path.join(d, "sig%d" % i)
            with open(sig, "wb") as f:
                f.write(s)
            for k in keys:
                if subprocess.run([ZT_SIG, "verify", k, man, sig], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0:
                    return True
    return False


def verify(path, check_signature=True):
    """Manifest of a valid slot file; SlotError otherwise."""
    m, text, sigs = trailer(path)
    if check_signature and not signed(text, sigs):
        raise SlotError("Invalid signature: image not from UntrashOS.")
    with open(path, "rb") as f:
        for p in ("kernel", "dtb", "initrd"):
            if m.get(p + "_off"):
                f.seek(int(m[p + "_off"]))
                h = hashlib.sha256()
                left = int(m[p + "_len"])
                while left:
                    b = f.read(min(left, 1 << 20))
                    if not b:
                        raise SlotError("Image damaged (%s)." % p)
                    h.update(b)
                    left -= len(b)
                if h.hexdigest() != m.get(p + "_sha256"):
                    raise SlotError("Image damaged (%s)." % p)
    return m


def version_key(v):
    """Sortable key of an UntrashOS version: 1.0 < 1.0.1 < 1.1-rc1 < 1.1.
    Anything that is not a version (dev builds) sorts first."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+)*)(?:[-~]?(rc|beta|alpha|pre)\.?(\d*))?", (v or "").strip(), re.I)
    if not m:
        return (0,), 0, 0
    nums = tuple(int(x) for x in m.group(1).split("."))
    nums += (0,) * (4 - len(nums))
    pre = {"alpha": 1, "beta": 2, "pre": 3, "rc": 3}.get((m.group(2) or "").lower(), 9)
    return nums, pre, int(m.group(3) or 0)


def newer(a, b):
    """True when version a is newer than version b."""
    return version_key(a) > version_key(b)
