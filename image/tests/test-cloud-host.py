#!/usr/bin/env python3
"""PC test of untrash-cloud (stock cloud apps with rclone), no root:
  python3 image/tests/test-cloud-host.py RCLONEROOT
RCLONEROOT: extracted Debian rclone deb (apt-get download rclone; dpkg-deb -x).
Checks: the real rclone OAuth helper gives a provider login address
(auth-start, no network needed); the whole browser-only OAuth chain with a
simulated provider (auth-start -> copied return address -> auth-finish ->
remote stored, config 0600); bad return addresses refused; FTP account with
obscured password; jobs on a local remote: two-way sync (first --resync,
then a deletion is mirrored), upload only, download only, due/interval
logic, status file, missing account reported."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-cloud")
fails = 0

FAKE = r'''#!/usr/bin/env python3
# rclone stand-in for "authorize" (simulated provider); everything else -> real rclone
import http.server, os, sys, threading
if "authorize" not in sys.argv:
    os.execv(os.environ["REAL_RCLONE"], [os.environ["REAL_RCLONE"]] + sys.argv[1:])
STATE = "teststate123"
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/auth?state=" + STATE):
            self.send_response(307)
            self.send_header("Location", "https://provider.example/oauth?state=%s&redirect_uri=http%%3A%%2F%%2Flocalhost%%3A53682%%2F" % STATE)
            self.end_headers()
        elif "code=" in self.path and "state=" + STATE in self.path:
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
            print('Paste the following into your remote machine --->\n{"access_token":"tok","token_type":"bearer","expiry":"0001-01-01T00:00:00Z"}\n<---End paste', flush=True)
            threading.Thread(target=srv.shutdown).start()
        else:
            self.send_response(400); self.end_headers()
srv = http.server.HTTPServer(("127.0.0.1", 53682), H)
print("NOTICE: Please go to the following link: http://127.0.0.1:53682/auth?state=" + STATE, flush=True)
srv.serve_forever()
'''


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name, flush=True)
    fails += 0 if cond else 1


def main():
    real = os.path.join(os.path.abspath(sys.argv[1]), "usr/bin/rclone")
    with tempfile.TemporaryDirectory() as W:
        os.chdir(W)
        env = dict(os.environ, ZT_CLOUD_RCLONE_CONF=W + "/etc/rclone.conf", ZT_SETTINGS=W + "/settings.json",
                   ZT_CLOUD_STATE=W + "/state", ZT_CLOUD_RUN=W + "/run", ZT_RCLONE=real, REAL_RCLONE=real)

        def cl(*a, input=None, e=None):
            r = subprocess.run([TOOL] + list(a), env=e or env, input=input, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, timeout=120)
            return r.returncode, r.stdout, r.stderr

        # 1. real rclone: login address of the provider
        rc, o, e = cl("auth-start", "dropbox")
        url = json.loads(o).get("url", "") if rc == 0 else ""
        check("real rclone: auth-start gives the Dropbox login page", url.startswith("https://www.dropbox.com/") and
              "redirect_uri=http%3A%2F%2Flocalhost%3A53682" in url)
        try:
            os.kill(json.load(open(W + "/run/cloud-auth.json"))["pid"], 15)
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(0.5)

        # 2. whole chain with a simulated provider
        fake = W + "/fake-rclone"
        open(fake, "w").write(FAKE)
        os.chmod(fake, 0o755)
        fe = dict(env, ZT_RCLONE=fake)
        rc, o, e = cl("auth-start", "dropbox", e=fe)
        check("auth-start (simulated provider)", rc == 0 and json.loads(o)["url"].startswith("https://provider.example/"))
        rc, o, e = cl("auth-finish", "Box", "https://evil.example/?state=teststate123&code=x", e=fe)
        check("foreign return address refused", rc != 0 and "Rücksprung" in e)
        rc, o, e = cl("auth-finish", "Box", "http://localhost:53682/?state=teststate123&error=access_denied", e=fe)
        check("denied login reported", rc != 0 and "abgelehnt" in e)
        rc, o, e = cl("auth-finish", "Box", "http://localhost:53682/?state=teststate123&code=abc", e=fe)
        check("auth-finish stores the account", rc == 0 and json.loads(o) == {"name": "Box", "type": "dropbox"})
        conf = open(W + "/etc/rclone.conf").read()
        check("rclone.conf 0600 with token", os.stat(W + "/etc/rclone.conf").st_mode & 0o777 == 0o600 and
              "[Box]" in conf and "type = dropbox" in conf and '"access_token":"tok"' in conf)
        rc, o, e = cl("auth-finish", "Box", "http://localhost:53682/?state=teststate123&code=abc", e=fe)
        check("same name twice refused", rc != 0)

        # 3. FTP account (Upload Manager target)
        rc, o, e = cl("add-ftp", "Ftp1", "ftp.example.net", "2121", "up", "1", input="geheim\n")
        conf = open(W + "/etc/rclone.conf").read()
        check("ftp account: host/port/user, password obscured, explicit TLS", rc == 0 and "host = ftp.example.net" in conf
              and "port = 2121" in conf and "geheim" not in conf and re.search(r"pass = \S+", conf) and "explicit_tls = true" in conf)

        # 4. jobs on a local remote
        subprocess.run([real, "--config", W + "/etc/rclone.conf", "config", "create", "Loc", "local"], stdout=subprocess.DEVNULL)
        for d in ("nas/sync", "cloud/sync", "nas/up", "cloud/down"):
            os.makedirs(W + "/" + d)
        open(W + "/nas/sync/a.txt", "w").write("a")
        open(W + "/cloud/sync/b.txt", "w").write("b")
        open(W + "/nas/up/u.txt", "w").write("u")
        open(W + "/cloud/down/d.txt", "w").write("d")
        jobs = [{"id": "aaaa0001", "name": "Sync", "remote": "Loc", "path": "cloud/sync", "local": W + "/nas/sync",
                 "direction": "both", "interval_min": 60, "active": True},
                {"id": "aaaa0002", "name": "Up", "remote": "Loc", "path": "cloud/up", "local": W + "/nas/up",
                 "direction": "up", "interval_min": 60, "active": True},
                {"id": "aaaa0003", "name": "Down", "remote": "Loc", "path": "cloud/down", "local": W + "/nas/down",
                 "direction": "down", "interval_min": 60, "active": True},
                {"id": "aaaa0004", "name": "Weg", "remote": "Gone", "path": "", "local": W + "/nas/x",
                 "direction": "up", "interval_min": 60, "active": False}]
        json.dump({"cloud": {"jobs": jobs}}, open(W + "/settings.json", "w"))
        rc, o, e = cl("run")
        check("run: due jobs (inactive one skipped)", rc == 0 and "aaaa0004" not in o)
        check("two-way: both sides have a.txt and b.txt", all(os.path.isfile(W + p) for p in
              ("/nas/sync/b.txt", "/cloud/sync/a.txt")))
        check("upload only", open(W + "/cloud/up/u.txt").read() == "u")
        check("download only", open(W + "/nas/down/d.txt").read() == "d")
        check("files 0666 (umask 0, stock 0777 model)", os.stat(W + "/nas/sync/b.txt").st_mode & 0o777 == 0o666)
        st = json.loads(cl("status")[1])
        check("status per job", st["aaaa0001"]["ok"] and st["aaaa0002"]["ok"] and "aaaa0004" not in st)
        rc, o, e = cl("run")
        check("interval: nothing due right after a run", o.strip() == "")
        os.unlink(W + "/cloud/sync/b.txt")
        open(W + "/nas/sync/c.txt", "w").write("c")
        rc, o, e = cl("run", "aaaa0001")
        check("two-way second run: deletion mirrored, new file up", rc == 0 and not os.path.exists(W + "/nas/sync/b.txt")
              and os.path.isfile(W + "/cloud/sync/c.txt"))
        rc, o, e = cl("run", "aaaa0004")
        check("missing account reported", rc == 1 and "Gone missing" in o)
        rc, o, e = cl("delete", "Ftp1")
        check("delete account", rc == 0 and "[Ftp1]" not in open(W + "/etc/rclone.conf").read())
        check("remotes list", {r["name"] for r in json.loads(cl("remotes")[1])} == {"Box", "Loc"})
    print("CLOUD TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
