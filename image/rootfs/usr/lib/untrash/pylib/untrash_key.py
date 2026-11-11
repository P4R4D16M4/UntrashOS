"""UntrashKey: a USB stick paired with this NAS as a hardware key.

With UntrashKey on, the protected areas work only while a paired stick is
plugged in: SSH (sshd runs only then, open sessions end when it is pulled),
the web terminal and the Desk actions of the chosen categories.  A stolen or
phished admin password alone then gives no shell and no lasting access.
Off by default.  docs/architecture/untrashkey.md.

The stick is the UntrashOS stick (FAT label UNTRASHPK, never mounted as a
USB volume, so the Desk cannot read it).  Pairing writes a random secret to
UNTRASH/untrashkey/<nas>.key; this NAS keeps only its SHA-256.  Pairing
needs a Desk admin and the stick pulled and plugged in again within two
minutes (physical presence: also the way back after a lost key).  A key is
present while the stick that was verified is still attached: same device,
same kernel diskseq (a new attach gets a new one), checked live.

  load() / save(cfg)       /etc/untrash/untrashkey.json (root only)
  present() / allow(cat)   is a paired key plugged in / may cat run now
  check()                  verify the plugged stick, enforce SSH on change
  pair_start(name) / pair_poll()   the replug pairing
  configure(req) / remove(id) / ssh_keys(lines)

Test hooks: ZT_KEY_ROOT (prefix of /etc /run /dev /sys), ZT_KEY_STICKDIR
(directory standing in for the mounted stick), ZT_KEY_SYSLOG (file that
records the systemctl/pkill calls instead of running them).
"""
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import tempfile
import time

R = os.environ.get("ZT_KEY_ROOT", "")
CONFIG = R + "/etc/untrash/untrashkey.json"
STATE = R + "/run/untrash/untrashkey.json"
PAIR = R + "/run/untrash/untrashkey-pair.json"
BYLABEL = R + "/dev/disk/by-label/UNTRASHPK"
SYSBLOCK = R + "/sys/class/block"
SERVICE_DIR = R + "/run/untrash/servicekey"
STICKDIR = os.environ.get("ZT_KEY_STICKDIR")
SYSLOG = os.environ.get("ZT_KEY_SYSLOG")

# what can be protected; the Desk actions of each category: untrash-desk KEY_GUARD
CATEGORIES = ("ssh", "terminal", "access", "exposure", "system", "data")
DEFAULT_PROTECT = ["ssh", "terminal", "access", "exposure", "system"]
PAIR_S = 120
KEY_RE = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521)|sk-ssh-ed25519@openssh.com) [A-Za-z0-9+/=]+( [^ ]*)?$")


class KeyFail(Exception):
    pass


def _json(path, default):
    try:
        with open(path) as f:
            v = json.load(f)
        return v if isinstance(v, dict) else default
    except (OSError, ValueError):
        return default


def _write(path, obj, mode=0o600):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".untrashkey.")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def load():
    c = _json(CONFIG, {})
    keys = [k for k in c.get("keys", []) if isinstance(k, dict) and re.fullmatch(r"[0-9a-f]{64}", str(k.get("hash", "")))]
    return {"enabled": bool(c.get("enabled")) and bool(keys), "nas": str(c.get("nas") or ""),
            "protect": [x for x in c.get("protect", DEFAULT_PROTECT) if x in CATEGORIES], "keys": keys}


def save(cfg):
    _write(CONFIG, cfg)


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def stick():
    """The plugged UntrashOS stick: {"dev": "/dev/sdb1", "seq": "17"} or None.
    Only a USB device counts (no loop/iSCSI disk with the same label)."""
    try:
        dev = os.path.realpath(BYLABEL) if os.path.lexists(BYLABEL) else ""
    except OSError:
        dev = ""
    if not dev or not os.path.exists(dev):
        return None
    sysp = os.path.realpath(os.path.join(SYSBLOCK, os.path.basename(dev)))
    if "/usb" not in sysp:
        return None
    seq = _read(os.path.join(sysp, "diskseq")) or _read(os.path.join(os.path.dirname(sysp), "diskseq"))
    if not seq.isdigit():
        return None
    return {"dev": dev[len(R):] if R and dev.startswith(R) else dev, "seq": seq}


def _max_seq():
    best = 0
    try:
        names = os.listdir(SYSBLOCK)
    except OSError:
        names = []
    for n in names:                     # a partition: the diskseq of its disk
        s = _read(os.path.join(SYSBLOCK, n, "diskseq")) or _read(os.path.join(SYSBLOCK, n, "..", "diskseq"))
        if s.isdigit():
            best = max(best, int(s))
    return best


