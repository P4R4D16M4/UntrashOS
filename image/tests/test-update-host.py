#!/usr/bin/env python3
"""PC test of untrash-update (release check, download, verification).

  python3 image/tests/test-update-host.py

A local HTTP server plays the GitHub releases API and serves the assets
(with Range for resumed downloads).  The slot files are small but real:
kernel/DTB/initrd regions with SHA-256 in the manifest, signed with a key
made for the test (slot/zt-sig.c, built for the PC).
"""
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
OS = os.path.abspath(os.path.join(HERE, "..", ".."))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-update")
sys.path.insert(0, os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "pylib"))
import untrash_slot as SL  # noqa: E402

fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += not ok


W = tempfile.mkdtemp(prefix="ut-update-")
SIG = os.path.join(W, "zt-sig")
subprocess.run(["gcc", "-O2", "-I" + os.path.join(OS, "third_party/tweetnacl"), "-o", SIG,
                os.path.join(OS, "slot/zt-sig.c"), os.path.join(OS, "third_party/tweetnacl/tweetnacl.c")], check=True)
os.makedirs(W + "/keys")
subprocess.run([SIG, "keygen", W + "/good.sec", W + "/keys/good.pub"], check=True, stdout=subprocess.DEVNULL)
subprocess.run([SIG, "keygen", W + "/bad.sec", W + "/bad.pub"], check=True, stdout=subprocess.DEVNULL)
SL.KEYS, SL.ZT_SIG = W + "/keys", SIG      # the module in this process, like the env for the tool


def slot(version, key="good", damage=False, manifest_version=None):
    """A slot file: head (kernel, dtb, initrd regions) + 8 KiB trailer."""
    parts = {"kernel": os.urandom(12288), "dtb": os.urandom(4096), "initrd": os.urandom(8192)}
    head, man, off = b"", ["format=untrash-slot-2", "version=%s" % (manifest_version or version)], 0
    for p, data in parts.items():
        man += ["%s_off=%d" % (p, off), "%s_len=%d" % (p, len(data)), "%s_sha256=%s" % (p, hashlib.sha256(data).hexdigest())]
        head += data
        off += len(data)
    if damage:
        head = head[:100] + bytes([head[100] ^ 1]) + head[101:]
    text = "\n".join(man) + "\n"
    with open(W + "/m", "w") as f:
        f.write(text)
    subprocess.run([SIG, "sign", "%s/%s.sec" % (W, key), W + "/m", W + "/s"], check=True)
    sig = open(W + "/s", "rb").read()
    return head + text.encode().ljust(4096, b"\0") + sig.ljust(4096, b"\0")


