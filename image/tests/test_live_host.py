#!/usr/bin/env python3
"""PC test of usr/lib/untrash/pylib/untrash_live.py (Desk status + terminal).

- terminal(): real RFC 6455 handshake on a local HTTP server, /bin/sh in a
  PTY: input is executed, output comes back, resize reaches the PTY, a
  foreign Origin is refused
- live() and activities() against a fake /proc, /sys and /run root
"""
import base64
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "pylib"))
import untrash_live as L  # noqa: E402

FAIL = 0


def check(name, ok):
    global FAIL
    print(("ok   " if ok else "FAIL ") + name)
    FAIL += 0 if ok else 1


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        L.terminal(self, "test", shell_cmd=["/bin/sh", "-i"])

    def log_message(self, *a):
        pass


def ws_connect(port, origin=None):
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    key = base64.b64encode(os.urandom(16)).decode()
    hdr = ("GET /api/term HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
           "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n" % (port, key))
    if origin:
        hdr += "Origin: %s\r\n" % origin
    s.sendall((hdr + "\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        c = s.recv(4096)
        if not c:
            break
        resp += c
    return s, resp.split(b"\r\n\r\n", 1)


def ws_send_text(s, obj):
    data = json.dumps(obj).encode()
    mask = os.urandom(4)
    n = len(data)
    head = struct.pack("!BB", 0x81, 0x80 | n) if n < 126 else struct.pack("!BBH", 0x81, 0x80 | 126, n)
    s.sendall(head + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))


def ws_read_until(s, needle, rest=b"", timeout=5):
    buf, out = rest, b""
    end = time.time() + timeout
    s.settimeout(0.5)
    while time.time() < end and needle not in out:
        try:
            c = s.recv(65536)
            if not c:
                break
            buf += c
        except socket.timeout:
            pass
        while len(buf) >= 2:
            n = buf[1] & 0x7F
            off = 2
            if n == 126:
                if len(buf) < 4:
                    break
                n = struct.unpack("!H", buf[2:4])[0]
                off = 4
            if len(buf) < off + n:
                break
            out += buf[off:off + n]
            buf = buf[off + n:]
    return out


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    s, (head, rest) = ws_connect(port, origin="http://127.0.0.1:%d" % port)
    # browsers accept only "HTTP/1.1 101" (Firefox closes at once on HTTP/1.0)
    check("terminal: HTTP/1.1 101 Switching Protocols", head.startswith(b"HTTP/1.1 101 "))
    ws_send_text(s, {"t": "r", "c": 101, "r": 33})
    ws_send_text(s, {"t": "i", "d": "stty size; echo UT$((40+2))\n"})
    out = ws_read_until(s, b"UT42", rest)
    check("terminal: input runs in the shell, output returns", b"UT42" in out)
    check("terminal: resize reaches the PTY", b"33 101" in out)
    ws_send_text(s, {"t": "i", "d": "exit\n"})
    s.close()

    s, (head, _r) = ws_connect(port, origin="http://evil.example")
    check("terminal: foreign Origin refused", b" 400" in head.split(b"\r\n")[0])
    s.close()

    with tempfile.TemporaryDirectory() as root:
        os.makedirs(root + "/proc/42")
        os.makedirs(root + "/proc/43")
        os.makedirs(root + "/run/untrash")
        os.makedirs(root + "/sys/block")
        os.makedirs(root + "/sys/class/net/eth0")
        open(root + "/sys/class/net/eth0/operstate", "w").write("up\n")
        open(root + "/proc/42/comm", "w").write("minidlnad\n")
        open(root + "/proc/43/comm", "w").write("minidlnad\n")
        st = lambda u, i: "cpu  %d 0 0 %d 0 0 0 0 0 0\ncpu0 %d 0 0 %d 0 0 0 0 0 0\n" % (u, i, u, i)  # noqa: E731
        open(root + "/proc/stat", "w").write(st(100, 100))
        open(root + "/proc/meminfo", "w").write("MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
        open(root + "/proc/loadavg", "w").write("0.5 0.4 0.3 1/100 42\n")
        open(root + "/proc/uptime", "w").write("7300.0 1\n")
        dev = "Inter-|\n face |\n  eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n"
        open(root + "/proc/net/dev" if os.path.isdir(root + "/proc/net") else root + "/proc/netdev", "w").write(dev)
        os.makedirs(root + "/proc/net", exist_ok=True)
        open(root + "/proc/net/dev", "w").write(dev)
        open(root + "/run/untrash/fan.json", "w").write(json.dumps({"temp_c": 41, "rpm_reg": 9, "level": 2, "time": time.time()}))
        open(root + "/proc/mdstat", "w").write("md120 : active raid1 sda3[0] sdb3[1]\n      100 blocks [2/2] [UU]\n"
                                               "      [==>...]  resync = 12.5% (1/8) finish=1min\n\nunused devices: <none>\n")
        tcp = "  sl  local_address rem_address   st\n   0: 0100007F:2008 0200A8C0:D431 01 0\n   1: 0100007F:01BD 0300A8C0:D432 01 0\n"
        open(root + "/proc/net/tcp", "w").write(tcp)
        L.live(root)
        open(root + "/proc/stat", "w").write(st(150, 150))
        open(root + "/proc/net/dev", "w").write(dev.replace(" 1000 ", " 3000 "))
        v = L.live(root)
        check("live: CPU from /proc/stat deltas (50 %)", v["cpu"]["total"] == 50.0 and v["cpu"]["cores"] == [50.0])
        check("live: memory and uptime", v["mem"]["total"] == 1024000 and v["uptime"] == 7300)
        check("live: board temperature from zt-fan", v["board"].get("temp_c") == 41 and not v["board"].get("stale"))
        check("live: network rate", v["net"]["eth0"]["rx_bps"] > 0 and v["net"]["eth0"]["up"])
        a = [x["kind"] for x in L.activities(root)["activities"]]
        check("activity: DLNA indexing (scanner child)", "index" in a)
        check("activity: one DLNA stream, one SMB client", "stream" in a and "smb" in a)
        check("activity: RAID resync with progress", "raid" in a)
    print("FAILURES %d" % FAIL)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
