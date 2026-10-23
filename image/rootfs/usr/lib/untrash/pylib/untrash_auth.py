"""Password checks for UntrashOS logins (Untrash Desk, FTP via PAM).

Stock users have only an SMB password (LM:NT hash in the stock database,
imported into Samba's tdbsam); only admin also has a Unix (md5-crypt)
password.  check() accepts the SMB password (NT hash = MD4 of the UTF-16LE
password) and, for users that have one, the Unix password (crypt(3) from
libcrypt via ctypes; Python 3.13 has no crypt module)."""
import ctypes
import ctypes.util
import hmac
import os
import struct
import subprocess

PDBEDIT = os.environ.get("ZT_PDBEDIT", "pdbedit")
SHADOW = os.environ.get("ZT_SHADOW", "/etc/shadow")


def md4(data):
    """RFC 1320 (hashlib has no MD4 with OpenSSL 3)."""
    def rol(x, n):
        x &= 0xffffffff
        return ((x << n) | (x >> (32 - n))) & 0xffffffff
    msg = bytearray(data) + b"\x80"
    msg += b"\x00" * ((56 - len(msg) % 64) % 64) + struct.pack("<Q", 8 * len(data))
    h = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476]
    for off in range(0, len(msg), 64):
        X = struct.unpack("<16I", msg[off:off + 64])
        a, b, c, d = h
        for i in range(16):
            k, r = i, (3, 7, 11, 19)[i % 4]
            a, b, c, d = d, rol(a + ((b & c) | (~b & d)) + X[k], r), b, c
        for i in range(16):
            k, r = (i % 4) * 4 + i // 4, (3, 5, 9, 13)[i % 4]
            a, b, c, d = d, rol(a + ((b & c) | (b & d) | (c & d)) + X[k] + 0x5a827999, r), b, c
        for i in range(16):
            k, r = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)[i], (3, 9, 11, 15)[i % 4]
            a, b, c, d = d, rol(a + (b ^ c ^ d) + X[k] + 0x6ed9eba1, r), b, c
        h = [(x + y) & 0xffffffff for x, y in zip(h, (a, b, c, d))]
    return struct.pack("<4I", *h)


def nt_hash(password):
    return md4(password.encode("utf-16-le")).hex().upper()


def smb_nt_hash(user):
    """NT hash of USER from tdbsam (pdbedit smbpasswd format), or None."""
    try:
        r = subprocess.run([PDBEDIT, "-L", "-w", "-u", user], stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in r.stdout.splitlines():
        f = line.split(":")
        if len(f) >= 4 and f[0] == user and len(f[3]) == 32 and f[3] != "X" * 32:
            return f[3].upper()
    return None


_libcrypt = None


def unix_crypt(password, setting):
    global _libcrypt
    if _libcrypt is None:
        _libcrypt = ctypes.CDLL(ctypes.util.find_library("crypt") or "libcrypt.so.1")
        _libcrypt.crypt.restype = ctypes.c_char_p
        _libcrypt.crypt.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    r = _libcrypt.crypt(password.encode(), setting.encode())
    return r.decode() if r else None


def shadow_hash(user):
    try:
        with open(SHADOW) as f:
            for line in f:
                p = line.split(":")
                if p[0] == user and len(p) > 1 and p[1].startswith("$"):
                    return p[1]
    except OSError:
        pass
    return None


def check(user, password):
    if not user or not password or ":" in user or "\n" in user:
        return False
    nt = smb_nt_hash(user)
    if nt and hmac.compare_digest(nt, nt_hash(password)):
        return True
    sh = shadow_hash(user)
    if sh:
        c = unix_crypt(password, sh)
        if c and hmac.compare_digest(c, sh):
            return True
    return False