ASSETS, RELEASES, SEEN = {}, [], {"range": [], "cut": 0, "list": 0}


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path.startswith("/releases"):
            SEEN["list"] += 1
            if SEEN.get("down"):
                self.send_error(404)
                return
            body = json.dumps(RELEASES).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        data = ASSETS.get(self.path.rsplit("/", 1)[-1])
        if data is None:
            self.send_error(404)
            return
        start = 0
        rng = self.headers.get("Range")
        if rng:
            SEEN["range"].append(rng)
            start = int(rng.split("=")[1].split("-")[0])
            self.send_response(206)
            self.send_header("Content-Range", "bytes %d-%d/%d" % (start, len(data) - 1, len(data)))
        else:
            self.send_response(200)
        self.send_header("Content-Length", str(len(data) - start))
        self.end_headers()
        if SEEN["cut"]:                       # break the transfer half way, once
            SEEN["cut"] -= 1
            self.wfile.write(data[start:start + (len(data) - start) // 2])
            self.wfile.flush()
            self.connection.shutdown(2)
            return
        self.wfile.write(data[start:])


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % srv.server_address[1]


def release(tag, asset=None, draft=False, pre=False, notes="notes"):
    name = asset or "untrash-%s-update.utslot" % tag.lstrip("v")
    return {"tag_name": tag, "name": "UntrashOS " + tag, "draft": draft, "prerelease": pre, "body": notes,
            "published_at": "2026-10-23T10:00:00Z", "html_url": BASE + "/r/" + tag,
            "assets": [{"name": name, "size": len(ASSETS.get(name, b"")), "browser_download_url": BASE + "/a/" + name},
                       {"name": "untrash-stick-%s.img.xz" % tag, "size": 1, "browser_download_url": BASE + "/a/x"}]}


def setenv(version="1.0", **upd):
    with open(W + "/version", "w") as f:
        f.write(version + "\n")
    with open(W + "/settings.json", "w") as f:
        json.dump({"update": dict({"check": True, "download": True, "channel": "stable"}, **upd)}, f)


with open(W + "/board.json", "w") as f:
    json.dump({"name": "test", "releases": BASE + "/releases", "asset": "untrash-*-update.utslot"}, f)
ENV = dict(os.environ, ZT_UPDATE_DIR=W + "/upd", ZT_BOARD_JSON=W + "/board.json", ZT_SETTINGS=W + "/settings.json",
           ZT_VERSION_FILE=W + "/version", ZT_SLOT_KEYS=W + "/keys", ZT_SIG=SIG, ZT_UPDATE_TIMEOUT="10")


def run(*a):
    r = subprocess.run([TOOL] + list(a), env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    st = json.loads(subprocess.run([TOOL, "status"], env=ENV, stdout=subprocess.PIPE, text=True).stdout)
    return r.returncode, r.stdout, st


try:
    # versions
    check("version order 1.0 < 1.0.1 < 1.1-rc1 < 1.1 < 1.10", SL.newer("1.0.1", "1.0") and SL.newer("1.1-rc1", "1.0.1")
          and SL.newer("1.1", "1.1-rc1") and SL.newer("1.10", "1.1") and SL.newer("v1.1", "1.0"))
    check("a dev build is older than every release", SL.newer("1.0", "dev") and not SL.newer("dev", "0.1"))

    ASSETS["untrash-1.1-update.utslot"] = slot("1.1")
    ASSETS["untrash-1.2-rc1-update.utslot"] = slot("1.2-rc1")
    ASSETS["untrash-1.3-update.utslot"] = slot("1.3")
    ASSETS["untrash-0.9-update.utslot"] = slot("0.9")
    RELEASES[:] = [release("v1.3", draft=True), release("v1.2-rc1", pre=True), release("v1.1", notes="What is new"), release("v0.9")]

    setenv("1.0", download=False)
    rc, out, st = run("check")
    av = st.get("available") or {}
    check("stable: newest non-draft, non-prerelease release is 1.1", rc == 0 and av.get("version") == "1.1" and av.get("notes") == "What is new")
    check("download off: found, not downloaded", st["download"]["state"] == "none" and not os.path.exists(W + "/upd/1.1.utslot"))

    setenv("1.0", channel="beta", download=False)
    rc, out, st = run("check")
    check("beta channel: the prerelease 1.2-rc1", st["available"]["version"] == "1.2-rc1" and st["available"]["prerelease"])

    setenv("1.0")
    SEEN["cut"] = 1
    rc, out, st = run("check")
    check("broken transfer: failed, partial file kept", rc == 1 and st["download"]["state"] == "failed" and os.path.exists(W + "/upd/1.1.utslot.part"))
    rc, out, st = run("download")
    check("resumed with Range, verified, ready", rc == 0 and st["download"]["state"] == "ready" and SEEN["range"]
          and open(W + "/upd/1.1.utslot", "rb").read() == ASSETS["untrash-1.1-update.utslot"])
    check("ready image passes the Desk's check", SL.verify(W + "/upd/1.1.utslot")["version"] == "1.1")
    n = SEEN["list"]
    rc, out, st = run("check")
    check("check again: still ready, no second download", st["download"]["state"] == "ready" and SEEN["list"] == n + 1)

    for what, data in (("signed by an unknown key", slot("1.4", key="bad")), ("payload damaged", slot("1.4", damage=True)),
                       ("manifest version differs from the release", slot("1.4", manifest_version="1.0"))):
        ASSETS["untrash-1.4-update.utslot"] = data
        RELEASES[:] = [release("v1.4")]
        rc, out, st = run("check")
        check("refused: %s (%s)" % (what, st["download"].get("error")), rc == 1 and st["download"]["state"] == "failed"
              and not os.path.exists(W + "/upd/1.4.utslot") and not os.path.exists(W + "/upd/1.1.utslot"))

    setenv("1.4")
    ASSETS["untrash-1.4-update.utslot"] = slot("1.4")
    RELEASES[:] = [release("v1.4"), release("v1.1")]
    rc, out, st = run("check")
    left = [f for f in os.listdir(W + "/upd") if f.endswith((".utslot", ".part"))]
    check("up to date: nothing offered, images removed", rc == 0 and st["available"] is None and left == [])

    SEEN["down"] = True
    rc, out, st = run("check")
    check("release page not reachable: error kept in the state", rc == 1 and "not reachable" in (st.get("error") or ""))
    SEEN["down"] = False

    setenv("1.0", check=False)
    n = SEEN["list"]
    rc, out, st = run("check")
    check("daily check off: no request", rc == 0 and SEEN["list"] == n)
    rc, out, st = run("check", "--manual")
    check("'Check now' works with the daily check off", SEEN["list"] == n + 1 and st["available"]["version"] == "1.4")
finally:
    srv.shutdown()
    shutil.rmtree(W, ignore_errors=True)

print("UPDATE TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", fails))
sys.exit(1 if fails else 0)
