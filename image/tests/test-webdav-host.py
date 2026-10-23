#!/usr/bin/env python3
"""PC test of the WebDAV configuration that untrash-config renders, with a
real Apache (no root needed):
  python3 image/tests/test-webdav-host.py APACHEROOT
APACHEROOT: extracted Debian debs apache2-bin libapr1 libaprutil1
libapache2-mod-authnz-external (apt-get download + dpkg-deb -x).
The stock test database (test_import_zyxel.py: admin rw / alice ro / bob deny
on "mixed", everybody on "guestonly") goes through render; Apache runs the
file with only paths swapped (modules, run dir, certificate, auth helper ->
a fake checker that knows admin/alice/bob with password "pw").  Checks with
real WebDAV requests: PROPFIND/GET for ro users, PUT/MKCOL/DELETE only for rw
users, no login -> 401, bob -> 401/403, https port answers, paths outside
/webdav denied."""
import base64
import http.client
import json
import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "rootfs")
fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name, flush=True)
    fails += 0 if cond else 1


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    ar = os.path.abspath(sys.argv[1])
    import importlib.util
    spec = importlib.util.spec_from_file_location("t", os.path.join(HERE, "test_import_zyxel.py"))
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    with tempfile.TemporaryDirectory() as W:
        root = W + "/root"
        cfg = root + "/etc/untrash/zyxel/stock-config"
        os.makedirs(cfg)
        t.make_db(cfg + "/ugs_conf.db")
        c = sqlite3.connect(cfg + "/ugs_conf.db")
        shares = {}
        for name, path in c.execute("SELECT s_name, s_path FROM smb_share WHERE s_enable='y'"):
            real = W + "/data/" + name
            os.makedirs(real)
            os.chmod(real, 0o777)
            open(real + "/hallo.txt", "w").write("hallo %s\n" % name)
            c.execute("UPDATE smb_share SET s_path=? WHERE s_name=?", (real, name))
            shares[name] = real
        c.commit()
        c.close()
        settings = W + "/settings.json"
        json.dump({"services": {"webdav": {"active": True, "anonymous": False}}}, open(settings, "w"))
        env = dict(os.environ, ZT_SETTINGS=settings, ZT_IMPORT_TOOL=os.path.join(FILES, "usr/sbin/untrash-import-zyxel"))
        r = subprocess.run([sys.executable, os.path.join(FILES, "usr/sbin/untrash-config"), "render", "--root", root],
                           env=env, stdout=subprocess.PIPE, text=True)
        check("render", r.returncode == 0 and "webdav" in r.stdout)
        conf = open(root + "/etc/untrash/webdav/httpd.conf").read()
        p1, p2 = free_port(), free_port()
        run = W + "/run"
        os.makedirs(run)
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=t",
                        "-keyout", W + "/k.pem", "-out", W + "/c.pem"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        fake = W + "/auth"
        open(fake, "w").write("#!/bin/sh\nread u; read p\n[ \"$p\" = pw ] && case \"$u\" in admin|alice|bob) exit 0;; esac\nexit 1\n")
        os.chmod(fake, 0o755)
        conf = (conf.replace("/usr/lib/apache2/modules/", ar + "/usr/lib/apache2/modules/")
                .replace("/run/untrash-webdav", run).replace("/etc/untrash/tls/untrash.crt", W + "/c.pem")
                .replace("/etc/untrash/tls/untrash.key", W + "/k.pem").replace("/usr/lib/untrash/untrash-webdav-auth", fake)
                .replace("Listen 5002", "Listen 127.0.0.1:%d" % p1).replace("Listen 5003", "Listen 127.0.0.1:%d" % p2)
                .replace("<VirtualHost *:5003>", "<VirtualHost *:%d>" % p2).replace("User www-data\nGroup www-data\n", "")
                .replace("ServerRoot /etc/apache2", "ServerRoot " + W).replace("ErrorLog syslog:daemon", "ErrorLog " + W + "/error.log")
                .replace("TypesConfig /etc/mime.types", "TypesConfig /dev/null"))
        open(W + "/httpd.conf", "w").write(conf)
        aenv = dict(os.environ, LD_LIBRARY_PATH=ar + "/usr/lib/x86_64-linux-gnu")
        ap = ar + "/usr/sbin/apache2"
        r = subprocess.run([ap, "-t", "-f", W + "/httpd.conf"], env=aenv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        check("apache2 -t: syntax ok (%s)" % r.stdout.strip().splitlines()[-1][:60], r.returncode == 0)
        if r.returncode:
            print(r.stdout)
            return
        srv = subprocess.Popen([ap, "-DFOREGROUND", "-f", W + "/httpd.conf"], env=aenv)
        try:
            for _ in range(50):
                try:
                    socket.create_connection(("127.0.0.1", p1), 0.2).close()
                    break
                except OSError:
                    time.sleep(0.1)

            def req(method, path, user=None, body=None, tls=False, headers=None):
                h = http.client.HTTPSConnection("127.0.0.1", p2, context=ssl._create_unverified_context()) if tls \
                    else http.client.HTTPConnection("127.0.0.1", p1)
                hd = dict(headers or {})
                if user:
                    hd["Authorization"] = "Basic " + base64.b64encode(("%s:pw" % user).encode()).decode()
                h.request(method, path, body=body, headers=hd)
                resp = h.getresponse()
                data = resp.read()
                return resp.status, data
            pf = {"Depth": "1"}
            check("no login -> 401", req("PROPFIND", "/webdav/mixed/", headers=pf)[0] == 401)
            st, body = req("PROPFIND", "/webdav/mixed/", "alice", headers=pf)
            check("alice (ro) PROPFIND 207 lists hallo.txt", st == 207 and b"hallo.txt" in body)
            check("alice GET", req("GET", "/webdav/mixed/hallo.txt", "alice") == (200, b"hallo mixed\n"))
            check("alice PUT refused", req("PUT", "/webdav/mixed/neu.txt", "alice", b"x")[0] in (401, 403)
                  and not os.path.exists(shares["mixed"] + "/neu.txt"))
            check("bob refused on mixed", req("PROPFIND", "/webdav/mixed/", "bob", headers=pf)[0] in (401, 403))
            check("admin PUT 201", req("PUT", "/webdav/mixed/neu.txt", "admin", b"data")[0] == 201
                  and open(shares["mixed"] + "/neu.txt").read() == "data")
            mk = req("MKCOL", "/webdav/mixed/ordner", "admin")[0]
            de = req("DELETE", "/webdav/mixed/ordner", "admin")[0]
            check("admin MKCOL + DELETE (%d/%d)" % (mk, de), mk == 201 and de == 204)
            check("bob writes on guestonly (everybody)", req("PUT", "/webdav/guestonly/b.txt", "bob", b"b")[0] == 201)
            check("guestplus closed (guest only, anonymous off)", req("PROPFIND", "/webdav/guestplus/", "admin", headers=pf)[0] in (401, 403))
            check("https port: alice PROPFIND 207", req("PROPFIND", "/webdav/mixed/", "alice", tls=True, headers=pf)[0] == 207)
            check("outside /webdav denied", req("GET", "/", "admin")[0] in (401, 403))
        finally:
            srv.terminate()
            srv.wait()
    print("WEBDAV TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