def _on_stick(st, rw, fn):
    """fn(directory of the mounted stick); mounted only for the call."""
    if STICKDIR:
        return fn(STICKDIR)
    for line in open("/proc/mounts"):
        f = line.split()
        if f[0] == st["dev"] and (not rw or "rw" in f[3].split(",")):
            return fn(f[1].replace("\\040", " "))
    tmp = tempfile.mkdtemp(prefix="untrashkey.", dir="/run")
    try:
        r = subprocess.run(["mount", "-t", "vfat", "-o", ("rw,flush" if rw else "ro") + ",nosuid,nodev,noexec",
                            st["dev"], tmp], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, universal_newlines=True)
        if r.returncode:
            raise KeyFail("The stick cannot be mounted: %s" % r.stderr.strip()[-200:])
        try:
            return fn(tmp)
        finally:
            subprocess.run(["umount", tmp], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    finally:
        try:
            os.rmdir(tmp)
        except OSError:
            pass


def _keyfile(mnt, nas):
    return os.path.join(mnt, "UNTRASH", "untrashkey", nas + ".key")


def _secret_of(text, nas):
    f = text.split()
    if len(f) == 3 and f[0] == "UNTRASHKEY1" and f[1] == nas and re.fullmatch(r"[0-9a-f]{64}", f[2]):
        return f[2]
    return None


def _match(cfg, secret):
    if not secret:
        return None
    h = hashlib.sha256(secret.encode()).hexdigest()
    for k in cfg["keys"]:
        if hmac.compare_digest(h, k["hash"]):
            return k
    return None


def _sys(cmd):
    if SYSLOG:
        with open(SYSLOG, "a") as f:
            f.write(" ".join(cmd) + "\n")
        return 0
    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode


def _enforce(cfg, present, ssh_keys):
    """SSH follows the key: on while it is plugged in (with the stick's
    UNTRASH/ssh/authorized_keys for root), off and every session ended
    when it is pulled."""
    if not cfg["enabled"] or "ssh" not in cfg["protect"]:
        return
    keys = os.path.join(SERVICE_DIR, "authorized_keys")
    if present:
        if ssh_keys:
            os.makedirs(SERVICE_DIR, mode=0o700, exist_ok=True)
            with open(keys + ".tmp", "w") as f:
                f.write("".join(x + "\n" for x in ssh_keys))
            os.chmod(keys + ".tmp", 0o600)
            os.replace(keys + ".tmp", keys)
        if ssh_keys or _sys(["systemctl", "-q", "is-enabled", "ssh.service"]) == 0:
            _sys(["systemctl", "start", "--no-block", "ssh.service"])
    else:
        try:
            os.remove(keys)
        except OSError:
            pass
        _sys(["systemctl", "stop", "ssh.service"])
        _sys(["pkill", "-x", "sshd"])          # the sessions: sshd's KillMode=process leaves them


def check(cfg=None):
    """Verify the plugged stick (reads its key file) and store the result;
    enforce SSH when the presence changed.  Returns the state."""
    cfg = cfg or load()
    prev = _json(STATE, {})
    st = stick()
    state = {"present": False, "time": int(time.time())}
    ssh_keys = []
    if st and cfg["nas"] and cfg["keys"]:
        def rd(mnt):
            try:
                sec = _secret_of(open(_keyfile(mnt, cfg["nas"])).read(), cfg["nas"])
            except OSError:
                sec = None
            try:
                lines = [x.strip() for x in open(os.path.join(mnt, "UNTRASH", "ssh", "authorized_keys"))]
            except OSError:
                lines = []
            return sec, [x for x in lines if KEY_RE.match(x)]
        try:
            sec, ssh_keys = _on_stick(st, False, rd)
        except (KeyFail, OSError):
            sec = None
        k = _match(cfg, sec)
        if k:
            state.update(present=True, dev=st["dev"], seq=st["seq"], key=k["id"], name=k.get("name", ""),
                         user=k.get("user", ""))
    _write(STATE, state, 0o644)
    if bool(prev.get("present")) != state["present"] or (state["present"] and prev.get("seq") != state.get("seq")):
        if prev.get("reset"):
            pass                        # configure()/ssh_keys() re-enforce: no new event
        elif state["present"]:
            _log("key %s (%s, user %s) plugged in" % (state["key"], state["name"], state["user"] or "any admin"))
        elif prev.get("present"):
            _log("key %s (%s) pulled" % (prev.get("key"), prev.get("name", "")))
        _enforce(cfg, state["present"], ssh_keys)
    return state


def _log(msg):
    """journal (untrash-key.service / untrash-desk.service): who opened what"""
    import sys
    print("untrashkey: " + msg, file=sys.stderr, flush=True)


def current(cfg=None):
    """The key plugged in right now (state dict with key, name, user) or None.
    Fast: the verified state is only trusted while the same attach of the
    same stick is still there."""
    cfg = cfg or load()
    s = _json(STATE, {})
    st = stick()
    if not st:
        if s.get("present"):
            check(cfg)                  # pulled: end SSH now, not at the next watcher tick
        return None
    if not (s.get("present") and s.get("dev") == st["dev"] and s.get("seq") == st["seq"]):
        s = check(cfg)
    return s if s.get("present") and any(k["id"] == s.get("key") for k in cfg["keys"]) else None


def present(cfg=None, user=None):
    """A paired key is plugged in (USER given: one of USER's keys, or a key
    for any admin)."""
    k = current(cfg)
    return bool(k) and (user is None or k.get("user") in ("", None, user))


def allow(cat, cfg=None, user=None):
    """May CAT run now: UntrashKey off, CAT not protected, or the key of
    USER (None = the system itself, e.g. sshd) plugged in."""
    cfg = cfg or load()
    if not cfg["enabled"] or cat not in cfg["protect"]:
        return True
    return present(cfg, user)


def status():
    cfg = load()
    pair = _json(PAIR, {})
    return {"enabled": cfg["enabled"], "protect": cfg["protect"], "categories": list(CATEGORIES),
            "keys": [{"id": k["id"], "name": k.get("name", ""), "user": k.get("user", ""), "added": k.get("added", "")}
                     for k in cfg["keys"]],
            "present": bool(current(cfg)) if cfg["keys"] else False, "current": (current(cfg) or {}).get("key"),
            "stick": bool(stick()),
            "pairing": {k: pair[k] for k in ("state", "mode", "name", "user", "expires", "error", "key", "step", "dev")
                        if k in pair} if pair else None}


# ------------------------------------------------------------------ pairing

def _name(name):
    name = re.sub(r"[^\w .@'-]", "", str(name or ""), flags=re.U).strip()[:40]
    if not name:
        raise KeyFail("Give the key a name.")
    return name


def pair_start(name, user="", mode="pair", since=None):
    """Wait for a stick attached from now on.  mode "pair": an UntrashOS
    stick pulled and plugged in again gets a key; mode "create": the Desk
    writes a whole new stick onto a USB disk plugged in (untrash_stick)."""
    _write(PAIR, {"state": "waiting", "mode": mode, "name": _name(name), "user": str(user or ""),
                  "since_seq": _max_seq() if since is None else since, "expires": int(time.time()) + PAIR_S})
    return status()


def pair_cancel():
    p = _json(PAIR, {})
    if p.get("state") == "writing":
        raise KeyFail("The stick is being written; wait until it is done.")
    try:
        os.remove(PAIR)
    except OSError:
        pass
    return status()


def pair_update(**kw):
    p = _json(PAIR, {})
    p.update(kw)
    _write(PAIR, p, 0o644)


def issue(mnt, name, user=""):
    """Write a new key file onto the stick mounted at MNT and register it
    for USER ("" = any admin); a key this stick had before is replaced.
    Returns the key id."""
    cfg = load()
    raw = _json(CONFIG, {})
    nas = cfg["nas"] or secrets.token_hex(8)
    secret = secrets.token_hex(32)
    f = _keyfile(mnt, nas)
    old = None
    try:
        old = _secret_of(open(f).read(), nas)
    except OSError:
        pass
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w") as o:
        o.write("UNTRASHKEY1 %s %s\n" % (nas, secret))
        o.flush()
        os.fsync(o.fileno())
    if _secret_of(open(f).read(), nas) != secret:
        raise KeyFail("The key could not be read back from the stick.")
    replaced = _match(cfg, old)           # the same stick paired again: its old secret goes
    keys = [k for k in cfg["keys"] if not replaced or k["id"] != replaced["id"]]
    kid = secrets.token_hex(4)
    keys.append({"id": kid, "name": _name(name), "user": str(user or ""),
                 "hash": hashlib.sha256(secret.encode()).hexdigest(),
                 "added": datetime.datetime.now().isoformat(timespec="seconds")})
    raw.update(nas=nas, keys=keys, protect=cfg["protect"], enabled=cfg["enabled"])
    save(raw)
    _log("key %s (%s) issued for user %s" % (kid, _name(name), user or "any admin"))
    return kid


def pair_poll(start_create=None):
    """mode "pair": pairs the UntrashOS stick that was attached after
    pair_start (pulled and plugged in again: someone is at the NAS).
    mode "create": hands the first USB disk attached after pair_start to
    start_create(disk) (the Desk writes the stick in a thread)."""
    p = _json(PAIR, {})
    if p.get("state") != "waiting":
        return status()
    if time.time() > p.get("expires", 0):
        p.update(state="expired")
        _write(PAIR, p, 0o644)
        return status()
    if p.get("mode") == "create":
        import untrash_stick
        new = untrash_stick.usb_disks(int(p.get("since_seq", 0)))
        if new and start_create:
            p.update(state="writing", step="Starting", dev=new[0]["dev"])
            _write(PAIR, p, 0o644)
            start_create(new[0], p)
        return status()
    st = stick()
    if not st or int(st["seq"]) <= int(p.get("since_seq", 0)):
        return status()
    try:
        kid = _on_stick(st, True, lambda mnt: issue(mnt, p["name"], p.get("user", "")))
    except (KeyFail, OSError) as e:
        p.update(state="failed", error=str(e))
        _write(PAIR, p, 0o644)
        return status()
    p.update(state="done", key=kid)
    _write(PAIR, p, 0o644)
    check()
    return status()


# ------------------------------------------------------------ configuration

def _need_key(cfg, user=None):
    if cfg["enabled"] and not present(cfg, user):
        raise KeyFail("Plug in your UntrashKey.")


def configure(req, user=None):
    """{"enabled": bool, "protect": [...]}.  Switching on needs a paired key
    plugged in now (no lock-out); any change while on needs it too."""
    cfg = load()
    raw = _json(CONFIG, {})
    _need_key(cfg, user)
    if "protect" in req:
        prot = req["protect"]
        if not isinstance(prot, list) or any(x not in CATEGORIES for x in prot):
            raise KeyFail("Unknown area.")
        raw["protect"] = [x for x in CATEGORIES if x in prot]
    if "enabled" in req:
        on = bool(req["enabled"])
        if on and not cfg["keys"]:
            raise KeyFail("Pair a stick first.")
        if on and not present(cfg, user):
            raise KeyFail("Plug in a paired stick to switch UntrashKey on.")
        raw["enabled"] = on
    raw.setdefault("protect", cfg["protect"])
    raw["keys"], raw["nas"] = cfg["keys"], cfg["nas"]
    was = cfg["enabled"] and "ssh" in cfg["protect"]
    save(raw)
    now = load()
    _write(STATE, {"present": False, "reset": True, "time": int(time.time())}, 0o644)
    check(now)                             # enforce from a clean state
    if was and not (now["enabled"] and "ssh" in now["protect"]):
        if _sys(["systemctl", "-q", "is-enabled", "ssh.service"]) == 0:
            _sys(["systemctl", "start", "--no-block", "ssh.service"])
    return status()


def remove(kid, user=None):
    cfg = load()
    _need_key(cfg, user)
    keys = [k for k in cfg["keys"] if k["id"] != kid]
    if len(keys) == len(cfg["keys"]):
        raise KeyFail("Unknown key.")
    if cfg["enabled"] and not keys:
        raise KeyFail("Switch UntrashKey off before removing the last key.")
    raw = _json(CONFIG, {})
    raw["keys"] = keys
    save(raw)
    check()
    return status()


def ssh_keys(lines=None, user=None):
    """The SSH public keys on the plugged, paired stick (read, or replace
    with LINES): root logs in with them while the stick is in."""
    cfg = load()
    if not present(cfg, user):
        raise KeyFail("Plug in your UntrashKey.")
    st = stick()
    path = lambda mnt: os.path.join(mnt, "UNTRASH", "ssh", "authorized_keys")  # noqa: E731
    if lines is None:
        def rd(mnt):
            try:
                return [x.strip() for x in open(path(mnt)) if KEY_RE.match(x.strip())]
            except OSError:
                return []
        return {"keys": _on_stick(st, False, rd)}
    clean = [x.strip() for x in lines if x.strip()]
    bad = [x for x in clean if not KEY_RE.match(x)]
    if bad:
        raise KeyFail("Not a public SSH key: %s" % bad[0][:40])

    def wr(mnt):
        os.makedirs(os.path.dirname(path(mnt)), exist_ok=True)
        with open(path(mnt), "w") as f:
            f.write("".join(x + "\n" for x in clean))
            f.flush()
            os.fsync(f.fileno())
    _on_stick(st, True, wr)
    _write(STATE, {"present": False, "reset": True, "time": int(time.time())}, 0o644)
    check(cfg)                             # the new keys apply now
    return {"keys": clean}
