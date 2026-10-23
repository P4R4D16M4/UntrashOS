"""UntrashOS Desk: live system values, running activities, web terminal.

live(root)      CPU (per core, from /proc/stat deltas), memory, swap, load,
                board temperature + fan level (zt-fan, /run/untrash/fan.json),
                disk temperatures (smartctl -n standby, cached, never wakes a
                disk), network rates, uptime.  Cheap enough for a 2 s poll.
activities(root) what the NAS is doing right now: DLNA indexing and streams,
                SMB clients, RAID resync/check, backup, downloads, COPY button,
                slot update.  Polled by the Desk status bar.
terminal(handler, user)  WebSocket (RFC 6455) <-> PTY with a login shell of
                the user (admins only; checked by the caller).

root: test prefix (ZT_DESK_ROOT); "" on the NAS.
"""
import base64
import fcntl
import hashlib
import json
import os
import pty
import re
import select
import signal
import socket
import struct
import subprocess
import termios
import threading
import time

_LOCK = threading.Lock()
_CPU = {}         # last /proc/stat sample per cpu
_NET = {}         # last /proc/net/dev sample per interface
_DISKT = {"t": 0, "v": {}}


def _first(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def _cpu(root):
    out = {}
    now = {}
    for line in _first(root + "/proc/stat").splitlines():
        if not line.startswith("cpu"):
            continue
        p = line.split()
        v = [int(x) for x in p[1:9]]
        idle, total = v[3] + v[4], sum(v)
        now[p[0]] = (idle, total)
    with _LOCK:
        for k, (idle, total) in now.items():
            pi, pt = _CPU.get(k, (idle, total))
            dt = total - pt
            out[k] = round(100.0 * (1 - (idle - pi) / dt), 1) if dt > 0 else 0.0
        _CPU.clear()
        _CPU.update(now)
    cores = [out[k] for k in sorted(out) if k != "cpu"]
    return {"total": out.get("cpu", 0.0), "cores": cores}


def _net(root):
    now, t = {}, time.time()
    for line in _first(root + "/proc/net/dev").splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        if name == "lo" or name.startswith(("sit", "tunl", "ip6tnl", "ip6gre", "gre")) or not rest.split():
            continue
        f = rest.split()
        now[name] = (int(f[0]), int(f[8]), t)
    out = {}
    with _LOCK:
        for n, (rx, tx, tt) in now.items():
            prx, ptx, pt = _NET.get(n, (rx, tx, tt))
            dt = max(tt - pt, 1e-3)
            up = _first(root + "/sys/class/net/%s/operstate" % n).strip() == "up"
            out[n] = {"rx_bps": int((rx - prx) / dt) if tt > pt else 0,
                      "tx_bps": int((tx - ptx) / dt) if tt > pt else 0, "up": up}
        _NET.clear()
        _NET.update(now)
    return out


def _disk_temps(root):
    """smartctl -n standby: a spun-down disk is reported as sleeping, not woken."""
    with _LOCK:
        if time.time() - _DISKT["t"] < 300:
            return _DISKT["v"]
    v = {}
    for d in sorted(os.listdir(root + "/sys/block") if os.path.isdir(root + "/sys/block") else []):
        if not re.fullmatch(r"sd[a-z]", d):
            continue
        if _first(root + "/sys/block/%s/removable" % d).strip() == "1":
            continue
        try:
            r = subprocess.run(["smartctl", "-n", "standby", "-A", "/dev/" + d], stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode & 2 and "STANDBY" in r.stdout.upper():
            v[d] = None          # sleeping
            continue
        m = re.search(r"^\s*(?:190|194)\s+\S+.*?(\d+)(?:\s*\(.*\))?\s*$", r.stdout, re.M)
        if m:
            v[d] = int(m.group(1))
    with _LOCK:
        _DISKT.update(t=time.time(), v=v)
    return v


def live(root=""):
    mem = {}
    for line in _first(root + "/proc/meminfo").splitlines():
        k, _, val = line.partition(":")
        if val.split():
            mem[k] = int(val.split()[0]) * 1024
    try:
        fan = json.loads(_first(root + "/run/untrash/fan.json", "{}") or "{}")
    except ValueError:
        fan = {}
    if fan and time.time() - fan.get("time", 0) > 60:
        fan["stale"] = True
    return {"cpu": _cpu(root), "load": _first(root + "/proc/loadavg").split()[:3],
            "mem": {"total": mem.get("MemTotal", 0), "avail": mem.get("MemAvailable", 0),
                    "swap_total": mem.get("SwapTotal", 0), "swap_free": mem.get("SwapFree", 0)},
            "board": fan, "disks": _disk_temps(root), "net": _net(root),
            "uptime": int(float((_first(root + "/proc/uptime", "0").split() or ["0"])[0]))}


# ------------------------------------------------------------- activities

def _tcp_peers(root, port):
    """Remote addresses with an ESTABLISHED connection to local TCP port."""
    peers = set()
    for f in ("/proc/net/tcp", "/proc/net/tcp6"):
        for line in _first(root + f).splitlines()[1:]:
            p = line.split()
            if len(p) < 4 or p[3] != "01":
                continue
            lport = int(p[1].rsplit(":", 1)[1], 16)
            if lport == port:
                peers.add(p[2].rsplit(":", 1)[0])
    return len(peers)


def _procs(root):
    out = {}
    for pid in os.listdir(root + "/proc") if os.path.isdir(root + "/proc") else []:
        if pid.isdigit():
            c = _first(root + "/proc/%s/comm" % pid).strip()
            if c:
                out[c] = out.get(c, 0) + 1
    return out


def activities(root=""):
    acts = []
    procs = _procs(root)
    if procs.get("minidlnad", 0) > 1:      # the scanner is a forked child
        acts.append({"kind": "index", "text": "Medienserver indexiert"})
    n = _tcp_peers(root, 8200)
    if n:
        acts.append({"kind": "stream", "text": "%d Medien-Stream%s" % (n, "s" if n > 1 else "")})
    n = _tcp_peers(root, 445)
    if n:
        acts.append({"kind": "smb", "text": "%d Gerät%s an den Freigaben" % (n, "e" if n > 1 else "")})
    for m in re.finditer(r"^(md\d+) : .*?\n.*?\n\s*\[.*?\]\s*(resync|recovery|check|reshape)\s*=\s*([\d.]+)%",
                         _first(root + "/proc/mdstat"), re.M | re.S):
        acts.append({"kind": "raid", "text": "RAID %s: %s %s %%" % (m.group(1), m.group(2), m.group(3)),
                     "progress": float(m.group(3))})
    # oneshot jobs: "activating" while they run
    for unit, text in (("untrash-backup.service", "Sicherung läuft"), ("untrash-cloud.service", "Cloud-Abgleich läuft")):
        if not root and subprocess.run(["systemctl", "show", "-p", "ActiveState", "--value", unit], stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, text=True).stdout.strip() == "activating":
            acts.append({"kind": "job", "text": text})
    if procs.get("aria2c"):
        acts.append({"kind": "download", "text": "Downloads aktiv"})
    if procs.get("untrash-export"):
        acts.append({"kind": "encode", "text": "Export läuft"})
    elif procs.get("ffmpeg"):
        acts.append({"kind": "encode", "text": "Wiedergabe wird umgewandelt"})
    if procs.get("untrash-slot-wr") or os.path.exists(root + "/run/untrash/slot-writing"):
        acts.append({"kind": "update", "text": "System-Update wird geschrieben"})
    return {"activities": acts, "time": int(time.time())}


# ------------------------------------------------------------- terminal

WS_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _ws_send(sock, data, op=2):
    n = len(data)
    if n < 126:
        head = struct.pack("!BB", 0x80 | op, n)
    elif n < 1 << 16:
        head = struct.pack("!BBH", 0x80 | op, 126, n)
    else:
        head = struct.pack("!BBQ", 0x80 | op, 127, n)
    sock.sendall(head + data)


def _recv_exact(sock, n):
    b = b""
    while len(b) < n:
        c = sock.recv(n - len(b))
        if not c:
            raise ConnectionError("closed")
        b += c
    return b


def _ws_recv(sock):
    b1, b2 = _recv_exact(sock, 2)
    op, masked, n = b1 & 0x0F, b2 & 0x80, b2 & 0x7F
    if n == 126:
        n = struct.unpack("!H", _recv_exact(sock, 2))[0]
    elif n == 127:
        n = struct.unpack("!Q", _recv_exact(sock, 8))[0]
    if n > 1 << 20:
        raise ConnectionError("frame too large")
    key = _recv_exact(sock, 4) if masked else b"\0\0\0\0"
    data = bytes(c ^ key[i % 4] for i, c in enumerate(_recv_exact(sock, n)))
    return op, data


def terminal(handler, user, shell_cmd=None):
    """Serve one terminal session on handler's connection (blocks until closed)."""
    h = handler.headers
    key = h.get("Sec-WebSocket-Key", "")
    origin = re.sub(r"^https?://", "", h.get("Origin", ""))
    if h.get("Upgrade", "").lower() != "websocket" or not key or (origin and origin != h.get("Host", "")):
        handler.send_response(400)
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return
    accept = base64.b64encode(hashlib.sha1(key.encode() + WS_GUID).digest()).decode()
    # written by hand: BaseHTTPRequestHandler answers "HTTP/1.0", and browsers
    # refuse a WebSocket upgrade that is not "HTTP/1.1 101" (browsers reject anything else)
    handler.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         "Sec-WebSocket-Accept: %s\r\n\r\n" % accept).encode())
    handler.wfile.flush()
    handler.close_connection = True
    sock = handler.connection
    cmd, home = shell_cmd, None
    if not cmd:
        # stock users have no home (/nonexistent): give them one under
        # /var/lib/untrash/home, so that bash history and settings persist
        import pwd
        pw = pwd.getpwnam(user)
        home = pw.pw_dir if os.path.isdir(pw.pw_dir) else "/var/lib/untrash/home/" + user
        if not os.path.isdir(home):
            os.makedirs(home, mode=0o700)
            os.chown(home, pw.pw_uid, pw.pw_gid)
        cmd = ["runuser", "-u", user, "--", pw.pw_shell or "/bin/bash", "--login"]
    pid, fd = pty.fork()
    if pid == 0:
        os.environ["TERM"] = "xterm-256color"
        if home:
            os.environ.update(HOME=home, USER=user, LOGNAME=user)
            os.chdir(home)
        try:
            os.execvp(cmd[0], cmd)
        finally:
            os._exit(127)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        while True:
            r, _, _ = select.select([sock, fd], [], [], 600)
            if not r:
                break            # 10 min without any traffic
            if fd in r:
                try:
                    out = os.read(fd, 65536)
                except OSError:
                    out = b""
                if not out:
                    break
                _ws_send(sock, out)
            if sock in r:
                op, data = _ws_recv(sock)
                if op == 8:
                    break
                if op == 9:
                    _ws_send(sock, data, 10)
                    continue
                if op == 1:
                    try:
                        m = json.loads(data.decode("utf-8", "replace"))
                    except ValueError:
                        continue
                    if m.get("t") == "i":
                        os.write(fd, str(m.get("d", "")).encode())
                    elif m.get("t") == "r":
                        rows, cols = int(m.get("r", 24)), int(m.get("c", 80))
                        if 0 < rows < 1000 and 0 < cols < 1000:
                            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            _ws_send(sock, b"", 8)
        except OSError:
            pass
        try:
            os.kill(pid, signal.SIGHUP)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.waitpid(pid, 0)
        except OSError:
            pass
