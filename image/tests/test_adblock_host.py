#!/usr/bin/env python3
"""PC test of usr/lib/untrash/untrash-adblock with a real dnsmasq on 127.0.0.1:15353.

- list formats (hosts, plain domains, adblock ||x^), comments, junk, localhost
- update: a broken list does not stop the others; allow list wins
- render + dnsmasq: list names answer 0.0.0.0, user blocks cover subdomains,
  AAAA of a listed name is NODATA, the query log feeds the statistics
- rotation keeps both log files readable for the statistics
"""
import importlib.machinery
import importlib.util
import os
import random
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-adblock")
FAIL = 0


def check(name, ok):
    global FAIL
    print(("ok   " if ok else "FAIL ") + name, flush=True)
    FAIL += 0 if ok else 1


def load_tool(w):
    os.environ.update(ZT_ADBLOCK_STORE=w + "/adblock.json", ZT_ADBLOCK_DATA=w + "/data", ZT_ADBLOCK_RUN=w + "/run",
                      ZT_ADBLOCK_UPSTREAM=w + "/resolv.conf", ZT_ADBLOCK_PORT="15353", ZT_ADBLOCK_LISTEN="127.0.0.1",
                      ZT_ADBLOCK_LOG_MAX="2000")
    ld = importlib.machinery.SourceFileLoader("adblock", TOOL)
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader("adblock", ld))
    ld.exec_module(m)
    return m


def dns(name, qtype=1):
    """(rcode, [answers as text]) from 127.0.0.1:15353."""
    tid = random.randint(0, 65535)
    q = struct.pack("!HHHHHH", tid, 0x0100, 1, 0, 0, 0) + b"".join(
        bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0" + struct.pack("!HH", qtype, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    s.sendto(q, ("127.0.0.1", 15353))
    r = s.recv(1500)
    s.close()
    rcode, an = r[3] & 15, struct.unpack("!H", r[6:8])[0]
    i, out = len(q), []
    for _ in range(an):
        i += 2 if r[i] & 0xC0 == 0xC0 else r.index(b"\0", i) + 1 - i
        t, _c, _ttl, ln = struct.unpack("!HHIH", r[i:i + 10])
        data = r[i + 10:i + 10 + ln]
        out.append(socket.inet_ntoa(data) if t == 1 else socket.inet_ntop(socket.AF_INET6, data) if t == 28 else "")
        i += 10 + ln
    return rcode, out


def main():
    if not shutil.which("dnsmasq") and not os.path.exists("/usr/sbin/dnsmasq"):
        print("SKIP: no dnsmasq on this PC")
        return
    with tempfile.TemporaryDirectory() as w:
        os.chmod(w, 0o755)          # as root dnsmasq drops to its user (like /run/untrash on the NAS)
        A = load_tool(w)
        text = "# c\n0.0.0.0 ads.example.com\n127.0.0.1 track.example.net # x\n0.0.0.0 localhost\nplain.example.org\n" \
               "||abp.example.com^\n||abp.example.com/path\n! comment\nnot a domain at all\n:: v6.example.com\n"
        check("list formats parsed, junk and localhost ignored",
              A.parse_list(text) == {"ads.example.com", "track.example.net", "plain.example.org", "abp.example.com",
                                     "v6.example.com"})
        open(w + "/resolv.conf", "w").write("nameserver 127.0.0.1\n")
        s = A.load()
        s["lists"] = [{"name": "one", "url": "http://one", "on": True}, {"name": "dead", "url": "http://dead", "on": True},
                      {"name": "off", "url": "http://off", "on": False}]
        s["allow"] = ["plain.example.org"]
        s["block"] = ["*.blocked.test", "exact.test"]

        def fetcher(url):
            if url == "http://dead":
                raise OSError("timeout")
            return text
        r = A.update(s, fetcher)
        hosts = open(A.HOSTS).read()
        check("update: dead list reported, others used", r["count"] == 4 and len(r["errors"]) == 1 and "dead" in r["errors"][0])
        check("allow list removes a listed name", "plain.example.org" not in hosts and "0.0.0.0 ads.example.com" in hosts)
        conf = open(A.render()).read()
        check("conf: user block with subdomains, allow forwards", "address=/blocked.test/0.0.0.0" in conf and
              "server=/plain.example.org/#" in conf and "log-queries=extra" in conf)
        p = subprocess.Popen(["dnsmasq", "--keep-in-foreground", "--conf-file=" + A.CONF], stderr=subprocess.PIPE, text=True)
        try:
            for _ in range(50):
                try:
                    dns("ads.example.com")
                    break
                except OSError:
                    time.sleep(0.1)
            check("listed name -> 0.0.0.0", dns("ads.example.com") == (0, ["0.0.0.0"]))
            check("AAAA of a listed name -> ::", dns("ads.example.com", 28) == (0, ["::"]))
            check("user wildcard block covers subdomains", dns("x.y.blocked.test")[1] == ["0.0.0.0"])
            check("user exact block", dns("exact.test")[1] == ["0.0.0.0"])
            for _ in range(4):      # more than ads.example.com (startup probe + A + AAAA)
                dns("track.example.net")
            time.sleep(1.5)         # log-async
            st = A.stats(24)
            check("stats: queries and blocked counted", st["queries"] >= 8 and st["blocked"] >= 8 and st["percent"] > 90)
            check("stats: top blocked + client", st["top_blocked"][0] == {"name": "track.example.net", "n": 4} and
                  st["top_clients"][0]["name"] == "127.0.0.1")
            lg = A.last(5)
            check("log: newest first, status blocked", lg[0]["name"] == "track.example.net" and lg[0]["status"] == "blocked")
            dns("ads.example.com")
            time.sleep(1.5)
            rot = A.rotate()
            dns("exact.test")
            time.sleep(1.5)
            st2 = A.stats(24)
            check("rotation: dnsmasq reopens, both files counted", rot and os.path.exists(A.LOG + ".1") and
                  st2["queries"] == st["queries"] + 2)
        finally:
            p.terminate()
            p.wait(5)
    print("FAILURES %d" % FAIL)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
