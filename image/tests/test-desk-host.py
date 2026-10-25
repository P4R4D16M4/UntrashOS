#!/usr/bin/env python3
"""PC test of Untrash Desk (usr/lib/untrash/untrash-desk) in test mode.

  python3 image/tests/test-desk-host.py           API test, exits 0/1
  python3 image/tests/test-desk-host.py --serve [PORT] [--fresh]
        only build the test root and run the Desk (browser preview);
        --fresh = way A (no users yet, first setup)

The test root holds the stock test database of test_import_zyxel.py (users
admin/alice/bob, group family, shares incl. rights cases), two volumes under
/i-data, zoneinfo and settings.  ZT_DESK_TEST=1: system commands are only
recorded (SYSLOG), the login password is "test-passwort" for every user.
Checks: CSRF header, login and lockout, admin/user separation, users and
groups (database + system commands), share create/save/delete (rights end up
in the rendered smb.conf exactly), file browser with the stock rights
(alice ro / bob deny on "mixed", path traversal refused), settings
validation, first setup (way A), way D (rollback marker on a test stick).
"""
import base64
import hashlib
import hmac
import http.cookiejar
import json
import re
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "rootfs")
BOARD = os.environ.get("ZT_BOARD_ROOTFS")   # board tools (untrash-power), docs/board-interface.md
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
PW = "test-passwort"
sys.path.insert(0, HERE)


def build_root(w, fresh=False):
    import importlib.util
    spec = importlib.util.spec_from_file_location("t", os.path.join(HERE, "test_import_zyxel.py"))
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    r = os.path.join(w, "root")
    cfg = r + "/etc/untrash/zyxel/stock-config"
    os.makedirs(cfg)
    if not fresh:
        t.make_db(cfg + "/ugs_conf.db")
        open(cfg + "/py_conf", "w").write(t.PYCONF)
        open(r + "/etc/untrash/zyxel/takeover.json", "w").write('{"rw": true}')
    for vol in ("aaaa0001", "sysvol-real"):
        os.makedirs(r + "/i-data/" + vol + "/.system")
        open(r + "/i-data/" + vol + "/.system/name_label", "w").write("Volume " + vol[:4])
    os.symlink(r + "/i-data/sysvol-real", r + "/i-data/sysvol")
    if not fresh:
        c = sqlite3.connect(cfg + "/ugs_conf.db")
        for (p,) in c.execute("SELECT s_path FROM smb_share"):
            if "gone" not in p:
                os.makedirs(r + p.replace("/i-data/sysvol/", "/i-data/sysvol-real/"), exist_ok=True)
        c.close()
        open(r + "/i-data/aaaa0001/mixed/readme.txt", "w").write("hallo\n")
    os.makedirs(r + "/usr/share")
    os.symlink("/usr/share/zoneinfo", r + "/usr/share/zoneinfo")
    os.makedirs(r + "/proc")
    open(r + "/proc/uptime", "w").write("12345.6 1000.0\n")
    open(r + "/proc/loadavg", "w").write("0.10 0.20 0.30 1/100 42\n")
    open(r + "/proc/meminfo", "w").write("MemTotal:  1003520 kB\nMemAvailable:  603520 kB\n")
    open(r + "/proc/mdstat", "w").write("Personalities : [raid1]\nmd2 : active raid1 sdb3[1] sda3[0]\n"
                                        "      1949221888 blocks super 1.2 [2/2] [UU]\n\n"
                                        "md0 : active raid1 sdb1[1] sda1[0]\n      1998784 blocks super 1.2 [4/2] [UU__]\n\n"
                                        "unused devices: <none>\n")
    os.makedirs(r + "/etc", exist_ok=True)
    open(r + "/etc/untrash-version", "w").write("test-desk-1\n")
    # test stick with a completed install run (way D)
    stick = os.path.join(w, "stick")
    run = stick + "/UNTRASH/install-20261010-080000"
    os.makedirs(run + "/flash")
    for f, n in (("mtd2-before-a.bin", 4096), ("mtd6-before-a.bin", 8192)):
        open(os.path.join(run, f), "wb").write(os.urandom(n))
    import hashlib
    h = lambda f: hashlib.sha256(open(os.path.join(run, f), "rb").read()).hexdigest()  # noqa: E731
    open(run + "/device.env", "w").write("LOADER_SLOT=2\nLOADER_MTD=6\nENV_OLD_SHA256=%s\nKX_OLD_SHA256=%s\n" % (
        h("mtd2-before-a.bin"), h("mtd6-before-a.bin")))
    open(run + "/install.log", "w").write("x RESULT DONE loader in kernel2\n")
    open(run + "/flash/VERIFIED", "w").write("files=9\n")
    return r, stick


def env_for(r, stick, port):
    sig = os.path.join(r, "zt-sig")           # untrash-mesh signs with the PC build of slot/zt-sig.c
    if not os.path.exists(sig):
        osr = os.path.abspath(os.path.join(HERE, "..", ".."))
        subprocess.run(["gcc", "-O2", "-I" + osr + "/third_party/tweetnacl", "-o", sig, osr + "/slot/zt-sig.c",
                        osr + "/third_party/tweetnacl/tweetnacl.c"], check=True)
    return dict(os.environ, ZT_DESK_TEST="1", ZT_DESK_ROOT=r, ZT_DESK_PORT=str(port), ZT_DESK_BIND="127.0.0.1",
                ZT_MESH_TOOL=os.path.join(FILES, "usr/lib/untrash/untrash-mesh"), ZT_MESH_DIR=r + "/etc/untrash/mesh", ZT_SIG=sig,
                ZT_MESH_FAKE_WG=r + "/mesh-wg.json", ZT_MESH_HOSTS=r + "/hosts", ZT_MESH_SMB=r + "/etc/samba/untrash-mesh.conf",
                ZT_MESH_PDATA=r + "/p-data", ZT_MESH_FAKE_MOUNT=r + "/mesh-mounts.json", ZT_MESH_FAKE_ACCOUNTS=r + "/mesh-accounts.json",
                ZT_MESH_ENDPOINTS="192.168.1.20:51820", ZT_MESH_JOIN_HOST="127.0.0.1",
                ZT_MESH_ADDRMAP="{}",                  # PC test: the app reaches the Desk over 127.0.0.1, not the mesh
                ZT_DESK_TESTPW=PW, ZT_DESK_STICK=stick,
                ZT_IMPORT_TOOL=os.path.join(FILES, "usr/sbin/untrash-import-zyxel"),
                ZT_CONFIG_TOOL=os.path.join(FILES, "usr/sbin/untrash-config"),
                ZT_DESK_STATIC=os.path.join(FILES, "usr/share/untrash/desk"),
                ZT_DESIGN_DIR=os.path.join(ROOT, "design"),
                ZT_SMB_EXTRA=r + "/etc/untrash/smb-extra.json",
                ZT_STORAGE_TOOL=os.path.join(HERE, "fake-untrash-storage"),
                ZT_CLOUD_TOOL=os.path.join(HERE, "fake-untrash-cloud"),
                ZT_ARIA2_RPC="http://127.0.0.1:%d/jsonrpc" % (port + 500),
                ZT_BACKUP_TOOL=os.path.join(FILES, "usr/lib/untrash/untrash-backup"),
                ZT_SETTINGS=r + "/etc/untrash/settings.json", ZT_BACKUP_STATE=r + "/var/lib/untrash/backup", ZT_BACKUP_ROOT=r,
                ZT_NOTIFY_TOOL="/bin/true", ZT_UPNP_TOOL=os.path.join(FILES, "usr/lib/untrash/untrash-upnp"),
                ZT_UPNPC=os.path.join(HERE, "fake-upnpc"), ZT_FAKE_UPNP_STATE=r + "/upnp-state.json",
                ZT_ISCSI_TOOL=os.path.join(FILES, "usr/lib/untrash/untrash-iscsi"), ZT_ISCSI_ROOT=r,
                ZT_POWER_TOOL=os.path.join(BOARD, "usr/lib/untrash/untrash-power") if BOARD else "/bin/false",
                ZT_UPDATE_TOOL="/bin/true",
                ZT_SOUND_TOOL=os.path.join(FILES, "usr/lib/untrash/untrash-sound"), ZT_SOUND_USER=r + "/etc/untrash/sounds.json",
                ZT_SOUND_DEVICE=r + "/tone", ZT_SOUND_LOG=r + "/tones", ZT_SOUND_LOG_MS="1", ZT_SOUND_NO_SLEEP="1",
                ZT_SOUND_LOCK=r + "/sound.lock", ZT_EXPORT_TOOL=os.path.join(FILES, "usr/lib/untrash/untrash-export"),
                ZT_TRANSFER_CHUNK="65536", ZT_TRANSFER_DELAY="0.02",
                ZT_DLNA_URL="http://127.0.0.1:9/", ZT_PROJECT=os.path.join(FILES, "usr/share/untrash/project.json"),
                ZT_ADBLOCK_TOOL=os.path.join(FILES, "usr/lib/untrash/untrash-adblock"), ZT_ADBLOCK_STORE=r + "/etc/untrash/adblock.json",
                ZT_ADBLOCK_DATA=r + "/var/lib/untrash/adblock", ZT_ADBLOCK_RUN=r + "/run/untrash/adblock")


class Client:
    def __init__(self, port):
        self.base = "http://127.0.0.1:%d" % port
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def req(self, path, body=None, raw=None, csrf=True):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        rq = urllib.request.Request(self.base + path, data=data)
        if data is not None and csrf:
            rq.add_header("X-UT", "1")
        try:
            with self.op.open(rq) as resp:
                b = resp.read()
                return resp.status, (json.loads(b) if resp.headers.get("Content-Type") == "application/json" else b)
        except urllib.error.HTTPError as e:
            b = e.read()
            try:
                return e.code, json.loads(b)
            except ValueError:
                return e.code, b


def serve(port, fresh):
    w = tempfile.mkdtemp(prefix="desk-")
    r, stick = build_root(w, fresh)
    print("test root %s, http://127.0.0.1:%d/ (password: %s)" % (r, port, PW), flush=True)
    os.execve(sys.executable, [sys.executable, os.path.join(FILES, "usr/lib/untrash/untrash-desk")], env_for(r, stick, port))


# GET endpoints of the Desk, read from the server source (ADMIN_GET + view routes)
ADMIN_GETS = set(re.findall(r'"(/api/[a-z/-]+)"', re.search(r"ADMIN_GET = \{(.*?)\}", open(os.path.join(
    FILES, "usr/lib/untrash/untrash-desk")).read(), re.S).group(1))) | {"/api/media", "/api/tv", "/api/export/targets",
                                                                       "/api/export/jobs", "/api/links", "/api/shares"}


def main():
    fails = []

    def check(name, cond):
        print(("ok   " if cond else "FAIL ") + name, flush=True)
        if not cond:
            fails.append(name)

    with tempfile.TemporaryDirectory() as w:
        r, stick = build_root(w)
        port = 18000 + os.getpid() % 2000
        srv = subprocess.Popen([sys.executable, os.path.join(FILES, "usr/lib/untrash/untrash-desk")],
                               env=env_for(r, stick, port), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            for _ in range(50):
                try:
                    urllib.request.urlopen("http://127.0.0.1:%d/api/state" % port)
                    break
                except OSError:
                    time.sleep(0.1)
            a, u, g = Client(port), Client(port), Client(port)
            st, j = a.req("/api/state")
            check("state: initialized, not logged in", st == 200 and j["initialized"] and not j["user"])
            st, page = a.req("/")
            check("index page served", st == 200 and b"desk.js" in page)
            st, _ = a.req("/ut/untrash.css")
            check("design css served", st == 200)
            check("static traversal refused", a.req("/desk/../../../../etc/passwd")[0] == 404)
            check("login without X-UT refused (CSRF)", a.req("/api/login", {"user": "admin", "password": PW}, csrf=False)[0] == 403)
            check("wrong password 401", a.req("/api/login", {"user": "admin", "password": "x"})[0] == 401)
            check("admin login", a.req("/api/login", {"user": "admin", "password": PW})[0] == 200)
            check("pc-guest cannot log in", g.req("/api/login", {"user": "pc-guest", "password": PW})[0] == 401)
            check("user login (alice)", u.req("/api/login", {"user": "alice", "password": PW})[0] == 200)
            me = a.req("/api/me")[1]
            check("me admin", me["user"] == "admin" and me["admin"] is True)
            check("alice is no admin, overview 403", u.req("/api/overview")[0] == 403)
            st, o = a.req("/api/overview")
            check("overview: version, RAID, volumes", st == 200 and o["version"] == "test-desk-1" and
                  o["arrays"][0]["health"] == "UU" and len(o["volumes"]) == 2)
            st, us = a.req("/api/users")
            check("users list", st == 200 and {x["name"] for x in us["users"]} >= {"admin", "alice", "bob", "pc-guest"})
            # users
            check("short password refused", a.req("/api/users/create", {"name": "carol", "password": "kurz"})[0] == 400)
            st, j = a.req("/api/users/create", {"name": "carol", "password": "Sehr-Geheim-1", "groups": ["family"]})
            check("create carol (uid 506)", st == 200 and j["uid"] == 506)
            check("duplicate refused", a.req("/api/users/create", {"name": "Carol", "password": "Sehr-Geheim-1"})[0] == 400)
            c = sqlite3.connect(r + "/etc/untrash/zyxel/stock-config/ugs_conf.db")
            check("carol in db with NT hash and in family",
                  c.execute("SELECT passwd FROM smb_user WHERE uname='carol'").fetchone()[0].startswith("X" * 32 + ":") and
                  c.execute("SELECT count(*) FROM group_member WHERE uname='carol' AND gname='family'").fetchone()[0] == 1)
            st, gj = a.req("/api/groups/create", {"name": "buero", "members": ["alice"]})
            check("group create", st == 200 and gj["gid"] == 502)
            check("group members set", a.req("/api/groups/members", {"name": "buero", "members": ["bob", "carol"]})[0] == 200 and
                  sorted(x for (x,) in c.execute("SELECT uname FROM group_member WHERE gname='buero'")) == ["bob", "carol"])
            # shares
            st, sh = a.req("/api/shares")
            check("shares + volumes", st == 200 and any(s["name"] == "mixed" for s in sh["shares"]) and
                  any(v["id"] == "aaaa0001" for v in sh["volumes"]))
            st, _ = a.req("/api/shares/save", {"new": True, "name": "Projekte", "volume": "aaaa0001"})
            check("share create (folder made)", st == 200 and os.path.isdir(r + "/i-data/aaaa0001/Projekte"))
            st, _ = a.req("/api/shares/save", {"name": "Projekte", "description": "Arbeit", "recycle": True, "media": 3,
                                                "users": {"admin": "rw", "carol": "ro"}, "groups": {"buero": "rw", "family": "deny"}})
            smb = open(r + "/etc/samba/smb.conf").read()
            sec = smb.split("[Projekte]")[1].split("\n[")[0]
            check("rights rendered into smb.conf", st == 200 and 'valid users = "admin" "carol" "+buero"' in sec and
                  'read list = "carol"' in sec and 'invalid users = "+family"' in sec and "vfs objects = recycle" in sec)
            s2 = json.load(open(r + "/etc/untrash/settings.json"))
            check("media flags -> media server settings", s2["services"]["mediaserver"]["shares"].get("Projekte") == 3)
            check("bad right refused", a.req("/api/shares/save", {"name": "Projekte", "users": {"alice": "admin"}})[0] == 400)
            check("unknown user in rights refused", a.req("/api/shares/save", {"name": "Projekte", "users": {"zed": "rw"}})[0] == 400)
            check("built-in share stays", a.req("/api/shares/delete", {"name": "admin"})[0] == 400)
            st, _ = a.req("/api/shares/delete", {"name": "Projekte"})
            check("share delete keeps the folder", st == 200 and os.path.isdir(r + "/i-data/aaaa0001/Projekte") and
                  "[Projekte]" not in open(r + "/etc/samba/smb.conf").read())
            # files with stock rights: alice ro on mixed, bob deny
            st, f = u.req("/api/files?share=mixed&path=")
            check("alice lists mixed", st == 200 and [e["name"] for e in f["entries"]] == ["readme.txt"])
            st, data = u.req("/api/files/download?share=mixed&path=readme.txt")
            check("alice downloads", st == 200 and data == b"hallo\n")
            check("alice cannot write (ro)", u.req("/api/files/op", {"op": "mkdir", "share": "mixed", "path": "", "name": "x"})[0] == 403)
            b = Client(port)
            b.req("/api/login", {"user": "bob", "password": PW})
            check("bob denied on mixed", b.req("/api/files?share=mixed&path=")[0] == 403)
            check("traversal refused", u.req("/api/files?share=mixed&path=../../")[0] == 403)
            st, _ = a.req("/api/files/upload?share=mixed&path=&name=neu.txt", raw=b"12345")
            check("admin upload", st == 200 and open(r + "/i-data/aaaa0001/mixed/neu.txt").read() == "12345")
            check("admin rename + delete", a.req("/api/files/op", {"op": "rename", "share": "mixed", "path": "neu.txt", "name": "n2.txt"})[0] == 200
                  and a.req("/api/files/op", {"op": "delete", "share": "mixed", "path": "n2.txt"})[0] == 200
                  and not os.path.exists(r + "/i-data/aaaa0001/mixed/n2.txt"))
            # Status → processes (fake /proc in the test root)
            for pid, name, ppid, cmd, uid, ticks in ((1, "systemd", 0, "/sbin/init", 0, 900), (77, "kworker/0:1", 2, "", 0, 5),
                                                     (4242, "rclone", 1, "rclone sync /i-data/x remote:", 1000, 300)):
                os.makedirs(r + "/proc/%d" % pid, exist_ok=True)
                open(r + "/proc/%d/stat" % pid, "w").write("%d (%s) S %d 1 1 0 -1 0 0 0 0 0 %d 50 0 0 20 0 1 0 1234%d 99999 512 0\n"
                                                         % (pid, name, ppid, ticks, pid))
                open(r + "/proc/%d/status" % pid, "w").write("Name:\t%s\nUid:\t%d\t%d\t%d\t%d\n" % (name, uid, uid, uid, uid))
                open(r + "/proc/%d/cmdline" % pid, "w").write(cmd.replace(" ", "\0"))
            os.makedirs(r + "/etc", exist_ok=True)
            with open(r + "/etc/passwd", "a") as pw:
                pw.write("root:x:0:0::/root:/bin/sh\nalice:x:1000:500::/nonexistent:/bin/sh\n")
            st, pj = a.req("/api/processes")
            ps = {p["pid"]: p for p in pj.get("processes", [])}
            check("processes: listed with name, user, command, memory", st == 200 and ps[4242]["name"] == "rclone" and ps[4242]["user"] == "alice"
                  and ps[4242]["cmd"] == "rclone sync /i-data/x remote:" and ps[4242]["rss"] == 512 * os.sysconf("SC_PAGE_SIZE"))
            check("processes: kernel threads marked", ps[77]["kernel"] is True and ps[4242]["kernel"] is False)
            check("processes: users get 403", u.req("/api/processes")[0] == 403 and u.req("/api/processes/kill", {"pid": 4242, "start": ps[4242]["start"]})[0] == 403)
            st, kj = a.req("/api/processes/kill", {"pid": 4242, "start": ps[4242]["start"], "signal": "TERM"})
            check("processes: end one (TERM)", st == 200 and kj["name"] == "rclone")
            check("processes: KILL on request", a.req("/api/processes/kill", {"pid": 4242, "start": ps[4242]["start"], "signal": "KILL"})[0] == 200)
            check("processes: a PID used again (other start time) is not hit", a.req("/api/processes/kill", {"pid": 4242, "start": 1})[0] == 409)
            check("processes: PID 1 and kernel threads are refused", a.req("/api/processes/kill", {"pid": 1, "start": ps[1]["start"]})[0] == 400
                  and a.req("/api/processes/kill", {"pid": 77, "start": ps[77]["start"]})[0] == 400)
            check("processes: an ended process", a.req("/api/processes/kill", {"pid": 9999, "start": 1})[0] == 409)
            for pid in (1, 77, 4242):
                shutil.rmtree(r + "/proc/%d" % pid)
            # file manager: recycle bin, copy/move jobs, ZIP, search, size, folder upload
            mx = r + "/i-data/aaaa0001/mixed"
            check("delete on a share with recycle bin moves it there (tree kept)", os.path.isfile(mx + "/recycle/n2.txt"))
            open(mx + "/n2.txt", "w").write("again")
            a.req("/api/files/op", {"op": "delete", "share": "mixed", "path": "n2.txt"})
            check("a second delete of the same name: Samba's \"Copy #1 of\"", os.path.isfile(mx + "/recycle/Copy #1 of n2.txt"))
            check("delete inside the recycle bin is permanent", a.req("/api/files/op", {"op": "delete", "share": "mixed", "path": "recycle/n2.txt"})[0] == 200
                  and not os.path.exists(mx + "/recycle/n2.txt"))
            st, fl = a.req("/api/files?share=mixed&path=")
            check("the listing says the share has a recycle bin", fl.get("recycle") is True and a.req("/api/files?share=groups&path=")[1].get("recycle") is False)
            os.makedirs(mx + "/fm/sub/leer")
            open(mx + "/fm/a.txt", "w").write("A" * 3000)
            open(mx + "/fm/sub/b.txt", "w").write("B")
            check("several deleted at once", a.req("/api/files/op", {"op": "delete", "share": "mixed", "paths": ["fm/zz1", "fm/zz2"]})[0] == 404)
            def job_wait(cl, jid):
                for _i in range(100):
                    js = [j for j in cl.req("/api/files/jobs")[1]["jobs"] if j["id"] == jid]
                    if js and js[0]["state"] != "running":
                        return js[0]
                    time.sleep(0.1)
                return {}
            def xfer(cl, body):
                st, j = cl.req("/api/files/transfer", body)
                return (st, job_wait(cl, j["job"])) if st == 200 else (st, j)
            st, j = xfer(a, {"op": "copy", "items": [{"share": "mixed", "path": "fm"}], "dst": {"share": "groups", "path": ""}})
            g0 = r + "/i-data/aaaa0001/groups"
            check("copy a folder to another share (tree, empty folder, bytes counted)", st == 200 and j.get("state") == "done"
                  and open(g0 + "/fm/sub/b.txt").read() == "B" and os.path.isdir(g0 + "/fm/sub/leer") and j["done"] == 3001 and j["total"] == 3001
                  and os.path.isdir(mx + "/fm"))
            st, j = xfer(a, {"op": "copy", "items": [{"share": "mixed", "path": "fm/a.txt"}], "dst": {"share": "mixed", "path": "fm"}})
            check("copy into the same folder: \"a (2).txt\"", j.get("state") == "done" and os.path.isfile(mx + "/fm/a (2).txt"))
            open(g0 + "/fm/a.txt", "w").write("old")
            xfer(a, {"op": "copy", "items": [{"share": "mixed", "path": "fm/a.txt"}], "dst": {"share": "groups", "path": "fm"}, "conflict": "skip"})
            check("conflict skip keeps the old file", open(g0 + "/fm/a.txt").read() == "old")
            xfer(a, {"op": "copy", "items": [{"share": "mixed", "path": "fm/a.txt"}], "dst": {"share": "groups", "path": "fm"}, "conflict": "overwrite"})
            check("conflict overwrite replaces it", open(g0 + "/fm/a.txt").read() == "A" * 3000)
            st, j = xfer(a, {"op": "move", "items": [{"share": "mixed", "path": "fm/a (2).txt"}, {"share": "mixed", "path": "fm/sub"}], "dst": {"share": "groups", "path": ""}})
            check("move two items to another share", j.get("state") == "done" and os.path.isfile(g0 + "/a (2).txt") and os.path.isfile(g0 + "/sub/b.txt")
                  and not os.path.exists(mx + "/fm/sub") and not os.path.exists(mx + "/fm/a (2).txt"))
            check("a folder cannot go into itself", a.req("/api/files/transfer", {"op": "move", "items": [{"share": "groups", "path": "fm"}], "dst": {"share": "groups", "path": "fm/sub"}})[0] == 400)
            check("a whole share is not copied", a.req("/api/files/transfer", {"op": "copy", "items": [{"share": "groups", "path": ""}], "dst": {"share": "mixed", "path": ""}})[0] == 400)
            check("alice (read only on mixed) cannot move out of it", u.req("/api/files/transfer", {"op": "move", "items": [{"share": "mixed", "path": "readme.txt"}], "dst": {"share": "mixed", "path": "fm"}})[0] == 403)
            check("bob (no access) cannot copy from mixed", b.req("/api/files/transfer", {"op": "copy", "items": [{"share": "mixed", "path": "readme.txt"}], "dst": {"share": "guestplus", "path": ""}})[0] == 403)
            check("jobs are per user", not any(j for j in u.req("/api/files/jobs")[1]["jobs"]))
            import io, zipfile
            st, zb = a.req("/api/files/zip?" + urllib.parse.urlencode({"share": "groups", "path": "fm"}))
            zn = sorted(zipfile.ZipFile(io.BytesIO(zb)).namelist()) if st == 200 else []
            check("a folder as ZIP (with its empty folder)", zn == ["fm/a.txt", "fm/sub/b.txt", "fm/sub/leer/"], )
            st, zb = a.req("/api/files/zip?" + urllib.parse.urlencode({"share": "groups", "path": "", "names": json.dumps(["a (2).txt", "sub"])}))
            zf = zipfile.ZipFile(io.BytesIO(zb)) if st == 200 else None
            check("a selection as ZIP", zf and sorted(zf.namelist()) == ["a (2).txt", "sub/b.txt", "sub/leer/"] and zf.read("a (2).txt") == b"A" * 3000)
            check("ZIP keeps the rights (bob)", b.req("/api/files/zip?" + urllib.parse.urlencode({"share": "mixed", "path": ""}))[0] == 403)
            check("ZIP refuses names outside the folder", a.req("/api/files/zip?" + urllib.parse.urlencode({"share": "groups", "path": "fm", "names": json.dumps(["../../mixed"])}))[0] == 403)
            st, sr = a.req("/api/files/search?" + urllib.parse.urlencode({"share": "groups", "path": "", "q": "B.TX"}))
            check("search below a folder (case-insensitive)", st == 200 and [x["path"] for x in sr["results"]] == ["fm/sub/b.txt", "sub/b.txt"])
            check("search needs 2 characters", a.req("/api/files/search?share=groups&path=&q=b")[0] == 400)
            st, sz = a.req("/api/files/size?share=groups&path=fm")
            check("folder size", st == 200 and sz["size"] == 3001 and sz["files"] == 2 and sz["dirs"] == 2)
            st, _ = a.req("/api/files/upload?" + urllib.parse.urlencode({"share": "groups", "path": "", "name": "c.txt", "dirs": "Neu/tief"}), raw=b"C")
            check("folder upload makes the subfolders", st == 200 and open(g0 + "/Neu/tief/c.txt").read() == "C")
            check("folder upload refuses .. and hidden folders", a.req("/api/files/upload?" + urllib.parse.urlencode({"share": "groups", "path": "", "name": "x", "dirs": "../x"}), raw=b"x")[0] == 400
                  and a.req("/api/files/upload?" + urllib.parse.urlencode({"share": "groups", "path": "", "name": "x", "dirs": ".ssh"}), raw=b"x")[0] == 400)
            # transfers: copy/move, uploads and downloads in one list (untrash-transfer does the writing)
            def ops(cl, q=""):
                return cl.req("/api/transfers" + q)[1]["ops"]
            up = [o for o in ops(a) if o["kind"] == "upload" and o["name"] == "c.txt"]
            check("transfers: an upload is listed (done, size, target)", up and up[0]["state"] == "done" and up[0]["total"] == 1
                  and up[0]["where"] == "groups/Neu/tief" and oct(os.stat(g0 + "/Neu/tief/c.txt").st_mode & 0o777) == "0o777")
            check("transfers: copy jobs are listed with their kind", any(o["kind"] == "copy" and o["state"] == "done" for o in ops(a)))
            a.req("/api/files/download?share=groups&path=fm/a.txt")
            dl = [o for o in ops(a) if o["kind"] == "download"]
            check("transfers: a download is listed, an inline view is not", dl and dl[0]["name"] == "a.txt" and dl[0]["state"] == "done"
                  and dl[0]["done"] == dl[0]["total"] == 3000)
            n_dl = len(dl)
            open(g0 + "/fm/p.jpg", "wb").write(b"\xff\xd8\xff\xe0jpeg")
            a.req("/api/files/download?share=groups&path=fm/p.jpg&inline=1")
            check("transfers: inline views are not listed", len([o for o in ops(a) if o["kind"] == "download"]) == n_dl)
            st, zb = a.req("/api/files/zip?" + urllib.parse.urlencode({"share": "groups", "path": "fm"}))
            zo = [o for o in ops(a) if o["kind"] == "download" and o["name"] == "fm.zip"]
            check("transfers: a ZIP download is listed with its size at the end", st == 200 and zo and zo[0]["state"] == "done" and zo[0]["total"] == len(zb))
            check("transfers: alice sees only her own", all(o["user"] == "alice" for o in ops(u)) and any(o["user"] == "admin" for o in ops(a)))
            open(g0 + "/gross.bin", "wb").write(os.urandom(4 << 20))
            st, j = a.req("/api/files/transfer", {"op": "copy", "items": [{"share": "groups", "path": "gross.bin"}], "dst": {"share": "groups", "path": "fm"}})
            jid = j.get("job", "")
            check("transfers: alice cannot cancel the admin's copy", u.req("/api/transfers/ctl", {"id": jid, "action": "cancel"})[0] == 404)
            time.sleep(0.3)
            st, _ = a.req("/api/transfers/ctl", {"id": jid, "action": "pause"})
            o1 = [o for o in ops(a) if o["id"] == jid]
            time.sleep(0.5)
            o2 = [o for o in ops(a) if o["id"] == jid]
            check("transfers: pause holds the copy (state paused, no progress)", st == 200 and o1 and o1[0]["state"] == "paused"
                  and o2[0]["done"] == o1[0]["done"] < 4 << 20 and os.path.exists(g0 + "/fm/gross.bin.untrash-part"))
            def data_fds(pid):
                out = []
                for fd in os.listdir("/proc/%d/fd" % pid):
                    try:
                        t = os.readlink("/proc/%d/fd/%s" % (pid, fd))
                    except OSError:
                        continue
                    if t.startswith(r + "/i-data/"):
                        out.append(t)
                return out
            # a CIFS file open for writing in the Desk hangs every process it forks (untrash1, 2026-10-25)
            check("transfers: during a copy the Desk itself holds no file of a data volume open", data_fds(srv.pid) == [])
            a.req("/api/transfers/ctl", {"id": jid, "action": "resume"})
            time.sleep(0.3)
            check("transfers: resume continues it", [o for o in ops(a) if o["id"] == jid][0]["done"] > o2[0]["done"])
            a.req("/api/transfers/ctl", {"id": jid, "action": "pause"})
            st, _ = a.req("/api/transfers/ctl", {"id": jid, "action": "cancel"})
            j = job_wait(a, jid)
            check("transfers: cancel of a paused copy ends it and removes the partial file", st == 200 and j.get("state") == "cancelled"
                  and not os.path.exists(g0 + "/fm/gross.bin.untrash-part") and not os.path.exists(g0 + "/fm/gross.bin"))
            check("transfers: an ended one cannot be cancelled again", a.req("/api/transfers/ctl", {"id": jid, "action": "cancel"})[0] == 409)
            # an upload cancelled in the Transfers window while its body is still coming
            import http.client
            ck = "; ".join("%s=%s" % (c.name, c.value) for c in a.jar)
            hc = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            hc.putrequest("POST", "/api/files/upload?share=groups&path=&name=lang.bin")
            for k, v in (("X-UT", "1"), ("Cookie", ck), ("Content-Type", "application/octet-stream"), ("Content-Length", str(8 << 20))):
                hc.putheader(k, v)
            hc.endheaders()
            hc.send(b"x" * (1 << 20))
            uo = []
            for _i in range(50):
                uo = [o for o in ops(a) if o["kind"] == "upload" and o["name"] == "lang.bin" and o["state"] == "running" and o["done"]]
                if uo:
                    break
                time.sleep(0.1)
            st_c = a.req("/api/transfers/ctl", {"id": uo[0]["id"], "action": "cancel"})[0] if uo else 0
            try:
                hc.send(b"x" * (1 << 20))
                rs = hc.getresponse().status
            except OSError:
                rs = 0
            hc.close()
            time.sleep(0.3)
            check("transfers: an upload cancelled from the list (409, no file, no partial file)", st_c == 200 and rs in (409, 0)
                  and not os.path.exists(g0 + "/lang.bin") and not os.path.exists(g0 + "/.lang.bin.untrash-upload")
                  and [o for o in ops(a) if o["id"] == uo[0]["id"]][0]["state"] == "cancelled")
            st, _ = a.req("/api/transfers/ctl", {"id": "", "action": "dismiss"})
            check("transfers: finished ones leave the list", st == 200 and not [o for o in ops(a) if o["state"] in ("done", "errors", "cancelled")])
            check("transfers: the download service is only for admins", u.req("/api/transfers/ctl", {"id": "dl:0123456789abcdef", "action": "pause"})[0] == 403)
            os.unlink(g0 + "/gross.bin")
            os.unlink(g0 + "/fm/p.jpg")
            shutil.rmtree(mx + "/fm")
            shutil.rmtree(mx + "/recycle")
            # media viewer: inline only for media types, sandboxed, with Range
            open(r + "/i-data/aaaa0001/mixed/bild.jpg", "wb").write(b"\xff\xd8\xff" + bytes(range(256)) * 4)
            open(r + "/i-data/aaaa0001/mixed/boese.html", "w").write("<script>alert(1)</script>")

            def raw(path, hdrs=None):
                rq = urllib.request.Request(a.base + path, headers=hdrs or {})
                try:
                    with a.op.open(rq) as resp:
                        return resp.status, dict(resp.headers), resp.read()
                except urllib.error.HTTPError as e:
                    return e.code, dict(e.headers), e.read()
            st, hd, body = raw("/api/files/download?share=mixed&path=bild.jpg&inline=1")
            check("inline image: image/jpeg, inline, CSP sandbox", st == 200 and hd["Content-Type"] == "image/jpeg" and
                  hd["Content-Disposition"].startswith("inline") and hd["Content-Security-Policy"].startswith("sandbox"))
            st, hd, body = raw("/api/files/download?share=mixed&path=boese.html&inline=1")
            check("inline HTML refused (download as octet-stream)", hd["Content-Type"] == "application/octet-stream" and
                  hd["Content-Disposition"].startswith("attachment"))
            st, hd, body = raw("/api/files/download?share=mixed&path=bild.jpg&inline=1", {"Range": "bytes=3-6"})
            check("range request 206", st == 206 and body == bytes([0, 1, 2, 3]) and hd["Content-Range"] == "bytes 3-6/1027")
            check("share root cannot be deleted", a.req("/api/files/op", {"op": "delete", "share": "mixed", "path": ""})[0] == 400)
            # settings
            check("bad hostname refused", a.req("/api/settings", {"hostname": "bad name!"})[0] == 400)
            check("bad static address refused", a.req("/api/settings", {"network": {"eth0": {"mode": "static", "address": "10.0.0.5"}}})[0] == 400)
            st, _ = a.req("/api/settings", {"hostname": "nas-neu", "netbios": {"name": "NASNEU", "workgroup": "WG", "description": "x"},
                                            "time": {"timezone": "Europe/Vienna", "ntp": True, "ntp_server": "pool.ntp.org"},
                                            "services": {"ssh": {"active": True, "port": 2200}, "time_machine": {"active": True, "share": "mixed"}},
                                            "power": {"spindown_min": 20}})
            s3 = json.load(open(r + "/etc/untrash/settings.json"))
            check("settings saved", st == 200 and s3["hostname"] == "nas-neu" and s3["time"]["timezone"] == "Europe/Vienna" and
                  s3["services"]["ssh"] == {"active": True, "port": 2200, "sftp": False} and s3["power"]["spindown_min"] == 20)
            st, _ = a.req("/api/settings", {"services": {"webdav": {"active": True, "anonymous": False},
                                                         "dyndns": {"active": True, "provider": "duckdns", "hostname": "x.duckdns.org",
                                                                    "username": "u", "password": "geheim-dd"},
                                                         "ups": {"active": True, "min_capacity": 20},
                                                         "syslog_server": {"active": True, "share": "mixed", "folder": "logs", "format": "full", "months": 3}},
                                            "notify": {"mail": {"active": True, "server": "smtp.example.net", "port": 587, "auth": True,
                                                                "username": "m", "password": "geheim-mail", "alerts_to": "a@example.net",
                                                                "log_to": "l@example.net", "alerts": True, "schedule": "weekly", "day": 2,
                                                                "hour": 4, "minute": 5},
                                                       "syslog": {"active": True, "server": "10.0.0.9", "port": 514}}})
            s5 = json.load(open(r + "/etc/untrash/settings.json"))
            check("new services saved (webdav, dyndns, ups, syslog server path from share, mail, syslog)", st == 200 and
                  s5["services"]["webdav"]["active"] and s5["services"]["dyndns"]["password"] == "geheim-dd" and
                  s5["services"]["ups"]["min_capacity"] == 20 and s5["services"]["syslog_server"]["path"].endswith("/mixed/logs/") and
                  s5["notify"]["mail"]["password"] == "geheim-mail" and s5["notify"]["mail"]["day"] == 2 and
                  s5["notify"]["syslog"]["server"] == "10.0.0.9")
            g5 = a.req("/api/settings")[1]
            check("passwords never sent back", g5["services"]["dyndns"]["password"] == "" and g5["notify"]["mail"]["password"] == ""
                  and g5["notify"]["mail"]["password_set"] and "geheim" not in json.dumps(g5))
            a.req("/api/settings", {"notify": {"mail": dict(g5["notify"]["mail"], password="")}})
            check("empty password keeps the stored one", json.load(open(r + "/etc/untrash/settings.json"))["notify"]["mail"]["password"] == "geheim-mail")
            check("bad mail address refused", a.req("/api/settings", {"notify": {"mail": {"active": True, "server": "s", "alerts_to": "kein-at"}}})[0] == 400)
            check("unknown dyndns provider refused", a.req("/api/settings", {"services": {"dyndns": {"active": True, "provider": "x", "hostname": "h"}}})[0] == 400)
            check("test mail endpoint", a.req("/api/notify/test", {})[0] == 200)
            # web publishing (stock /MyWeb), link aggregation, printers
            pubc = Client(port)
            check("MyWeb off -> 404", pubc.req("/MyWeb/mixed/readme.txt")[0] == 404)
            a.req("/api/settings", {"services": {"webpublish": {"active": True, "port": 80}}})
            check("MyWeb on, share not published -> 404", pubc.req("/MyWeb/mixed/readme.txt")[0] == 404)
            check("share flag web_public", a.req("/api/shares/save", {"name": "mixed", "web_public": True})[0] == 200 and
                  any(x["web_public"] for x in a.req("/api/shares")[1]["shares"] if x["name"] == "mixed"))
            rq = urllib.request.Request(pubc.base + "/myweb/MIXED/readme.txt")
            with urllib.request.urlopen(rq) as resp:
                csp, body = resp.headers.get("Content-Security-Policy", ""), resp.read()
            check("MyWeb serves the file without login (case-insensitive), CSP sandbox", body == b"hallo\n" and
                  csp.startswith("sandbox") and "allow-same-origin" not in csp)
            check("MyWeb directory listing", b"readme.txt" in pubc.req("/MyWeb/mixed/")[1])
            check("MyWeb traversal refused", pubc.req("/MyWeb/mixed/../../../../etc/passwd")[0] in (403, 404))
            check("MyWeb is read-only", pubc.req("/MyWeb/mixed/x.txt", raw=b"x")[0] != 200)
            check("web publishing port 5002 refused", a.req("/api/settings", {"services": {"webpublish": {"active": True, "port": 5002}}})[0] == 400)
            check("bond static without address refused", a.req("/api/settings", {"network": {"bond": {"active": True, "mode": 4, "mode_ip": "static", "address": "x"}}})[0] == 400)
            st, _ = a.req("/api/settings", {"network": {"bond": {"active": True, "mode": 1, "mode_ip": "dhcp"}}})
            check("bond saved", st == 200 and json.load(open(r + "/etc/untrash/settings.json"))["network"]["bond"]["active"])
            os.makedirs(r + "/var/lib/untrash", exist_ok=True)
            json.dump({"ABC": {"name": "Laser_1", "model": "HP X", "status": "on-line"}}, open(r + "/var/lib/untrash/printers.json", "w"))
            check("printers listed", a.req("/api/printers")[1]["printers"][0]["name"] == "Laser_1")
            check("cancel unknown printer refused", a.req("/api/printers/cancel", {"name": "x"})[0] == 400)
            check("cancel jobs", a.req("/api/printers/cancel", {"name": "Laser_1"})[0] == 200)
            # cloud apps (untrash-cloud test double; the real tool: test-cloud-host.py)
            st, cj = a.req("/api/cloud")
            check("cloud state: accounts, jobs, shares", st == 200 and cj["remotes"][0]["name"] == "Box" and "mixed" in cj["shares"])
            check("cloud auth-start returns the login page", a.req("/api/cloud/auth-start", {"provider": "dropbox"})[1]["url"].startswith("https://"))
            st, er = a.req("/api/cloud/auth-finish", {"name": "B2", "url": "http://x/"})
            check("cloud auth-finish error passed on", st == 400 and "return address" in er["error"])
            check("cloud job with unknown account refused", a.req("/api/cloud/jobs", {"jobs": [{"name": "x", "remote": "Nope", "share": "mixed", "direction": "both"}]})[0] == 400)
            check("cloud job path traversal refused", a.req("/api/cloud/jobs", {"jobs": [{"name": "x", "remote": "Box", "share": "mixed", "folder": "../..", "direction": "both"}]})[0] == 400)
            st, jj = a.req("/api/cloud/jobs", {"jobs": [{"name": "Sync", "remote": "Box", "share": "mixed", "folder": "Dropbox", "direction": "both", "interval_min": 1, "active": True}]})
            j0 = jj["jobs"][0] if st == 200 else {}
            check("cloud job saved: local path from share, interval >= 5", st == 200 and j0["local"].endswith("/mixed/Dropbox")
                  and j0["interval_min"] == 5 and json.load(open(r + "/etc/untrash/settings.json"))["cloud"]["jobs"][0]["id"] == j0["id"])
            check("cloud delete of a used account refused", a.req("/api/cloud/delete", {"name": "Box"})[0] == 400)
            check("cloud run now", a.req("/api/cloud/run", {"id": j0.get("id")})[0] == 200)
            # download service (aria2 JSON-RPC simulated; secret checked)
            import http.server
            import threading
            calls = []

            class Aria(http.server.BaseHTTPRequestHandler):
                def log_message(self, *x):
                    pass

                def do_POST(self):
                    req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    calls.append(req)
                    ok = req["params"][0] == "token:" + open(r + "/etc/untrash/aria2.secret").read().strip()
                    m = req["method"]
                    res = {"aria2.tellActive": [{"gid": "0123456789abcdef", "status": "active", "totalLength": "1000",
                                                 "completedLength": "250", "downloadSpeed": "10", "uploadSpeed": "0",
                                                 "files": [{"path": "/x/ubuntu.iso"}], "dir": "/x"}],
                           "aria2.tellWaiting": [], "aria2.tellStopped": []}.get(m, "OK")
                    body = json.dumps({"id": req["id"], "result": res} if ok else {"id": req["id"], "error": {"message": "Unauthorized"}}).encode()
                    self.send_response(200 if ok else 400)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
            asrv = http.server.HTTPServer(("127.0.0.1", port + 500), Aria)
            threading.Thread(target=asrv.serve_forever, daemon=True).start()
            os.makedirs(r + "/etc/untrash", exist_ok=True)
            open(r + "/etc/untrash/aria2.secret", "w").write("s3cr3t\n")
            check("downloads off: no RPC", a.req("/api/downloads")[1]["running"] is False and not calls)
            check("download settings: bad period refused", a.req("/api/settings", {"services": {"download": {"active": True, "period": "25:00"}}})[0] == 400)
            st, _ = a.req("/api/settings", {"services": {"download": {"active": True, "share": "mixed", "folder": "../dl", "slots": 50, "period": "0100:0700"}}})
            dd = json.load(open(r + "/etc/untrash/settings.json"))["services"]["download"]
            check("download settings saved (folder sanitized, slots <= 10)", st == 200 and dd["folder"] == "dl" and dd["slots"] == 10 and dd["period"] == "0100:0700")
            st, dl = a.req("/api/downloads")
            check("downloads listed via RPC with secret", st == 200 and dl["running"] and dl["items"][0]["name"] == "ubuntu.iso" and dl["items"][0]["done"] == 250)
            check("bad download address refused", a.req("/api/downloads/add", {"url": "file:///etc/passwd"})[0] == 400)
            check("magnet added", a.req("/api/downloads/add", {"url": "magnet:?xt=urn:btih:abc"})[0] == 200 and calls[-1]["method"] == "aria2.addUri")
            check("torrent upload", a.req("/api/downloads/torrent", raw=b"d4:infod4:name1:xee")[0] == 200 and calls[-1]["method"] == "aria2.addTorrent")
            check("not a torrent refused", a.req("/api/downloads/torrent", raw=b"<html>")[0] == 400)
            check("pause / remove", a.req("/api/downloads/ctl", {"gid": "0123456789abcdef", "action": "pause"})[0] == 200 and
                  a.req("/api/downloads/ctl", {"gid": "0123456789abcdef", "action": "remove"})[0] == 200 and calls[-1]["method"] == "aria2.removeDownloadResult")
            check("bad gid refused", a.req("/api/downloads/ctl", {"gid": "../x", "action": "pause"})[0] == 400)
            asrv.shutdown()
            # COPY/SYNC button
            check("copybtn: same share as backup refused", a.req("/api/settings", {"copybtn": {"copy": {"share": "mixed", "bak_share": "mixed", "direction": "cp2Vol"}}})[0] == 400)
            st, _ = a.req("/api/settings", {"copybtn": {"copy": {"share": "mixed", "bak_share": "", "direction": "cp2Vol", "newdir": True},
                                                        "sync": {"share": "mixed", "bak_share": "admin", "direction": "twoWay"}}})
            cb = json.load(open(r + "/etc/untrash/settings.json"))["copybtn"]
            check("copybtn saved as stock paths", st == 200 and cb["copy"]["share_path"].endswith("/mixed") and cb["copy"]["newdir"]
                  and cb["sync"]["bak_path"].endswith("/admin") and cb["sync"]["direction"] == "twoWay")
            # Backup Planner (real untrash-backup + rsync on the test root)
            check("backup: target inside the source refused", a.req("/api/backup/jobs", {"jobs": [{"name": "x", "type": "archive",
                  "sources": [{"share": "mixed"}], "target": {"kind": "local", "share": "mixed", "folder": "sub"}}]})[0] == 400)
            check("backup: rsync without host refused", a.req("/api/backup/jobs", {"jobs": [{"name": "x", "type": "rsync",
                  "sources": [{"share": "mixed"}], "target": {"host": "", "module": "m"}}]})[0] == 400)
            st, bj = a.req("/api/backup/jobs", {"jobs": [{"name": "Mixed", "type": "archive", "sources": [{"share": "mixed"}],
                                                          "target": {"kind": "local", "share": "admin", "folder": "../Sicherung"},
                                                          "keep": 3, "schedule": {"kind": "daily", "hour": 3}, "active": True},
                                                         {"name": "Fern", "type": "rsync", "sources": [{"share": "mixed"}],
                                                          "target": {"host": "nas2.local", "module": "backup", "user": "u"}, "password": "rs-pw"}]})
            bid = bj["jobs"][0]["id"] if st == 200 else ""
            rid = bj["jobs"][1]["id"] if st == 200 else ""
            check("backup jobs saved (folder sanitized, rsync password 0600 outside settings)", st == 200 and
                  bj["jobs"][0]["target"]["path"].endswith("/Sicherung") and ".." not in bj["jobs"][0]["target"]["path"] and
                  open(r + "/etc/untrash/backup-secrets/" + rid).read() == "rs-pw" and
                  os.stat(r + "/etc/untrash/backup-secrets/" + rid).st_mode & 0o777 == 0o600 and
                  "rs-pw" not in open(r + "/etc/untrash/settings.json").read())
            check("backup run now", a.req("/api/backup/run", {"id": bid})[0] == 200)
            for _ in range(50):
                vv = a.req("/api/backup/versions?id=" + bid)[1].get("versions", [])
                if vv:
                    break
                time.sleep(0.2)
            check("backup version listed", len(vv) == 1)
            st, _ = a.req("/api/backup/restore", {"id": bid, "version": vv[0] if vv else "", "share": "mixed", "folder": "restored"})
            check("backup restore into a share folder", st == 200 and os.path.isfile(r + "/i-data/aaaa0001/mixed/restored/mixed/readme.txt"))
            check("backup state", a.req("/api/backup")[1]["status"][bid]["ok"])
            # user quota (stock: per volume, GB)
            st, qj = a.req("/api/users/quota?name=alice")
            check("quota: internal volumes listed", st == 200 and {x["volume"] for x in qj["quotas"]} == {"aaaa0001", "sysvol-real"})
            check("quota: unknown volume refused", a.req("/api/users/quota", {"name": "alice", "quotas": {"zzz": 5}})[0] == 400)
            check("quota: too big refused", a.req("/api/users/quota", {"name": "alice", "quotas": {"aaaa0001": 99999}})[0] == 400)
            check("quota set", a.req("/api/users/quota", {"name": "alice", "quotas": {"aaaa0001": 50}})[0] == 200)
            check("quota: alice may not", u.req("/api/users/quota?name=alice")[0] == 403)
            # certificate + HTTPS
            check("no certificate yet", a.req("/api/cert")[1] == {"present": False})
            check("https without certificate refused", a.req("/api/settings", {"services": {"https": {"active": True}}})[0] == 400)
            st, ci = a.req("/api/cert/regenerate", {"cn": "nas-neu"})
            check("self-signed certificate made", st == 200 and ci["present"] and ci["self_signed"] and "nas-neu" in ci["subject"]
                  and os.stat(r + "/etc/untrash/tls/untrash.key").st_mode & 0o777 == 0o600)
            other = os.path.join(w, "other")
            os.makedirs(other)
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=own.example",
                            "-keyout", other + "/k", "-out", other + "/c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            check("upload: key of another certificate refused", a.req("/api/cert/upload", {"cert": open(other + "/c").read(),
                  "key": open(r + "/etc/untrash/tls/untrash.key").read()})[0] == 400 and "nas-neu" in a.req("/api/cert")[1]["subject"])
            st, ci = a.req("/api/cert/upload", {"cert": open(other + "/c").read(), "key": open(other + "/k").read()})
            check("upload own certificate", st == 200 and "own.example" in ci["subject"])
            check("https + force saved", a.req("/api/settings", {"services": {"https": {"active": True, "port": 443, "force": True}}})[0] == 200
                  and json.load(open(r + "/etc/untrash/settings.json"))["services"]["https"] == {"active": True, "port": 443, "force": True})
            # UPnP
            st, uj = a.req("/api/upnp")
            check("upnp state: router + external address", st == 200 and uj["external_ip"] == "203.0.113.5" and "HTTP" in uj["names"])
            check("upnp: duplicate WAN port refused", a.req("/api/upnp", {"services": {"HTTP": 8000, "FTP": 8000}})[0] == 400)
            check("upnp: unknown service refused", a.req("/api/upnp", {"services": {"CIFS": 445}})[0] == 400)
            check("upnp saved", a.req("/api/upnp", {"services": {"HTTP": 8000}})[0] == 200 and
                  json.load(open(r + "/etc/untrash/settings.json"))["upnp"]["services"] == {"HTTP": 8000})
            # iSCSI (LUN files real, LIO only on the NAS: test-iscsi-host.py)
            check("iscsi: no LUN yet", a.req("/api/iscsi")[1]["luns"] == [])
            check("iscsi: LUN on unknown volume refused", a.req("/api/iscsi/lun", {"name": "l1", "volume": "x", "size_gb": 1})[0] == 400)
            st, _ = a.req("/api/iscsi/lun", {"name": "l1", "volume": "aaaa0001", "size_gb": 2, "thin": True})
            check("iscsi: thin LUN file made", st == 200 and os.path.getsize(r + "/i-data/aaaa0001/.iscsi_Lun/l1") == 2 << 30)
            check("iscsi: duplicate LUN name refused", a.req("/api/iscsi/lun", {"name": "L1", "volume": "aaaa0001", "size_gb": 1})[0] == 400)
            check("iscsi: short CHAP password refused", a.req("/api/iscsi/targets", {"targets": [{"name": "t1", "luns": ["l1"], "chap": True,
                  "chap_user": "u", "chap_password": "kurz"}]})[0] == 400)
            st, tj = a.req("/api/iscsi/targets", {"targets": [{"name": "t1", "luns": ["l1"], "chap": True, "chap_user": "u",
                                                               "chap_password": "geheim-12345", "initiators": ["iqn.1991-05.com.microsoft:pc"]}]})
            sec = json.load(open(r + "/etc/untrash/iscsi-secrets.json"))
            iqn = tj["targets"][0]["iqn"] if st == 200 else ""
            check("iscsi target saved: IQN from the name, CHAP secret 0600 outside settings", st == 200 and iqn.startswith("iqn.2026-10.local.untrash:")
                  and sec[iqn]["password"] == "geheim-12345" and os.stat(r + "/etc/untrash/iscsi-secrets.json").st_mode & 0o777 == 0o600
                  and "geheim-12345" not in json.dumps(a.req("/api/iscsi")[1]))
            a.req("/api/iscsi/targets", {"targets": [{"name": "t1", "iqn": iqn, "luns": ["l1"], "chap": True, "chap_user": "u"}]})
            check("iscsi: empty password keeps the secret", json.load(open(r + "/etc/untrash/iscsi-secrets.json"))[iqn]["password"] == "geheim-12345")
            check("iscsi: LUN in a target cannot be deleted", a.req("/api/iscsi/lun-delete", {"name": "l1", "confirm": "DELETE"})[0] == 400)
            a.req("/api/iscsi/targets", {"targets": []})
            check("iscsi: LUN delete needs DELETE, then gone", a.req("/api/iscsi/lun-delete", {"name": "l1"})[0] == 400 and
                  a.req("/api/iscsi/lun-delete", {"name": "l1", "confirm": "DELETE"})[0] == 200 and not os.path.exists(r + "/i-data/aaaa0001/.iscsi_Lun/l1"))
            # power: power-loss mode, WoL, schedule
            check("power: bad mode refused", a.req("/api/settings", {"power": {"pwron": "maybe"}})[0] == 400)
            check("power: bad time refused", a.req("/api/settings", {"power": {"schedule": [{"action": "on", "kind": "daily", "hour": 25}]}})[0] == 400)
            st, _ = a.req("/api/settings", {"power": {"pwron": "never", "wol": True, "schedule_active": True,
                                                      "schedule": [{"action": "on", "kind": "weekly", "day": 2, "hour": 7, "minute": 5},
                                                                   {"action": "off", "kind": "monthly", "mday": 40, "hour": 22, "minute": 0}]}})
            pj = json.load(open(r + "/etc/untrash/settings.json"))["power"]
            check("power saved (mday clamped to 28)", st == 200 and pj["pwron"] == "never" and pj["wol"] and pj["schedule"][1]["mday"] == 28)
            if BOARD:
                check("power next", a.req("/api/power/next")[1]["on"].endswith("07:05"))
            check("copybtn run now", a.req("/api/copybtn/run", {"kind": "copy"})[0] == 200 and a.req("/api/copybtn/run", {"kind": "x"})[0] == 400)
            check("unknown timezone refused", a.req("/api/settings", {"time": {"timezone": "Mars/Base", "ntp": False, "ntp_server": "x"}})[0] == 400)
            check("time zones listed", "Europe/Berlin" in a.req("/api/timezones")[1]["zones"])
            # appearance per user (design/theme.js): defaults, saved per user, validated
            check("theme.js served", a.req("/ut/theme.js")[0] == 200 and b"theme.js" in a.req("/")[1])
            check("prefs default dark/none/auto", a.req("/api/me")[1]["prefs"] == {"theme": "dark", "cvd": "none", "motion": "auto"})
            st, pj = u.req("/api/prefs", {"theme": "light", "cvd": "deutan"})
            check("prefs saved for alice", st == 200 and u.req("/api/me")[1]["prefs"] == {"theme": "light", "cvd": "deutan", "motion": "auto"})
            check("prefs of admin untouched", a.req("/api/me")[1]["prefs"]["theme"] == "dark")
            check("prefs: unknown value refused", u.req("/api/prefs", {"theme": "neon"})[0] == 400 and u.req("/api/prefs", {"font": "x"})[0] == 400)
            check("prefs: anonymous refused", Client(port).req("/api/prefs", {"theme": "light"})[0] == 401)
            # UntrashMesh (untrash-mesh: test-mesh-host.py has the network part)
            st, mj = a.req("/api/mesh")
            check("mesh: status without a mesh", st == 200 and mj["mesh"] is None and len(mj["node"]) == 16)
            check("mesh: users get 403", u.req("/api/mesh")[0] == 403 and u.req("/api/mesh/create", {"name": "x"})[0] == 403)
            check("mesh: bad name refused", a.req("/api/mesh/create", {"name": "<script>"})[0] == 400)
            st, mj = a.req("/api/mesh/create", {"name": "home"})
            check("mesh: created, this NAS is admin with a mesh address", st == 200 and mj["mesh"]["name"] == "home" and mj["admin"] and mj["address"].startswith("fd"))
            st, ij = a.req("/api/mesh/invite", {"hours": 24})
            check("mesh: invitation text", st == 200 and len(ij["invitation"]) > 40)
            check("mesh: bad invitation hours refused", a.req("/api/mesh/invite", {"hours": 999})[0] == 400)
            check("mesh: join while in a mesh refused", a.req("/api/mesh/join", {"invitation": ij["invitation"]})[0] == 400)
            check("mesh: not an invitation refused", a.req("/api/mesh/join", {"invitation": "x y z"})[0] == 400)
            st, mj = a.req("/api/mesh/rename", {"name": "keller"})
            check("mesh: renamed", st == 200 and mj["name"] == "keller")
            check("co-op: unknown member refused", a.req("/api/mesh/share", {"node": "x", "shares": {}})[0] == 400)
            check("co-op: unknown share refused", a.req("/api/mesh/share", {"node": "0" * 16, "shares": {"nope": "ro"}})[0] == 400)
            check("co-op: bad right refused", a.req("/api/mesh/share", {"node": "0" * 16, "shares": {"mixed": "admin"}})[0] == 400)
            # off-site mirror (test-mesh-host.py has the DRBD part)
            check("mirror: volumes say which one holds the running system", all(v.get("host") is False for v in a.req("/api/storage")[1]["volumes"] if v["kind"] == "intern"))
            check("mirror: unknown member refused", a.req("/api/mesh/mirror-start", {"volume": "aaaa0001", "node": "x"})[0] == 400)
            check("mirror: unknown volume refused", a.req("/api/mesh/mirror-start", {"volume": "nope", "node": "0" * 16})[0] == 400)
            st, mj = a.req("/api/mesh/mirror-start", {"volume": "aaaa0001", "node": "0" * 16})
            check("mirror: untrash-mesh refusal reaches the Desk", st == 400 and mj.get("error"))
            check("mirror: bad mirror id refused", a.req("/api/mesh/mirror-stop", {"id": "../x"})[0] == 400
                  and a.req("/api/mesh/mirror-accept", {"id": "zz", "volume": "aaaa0001"})[0] == 400)
            check("mirror: unknown mirror refused", a.req("/api/mesh/mirror-decline", {"id": "0" * 8})[0] == 400)
            check("mirror: users get 403", u.req("/api/mesh/mirror-stop", {"id": "0" * 8})[0] == 403)
            st, mj = a.req("/api/mesh")
            check("mirror: status lists mirrors and copies", st == 200 and mj["mirrors"] == [] and mj["mirror_copies"] == [])
            # a mounted partner volume (as untrash-mesh reports it) is a volume; a share can live on it
            os.makedirs(r + "/p-data/nas-b-Photos", exist_ok=True)
            json.dump({r + "/p-data/nas-b-Photos": {"node": "f" * 16, "partner": "nas-b", "share": "Photos", "mode": "rw", "online": True,
                                                    "mounted": True, "size": 4 * 10 ** 12, "free": 10 ** 12}},
                      open(r + "/etc/untrash/mesh/volumes.json", "w"))
            vols = a.req("/api/shares")[1]["volumes"]
            pv = [v for v in vols if v["kind"] == "partner"]
            check("co-op: partner volume listed with the partner's numbers", pv and pv[0]["id"] == "p:nas-b-Photos" and pv[0]["free"] == 10 ** 12
                  and pv[0]["label"] == "Photos @ nas-b")
            st, _ = a.req("/api/shares/save", {"new": True, "name": "VonB", "volume": "p:nas-b-Photos", "users": {"admin": "rw"}})
            check("co-op: share made on the partner volume", st == 200 and any(x["name"] == "VonB" and x["path"] == "/p-data/nas-b-Photos/VonB"
                                                                              for x in a.req("/api/shares")[1]["shares"]))
            a.req("/api/shares/delete", {"name": "VonB"})
            # Files: admins open partner volumes directly ("mesh:<partner>-<share>"), users do not see them
            st, fl = a.req("/api/files?share=mesh:nas-b-Photos&path=")
            check("files: admin lists the partner volume directly", st == 200 and "VonB" in [e["name"] for e in fl["entries"]])
            st, _ = a.req("/api/files/upload?share=mesh:nas-b-Photos&path=&name=aus-dem-mesh.txt", raw=b"mesh")
            check("files: admin writes to a read/write partner volume", st == 200 and open(r + "/p-data/nas-b-Photos/aus-dem-mesh.txt").read() == "mesh")
            check("files: users do not get partner volumes", u.req("/api/files?share=mesh:nas-b-Photos&path=")[0] == 403
                  and not any(x["name"].startswith("mesh:") for x in u.req("/api/shares")[1]["shares"]))
            vj = json.load(open(r + "/etc/untrash/mesh/volumes.json"))
            vj[r + "/p-data/nas-b-Photos"]["mode"] = "ro"
            json.dump(vj, open(r + "/etc/untrash/mesh/volumes.json", "w"))
            check("files: a read-only partner volume refuses writes", a.req("/api/files/op", {"op": "mkdir", "share": "mesh:nas-b-Photos", "path": "", "name": "x"})[0] == 403)
            vj[r + "/p-data/nas-b-Photos"]["mode"] = "rw"
            json.dump(vj, open(r + "/etc/untrash/mesh/volumes.json", "w"))

            # UntrashApp (docs/architecture/app-api.md): pairing, signed requests, sign-in, confirmations
            sig = os.path.join(r, "zt-sig")
            def app_key(n):
                sec, pub = os.path.join(r, n + ".sec"), os.path.join(r, n + ".pub")
                subprocess.run([sig, "keygen", sec, pub], check=True)
                pk = open(pub, "rb").read().hex()
                return {"sec": sec, "pub": pk, "node": hashlib.sha256(bytes.fromhex(pk)).hexdigest()[:16]}
            def app_req(k, method, path, body=None, ts=None, nonce=None, tamper=False):
                raw = json.dumps(body).encode() if body is not None else b""
                ts, nonce = str(int(ts or time.time())), nonce or os.urandom(12).hex()
                msg = "\n".join(["UTAPP1", method, path, ts, nonce, hashlib.sha256(raw + (b" " if tamper else b"")).hexdigest()]).encode()
                mf, sf = os.path.join(r, "appmsg"), os.path.join(r, "appsig")
                open(mf, "wb").write(msg)
                subprocess.run([sig, "sign", k["sec"], mf, sf], check=True)
                rq = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=raw if method == "POST" else None, method=method)
                rq.add_header("Authorization", "UntrashApp node=%s, ts=%s, nonce=%s, sig=%s" % (k["node"], ts, nonce, open(sf, "rb").read().hex()))
                try:
                    with urllib.request.urlopen(rq) as resp:
                        return resp.status, json.loads(resp.read())
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read() or b"{}")
            st, pj = a.req("/api/mesh/pair", {"user": "alice", "hours": 1})
            inv = json.loads(base64.urlsafe_b64decode(pj.get("invitation", "") + "=" * (-len(pj.get("invitation", "")) % 4)) or b"{}")
            mst = json.load(open(r + "/etc/untrash/mesh/mesh.json"))
            check("app: pairing invitation marked for the app, linked to alice", st == 200 and inv.get("k") == "app"
                  and any(i.get("app") == "alice" for i in mst["invites"].values()))
            check("app: pairing needs a known user", a.req("/api/mesh/pair", {"user": "nobody"})[0] == 404 and u.req("/api/mesh/pair", {"user": "alice"})[0] == 403)
            ka, kb = app_key("app-alice"), app_key("app-admin")
            for k, nm in ((ka, "alices-phone"), (kb, "admin-phone")):     # as untrash-mesh's join would add them
                mst["roster"]["members"][k["node"]] = {"pub": k["pub"], "wg": "x", "name": nm, "role": "member", "kind": "app", "added": 1}
            json.dump(mst, open(r + "/etc/untrash/mesh/mesh.json", "w"))
            st, mj = a.req("/api/mesh/app-link", {"node": ka["node"], "user": "alice"})
            check("app: linked to alice (shown in the mesh status)", st == 200 and any(x["node"] == ka["node"] and x["user"] == "alice" for x in mj["members"]))
            check("app: only app members can be linked", a.req("/api/mesh/app-link", {"node": mj["node"], "user": "alice"})[0] == 400)
            st, info = app_req(ka, "GET", "/api/app/info")
            check("app: signed request acts as alice", st == 200 and info["user"] == "alice" and info["api"] == 1 and not info["admin"])
            check("app: alice's app is no admin", app_req(ka, "GET", "/api/overview")[0] == 403)
            check("app: app endpoints refuse a browser session", u.req("/api/app/info")[0] == 403)
            check("app: an unlinked app is refused", app_req(kb, "GET", "/api/app/info")[0] == 401)
            check("app: a tampered body is refused", app_req(ka, "POST", "/api/app/answer", {"id": "x"}, tamper=True)[0] == 401)
            check("app: an old request is refused", app_req(ka, "GET", "/api/app/info", ts=time.time() - 600)[0] == 401)
            n1 = os.urandom(12).hex()
            check("app: a replayed nonce is refused", app_req(ka, "GET", "/api/app/info", nonce=n1)[0] == 200
                  and app_req(ka, "GET", "/api/app/info", nonce=n1)[0] == 401)
            check("app: uploads (streamed bodies) are not for the app in v1", app_req(ka, "POST", "/api/files/upload", {})[0] == 400)
            # sign-in without password: only once alice chose "password or app"
            b2 = Client(port)
            st, lj = b2.req("/api/login/app", {"user": "alice"})
            check("app login: request made, but alice (password only) does not see it", st == 200 and lj["code"] >= 10
                  and app_req(ka, "GET", "/api/app/requests")[1]["requests"] == [])
            check("app login: an unknown user gets the same answer", b2.req("/api/login/app", {"user": "nobody"})[0] == 200)
            check("app login: sign-in change needs the password", u.req("/api/signin", {"mode": "app", "password": "x"})[0] == 403)
            check("app login: alice chooses password or app", u.req("/api/signin", {"mode": "app", "password": PW})[1].get("signin") == "app")
            st, lj = b2.req("/api/login/app", {"user": "alice"})
            rq = app_req(ka, "GET", "/api/app/requests")[1]["requests"]
            check("app login: the app sees it with three numbers, one is the browser's", len(rq) == 1 and lj["code"] in rq[0]["choices"]
                  and len(set(rq[0]["choices"])) == 3 and rq[0]["kind"] == "login")
            wrong = next(c for c in rq[0]["choices"] if c != lj["code"])
            check("app login: the wrong number denies it", app_req(ka, "POST", "/api/app/answer", {"id": rq[0]["id"], "approve": True, "code": wrong})[1]["state"] == "denied"
                  and b2.req("/api/login/app?id=" + lj["id"])[1]["state"] == "denied" and b2.req("/api/me")[0] == 401)
            st, lj = b2.req("/api/login/app", {"user": "alice"})
            check("app login: pending until the app answers", b2.req("/api/login/app?id=" + lj["id"])[1]["state"] == "pending")
            rid = app_req(ka, "GET", "/api/app/requests")[1]["requests"][0]["id"]
            app_req(ka, "POST", "/api/app/answer", {"id": rid, "approve": True, "code": lj["code"]})
            check("app login: approved -> the browser is signed in as alice", b2.req("/api/login/app?id=" + lj["id"])[1]["state"] == "approved"
                  and b2.req("/api/me")[1].get("user") == "alice")
            check("app login: the approval works once", Client(port).req("/api/login/app?id=" + lj["id"])[1]["state"] == "used")
            # two factors: password, then the app
            u.req("/api/signin", {"mode": "both", "password": PW})
            b3 = Client(port)
            st, lj = b3.req("/api/login", {"user": "alice", "password": PW})
            check("2fa: the password alone gives no session", st == 200 and lj.get("second") and b3.req("/api/me")[0] == 401)
            check("2fa: sign-in without password no longer shown", b3.req("/api/login/app", {"user": "alice"})[0] == 200
                  and [x["kind"] for x in app_req(ka, "GET", "/api/app/requests")[1]["requests"]] == ["login2"])
            rid = app_req(ka, "GET", "/api/app/requests")[1]["requests"][0]["id"]
            app_req(ka, "POST", "/api/app/answer", {"id": rid, "approve": True, "code": lj["code"]})
            check("2fa: after the app the session is there", b3.req("/api/login/app?id=" + lj["second"])[1]["state"] == "approved"
                  and b3.req("/api/me")[1].get("user") == "alice")
            # confirmations: admin with two factors confirms resetting alice's sign-in in the app
            a.req("/api/mesh/app-link", {"node": kb["node"], "user": "admin"})
            check("confirm: admin sets two factors", a.req("/api/signin", {"mode": "both", "password": PW})[1].get("signin") == "both")
            st, cj = a.req("/api/users/signin", {"user": "alice", "mode": "password"})
            check("confirm: the action waits for the app (428)", st == 428 and cj.get("confirm") and cj["action"] == "Reset the sign-in of a user")
            rq = app_req(kb, "GET", "/api/app/requests")[1]["requests"]
            check("confirm: the app sees the action and the user", rq and rq[0]["kind"] == "confirm" and rq[0]["detail"] == "alice")
            app_req(kb, "POST", "/api/app/answer", {"id": rq[0]["id"], "approve": True, "code": cj["code"]})
            check("confirm: the browser sees the approval", a.req("/api/confirm?id=" + cj["confirm"])[1]["state"] == "approved")
            check("confirm: repeated with the confirmation it runs", a.req("/api/users/signin", {"user": "alice", "mode": "password", "confirm": cj["confirm"]})[0] == 200
                  and next(x for x in a.req("/api/users")[1]["users"] if x["name"] == "alice")["signin"] == "password")
            check("confirm: a confirmation is used once", a.req("/api/users/signin", {"user": "alice", "mode": "password", "confirm": cj["confirm"]})[0] == 428)
            check("confirm: it is bound to the user it named", a.req("/api/users/signin", {"user": "bob", "mode": "password", "confirm": cj["confirm"]})[0] == 428)
            check("confirm: the admin's app itself needs no extra confirmation", app_req(kb, "POST", "/api/users/signin", {"user": "alice", "mode": "password"})[0] == 200)
            check("confirm: the other app cannot answer admin's requests", app_req(ka, "POST", "/api/app/answer", {"id": rq[0]["id"], "approve": True, "code": cj["code"]})[0] == 404)
            a.req("/api/mesh/app-link", {"node": kb["node"], "user": ""})
            check("app: without a linked app the sign-in is the password again", a.req("/api/me")[1]["signin"] == "password"
                  and a.req("/api/users/signin", {"user": "alice", "mode": "password"})[0] == 200)
            st, mj = a.req("/api/mesh/leave", {})
            check("mesh: left", st == 200 and mj["mesh"] is None)
            # office bridge: a stand-in office server (discovery only); the test plays the editor (WOPI)
            import http.server
            import threading
            DISC = (b'<?xml version="1.0"?><wopi-discovery><net-zone name="external-http"><app name="writer">'
                    b'<action ext="odt" name="edit" urlsrc="https://office.test/browser/x/cool.html?&lt;ui=UI_LLCC&amp;&gt;"/>'
                    b'<action ext="txt" name="view" urlsrc="https://office.test/browser/x/cool.html?"/>'
                    b'<action ext="txt" name="edit" urlsrc="https://office.test/browser/x/cool.html?"/></app>'
                    b'<app name="Capabilities"><action ext="" name="getinfo" urlsrc="https://office.test/hosting/capabilities"/></app></net-zone></wopi-discovery>')
            class OfficeH(http.server.BaseHTTPRequestHandler):
                def do_GET(self):
                    self.send_response(200 if self.path == "/hosting/discovery" else 404)
                    self.send_header("Content-Type", "text/xml")
                    self.end_headers()
                    self.wfile.write(DISC)
                def log_message(self, *a):
                    pass
            osrv = http.server.HTTPServer(("127.0.0.1", 0), OfficeH)
            threading.Thread(target=osrv.serve_forever, daemon=True).start()
            office = "http://127.0.0.1:%d" % osrv.server_address[1]
            check("office: off by default, Files sees no types", a.req("/api/office")[1]["enabled"] is False and u.req("/api/office")[1]["exts"] == [])
            check("office: both addresses needed", a.req("/api/office/settings", {"server": office, "wopi_base": ""})[0] == 400
                  and a.req("/api/office/settings", {"server": "javascript:x", "wopi_base": "http://nas"})[0] == 400)
            check("office: users cannot set it", u.req("/api/office/settings", {"server": office, "wopi_base": "http://nas"})[0] == 403)
            st, oj = a.req("/api/office/settings", {"server": office, "wopi_base": "http://nas.test"})
            check("office: saved and checked (types from the discovery, edit over view)", st == 200 and oj["exts"] == ["odt", "txt"])
            check("office: users see the types, not the addresses", u.req("/api/office")[1] == {"enabled": True, "exts": ["odt", "txt"]})
            open(r + "/i-data/aaaa0001/mixed/brief.odt", "wb").write(b"ODT-1")
            check("office: no open for unknown types / missing files", a.req("/api/office/open", {"share": "mixed", "path": "readme.md"})[0] in (400, 404)
                  and a.req("/api/office/open", {"share": "mixed", "path": "nope.odt"})[0] == 404)
            check("office: no open without share rights (bob deny)", b.req("/api/office/open", {"share": "mixed", "path": "brief.odt"})[0] == 403)
            st, op = a.req("/api/office/open", {"share": "mixed", "path": "brief.odt", "lang": "de"})
            fid = re.search(r"WOPISrc=([^&]+)", op.get("url", ""))
            fid = urllib.parse.unquote(fid.group(1)).rsplit("/", 1)[1] if fid else ""
            check("office: editor URL with WOPISrc on the NAS address, placeholders removed", st == 200 and op["url"].startswith("https://office.test/browser/x/cool.html?")
                  and "WOPISrc=http%3A%2F%2Fnas.test%2Fwopi%2Ffiles%2F" in op["url"] and "UI_LLCC" not in op["url"] and "lang=de" in op["url"]
                  and op["action"] == "edit" and op["access_token_ttl"] > time.time() * 1000)
            def wopi(method, path, token, body=None, hdrs=None):
                rq = urllib.request.Request("http://127.0.0.1:%d/wopi/files/%s?access_token=%s" % (port, path, urllib.parse.quote(token)),
                                            data=body, method=method)
                for k, v in (hdrs or {}).items():
                    rq.add_header(k, v)
                try:
                    with urllib.request.urlopen(rq) as resp:
                        return resp.status, resp.read(), resp.headers
                except urllib.error.HTTPError as e:
                    return e.code, e.read(), e.headers
            tk = op["access_token"]
            st, info, _h = wopi("GET", fid, tk)
            info = json.loads(info) if st == 200 else {}
            check("wopi: CheckFileInfo (name, size, admin may write, locks)", info.get("BaseFileName") == "brief.odt" and info.get("Size") == 5
                  and info.get("UserCanWrite") is True and info.get("SupportsLocks") is True and info.get("UserId") == "admin")
            check("wopi: GetFile", wopi("GET", fid + "/contents", tk)[1] == b"ODT-1")
            check("wopi: a wrong token is refused", wopi("GET", fid, tk[:-2] + ("00" if not tk.endswith("00") else "11"))[0] == 401)
            check("wopi: the token is bound to its file", wopi("GET", "0" * 32, tk)[0] == 401)
            check("wopi: PutFile without any lock saves (editors that never lock)",
                  wopi("POST", fid + "/contents", tk, b"ODT-1", {"X-WOPI-Override": "PUT"})[0] == 200)
            check("wopi: Lock", wopi("POST", fid, tk, b"", {"X-WOPI-Override": "LOCK", "X-WOPI-Lock": "L1"})[0] == 200)
            st, _b, h = wopi("POST", fid, tk, b"", {"X-WOPI-Override": "LOCK", "X-WOPI-Lock": "L2"})
            check("wopi: a second lock conflicts and names the current one", st == 409 and h.get("X-WOPI-Lock") == "L1")
            check("wopi: GetLock", wopi("POST", fid, tk, b"", {"X-WOPI-Override": "GET_LOCK"})[2].get("X-WOPI-Lock") == "L1")
            check("wopi: PutFile with the wrong lock refused", wopi("POST", fid + "/contents", tk, b"BAD", {"X-WOPI-Override": "PUT", "X-WOPI-Lock": "L2"})[0] == 409
                  and open(r + "/i-data/aaaa0001/mixed/brief.odt", "rb").read() == b"ODT-1")
            st, _b, h = wopi("POST", fid + "/contents", tk, b"ODT-2 saved", {"X-WOPI-Override": "PUT", "X-WOPI-Lock": "L1"})
            check("wopi: PutFile with the lock saves the file (new version, LastModifiedTime for Collabora)", st == 200 and json.loads(_b).get("LastModifiedTime", "").endswith("Z") and open(r + "/i-data/aaaa0001/mixed/brief.odt", "rb").read() == b"ODT-2 saved"
                  and h.get("X-WOPI-ItemVersion") and not [x for x in os.listdir(r + "/i-data/aaaa0001/mixed") if "untrash-office" in x])
            check("wopi: UnlockAndRelock", wopi("POST", fid, tk, b"", {"X-WOPI-Override": "LOCK", "X-WOPI-Lock": "L3", "X-WOPI-OldLock": "L1"})[0] == 200)
            check("wopi: RefreshLock / Unlock", wopi("POST", fid, tk, b"", {"X-WOPI-Override": "REFRESH_LOCK", "X-WOPI-Lock": "L3"})[0] == 200
                  and wopi("POST", fid, tk, b"", {"X-WOPI-Override": "UNLOCK", "X-WOPI-Lock": "L3"})[0] == 200
                  and wopi("POST", fid, tk, b"", {"X-WOPI-Override": "GET_LOCK"})[2].get("X-WOPI-Lock") == "")
            check("wopi: RenameFile not supported (501)", wopi("POST", fid, tk, b"", {"X-WOPI-Override": "RENAME_FILE"})[0] == 501)
            st, opu = u.req("/api/office/open", {"share": "mixed", "path": "brief.odt"})
            st2, iu, _h = wopi("GET", fid, opu.get("access_token", ""))
            check("wopi: alice (read only on mixed) gets the same file id, may not write", st == 200 and st2 == 200 and json.loads(iu)["UserCanWrite"] is False
                  and opu["url"] == op["url"].replace("lang=de", "lang=en"))
            check("wopi: alice's token cannot lock or save", wopi("POST", fid, opu["access_token"], b"", {"X-WOPI-Override": "LOCK", "X-WOPI-Lock": "A"})[0] == 403
                  and wopi("POST", fid + "/contents", opu["access_token"], b"X", {"X-WOPI-Override": "PUT"})[0] == 403)
            key = open(r + "/etc/untrash/wopi.key", "rb").read()
            def forge(body):
                bb = base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode().rstrip("=")
                return bb + "." + hmac.new(key, bb.encode(), hashlib.sha256).hexdigest()
            check("wopi: an expired token is refused", wopi("GET", fid, forge({"u": "admin", "s": "mixed", "p": "brief.odt", "e": int(time.time()) - 1}))[0] == 401)
            check("wopi: rights are checked now, not at opening (bob's token is refused)",
                  wopi("GET", fid, forge({"u": "bob", "s": "mixed", "p": "brief.odt", "e": int(time.time()) + 99}))[0] == 403)
            check("wopi: key file only for root", oct(os.stat(r + "/etc/untrash/wopi.key").st_mode & 0o777) == "0o600")
            # PutRelativeFile ("Save as", "Export as PDF"): names in UTF-7
            st, _b2, _h = wopi("POST", fid, tk, b"%PDF-1.4 x", {"X-WOPI-Override": "PUT_RELATIVE", "X-WOPI-SuggestedTarget": ".pdf"})
            pr = json.loads(_b2) if st == 200 else {}
            check("wopi: PutRelative with a suggested extension makes brief.pdf next to it", st == 200 and pr.get("Name") == "brief.pdf"
                  and open(r + "/i-data/aaaa0001/mixed/brief.pdf", "rb").read() == b"%PDF-1.4 x" and pr.get("Url", "").startswith("http://nas.test/wopi/files/") and pr.get("LastModifiedTime", "").endswith("Z"))
            ntk = urllib.parse.unquote(pr.get("Url", "x=").split("access_token=")[1])
            check("wopi: the new file's URL and token work", wopi("GET", pr["Url"].split("/wopi/files/")[1].split("?")[0], ntk)[0] == 200)
            st, _b2, _h = wopi("POST", fid, tk, b"X", {"X-WOPI-Override": "PUT_RELATIVE", "X-WOPI-SuggestedTarget": ".pdf"})
            check("wopi: a suggestion never overwrites (brief (2).pdf)", json.loads(_b2).get("Name") == "brief (2).pdf")
            st, _b2, h = wopi("POST", fid, tk, b"X", {"X-WOPI-Override": "PUT_RELATIVE", "X-WOPI-RelativeTarget": "brief.pdf"})
            check("wopi: an exact name that exists: 409 with a free name", st == 409 and h.get("X-WOPI-ValidRelativeTarget") == "brief (3).pdf")
            st, _b2, _h = wopi("POST", fid, tk, b"NEW", {"X-WOPI-Override": "PUT_RELATIVE", "X-WOPI-RelativeTarget": "brief.pdf", "X-WOPI-OverwriteRelativeTarget": "true"})
            check("wopi: ... or overwritten on request", st == 200 and open(r + "/i-data/aaaa0001/mixed/brief.pdf", "rb").read() == b"NEW")
            st, _b2, _h = wopi("POST", fid, tk, b"U", {"X-WOPI-Override": "PUT_RELATIVE", "X-WOPI-RelativeTarget": "Grüße.odt".encode("utf-7").decode()})
            check("wopi: UTF-7 names (Grüße)", st == 200 and json.loads(_b2).get("Name") == "Grüße.odt")
            check("wopi: no names outside the folder", wopi("POST", fid, tk, b"X", {"X-WOPI-Override": "PUT_RELATIVE", "X-WOPI-RelativeTarget": "../x.odt"})[0] == 400)
            check("wopi: alice (read only) cannot save as", wopi("POST", fid, opu["access_token"], b"X", {"X-WOPI-Override": "PUT_RELATIVE", "X-WOPI-SuggestedTarget": ".pdf"})[0] == 403)
            for f in ("brief.pdf", "brief (2).pdf", "Grüße.odt"):
                os.unlink(r + "/i-data/aaaa0001/mixed/" + f)
            # proof keys: an office server that signs its requests (key made with openssl)
            kdir = tempfile.mkdtemp()
            subprocess.run(["openssl", "genrsa", "-out", kdir + "/k.pem", "2048"], check=True, capture_output=True)
            mod = subprocess.run(["openssl", "rsa", "-in", kdir + "/k.pem", "-noout", "-modulus"], check=True, capture_output=True, text=True).stdout.strip().split("=")[1]
            b64 = lambda bb: base64.b64encode(bb).decode()  # noqa: E731
            pk = '<proof-key value="x" modulus="%s" exponent="%s" oldvalue="x" oldmodulus="%s" oldexponent="%s"/>' % (
                b64(bytes.fromhex(mod)), b64((65537).to_bytes(3, "big")), b64(bytes.fromhex(mod)), b64((65537).to_bytes(3, "big")))
            DISC = DISC.replace(b"</net-zone>", b"</net-zone>" + pk.encode())
            OfficeH.do_GET = lambda self: (self.send_response(200), self.send_header("Content-Type", "text/xml"), self.end_headers(), self.wfile.write(DISC))
            a.req("/api/office/settings", {"server": office, "wopi_base": "http://nas.test"})       # discovery read again
            def proof(path, token, ts=None, url_base="http://nas.test"):
                ts = ts if ts is not None else int((time.time() + 62135596800) * 1e7)
                url = (url_base + path).upper().encode()
                msg = struct.pack(">I", len(token)) + token.encode() + struct.pack(">I", len(url)) + url + struct.pack(">I", 8) + struct.pack(">q", ts)
                open(kdir + "/m", "wb").write(msg)
                sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", kdir + "/k.pem", kdir + "/m"], check=True, capture_output=True).stdout
                return {"X-WOPI-TimeStamp": str(ts), "X-WOPI-Proof": b64(sig)}
            ppath = "/wopi/files/%s?access_token=%s" % (fid, urllib.parse.quote(tk))
            check("proof: without a proof the token alone is refused", wopi("GET", fid, tk)[0] == 401)
            check("proof: with a valid proof accepted", wopi("GET", fid, tk, hdrs=proof(ppath, tk))[0] == 200)
            check("proof: a proof for another URL is refused", wopi("GET", fid, tk, hdrs=proof(ppath, tk, url_base="http://evil.test"))[0] == 401)
            check("proof: an old time stamp is refused", wopi("GET", fid, tk, hdrs=proof(ppath, tk, ts=int((time.time() - 3600 + 62135596800) * 1e7)))[0] == 401)
            bad = proof(ppath, tk)
            bad["X-WOPI-Proof"] = b64(bytes(256))
            check("proof: a wrong signature is refused", wopi("GET", fid, tk, hdrs=bad)[0] == 401)
            shutil.rmtree(kdir)
            a.req("/api/office/settings", {"server": "", "wopi_base": ""})
            check("office: switched off", a.req("/api/office")[1]["enabled"] is False and a.req("/api/office/open", {"share": "mixed", "path": "brief.odt"})[0] == 400)
            osrv.shutdown()
            # updates: settings, check, the downloaded release, downgrade guard (untrash-update: test-update-host.py)
            def utslot(ver):
                head = os.urandom(4096)
                man = ("format=untrash-slot-2\nversion=%s\nkernel_off=0\nkernel_len=4096\nkernel_sha256=%s\n"
                       % (ver, hashlib.sha256(head).hexdigest())).encode()
                return head + man.ljust(4096, b"\0") + b"\1" * 64 + b"\0" * 4032
            open(r + "/etc/untrash-version", "w").write("1.0\n")
            st, uj = a.req("/api/update")
            check("update: version, settings, no release yet", st == 200 and uj["version"] == "1.0" and uj["release"] == {})
            check("update settings saved", a.req("/api/update/settings", {"channel": "beta", "download": False})[0] == 200
                  and a.req("/api/update")[1]["settings"]["channel"] == "beta" and a.req("/api/update")[1]["settings"]["download"] is False)
            check("update settings: unknown channel refused", a.req("/api/update/settings", {"channel": "nightly"})[0] == 400)
            check("update check starts", a.req("/api/update/check", {})[0] == 200)
            check("alice: update API 403", u.req("/api/update/check", {})[0] == 403 and u.req("/api/update")[0] == 403)
            check("install release: none ready -> 400", a.req("/api/update/install", {"source": "release"})[0] == 400)
            ud = r + "/var/lib/untrash/update"
            os.makedirs(ud, exist_ok=True)
            open(ud + "/2.0.utslot", "wb").write(utslot("2.0"))
            json.dump({"available": {"version": "2.0"}, "download": {"state": "ready", "file": ud + "/2.0.utslot"}}, open(ud + "/state.json", "w"))
            # which slot is written: never the running one (2026-10-25: a partition boot has no boot.env;
            # the old code then always wrote slot a, over the running system of untrash-2)
            st, ij = a.req("/api/update/install", {"source": "release"})
            check("install refused when the running slot is unknown", st == 500 and "Cannot tell" in ij.get("error", ""))
            open(r + "/proc/cmdline", "w").write("console=ttyS0 init=/usr/lib/untrash/untrash-init untrash.verity=1,x,y untrash.part=ut-sys-a\n")
            st, ij = a.req("/api/update/install", {"source": "release"})
            check("install the downloaded release 2.0 into slot b (running from ut-sys-a, partition boot)",
                  st == 200 and ij.get("slot") == "b" and a.req("/api/update")[1]["image"] == "2.0")
            open(r + "/proc/cmdline", "w").write("root=/dev/dm-0 dm-mod.waitfor=PARTLABEL=ut-sys-b dm-mod.create=\"untrash-root,,,ro,0 1 verity\"\n")
            json.dump({"available": {"version": "2.0"}, "download": {"state": "ready", "file": ud + "/2.0.utslot"}}, open(ud + "/state.json", "w"))
            st, ij = a.req("/api/update/install", {"source": "release"})
            check("... into slot a when running from ut-sys-b (loader without initrd: dm-mod.waitfor)", st == 200 and ij.get("slot") == "a")
            os.makedirs(r + "/run/untrash", exist_ok=True)
            open(r + "/run/untrash/boot.env", "w").write("ZT_BOOT=file\nZT_SLOT=b\nZT_HOST=/run/untrash/host\n")
            json.dump({"available": {"version": "2.0"}, "download": {"state": "ready", "file": ud + "/2.0.utslot"}}, open(ud + "/state.json", "w"))
            st, ij = a.req("/api/update/install", {"source": "release"})
            check("... a slot file boot takes the slot from boot.env (b -> a)", st == 200 and ij.get("slot") == "a")
            os.unlink(r + "/run/untrash/boot.env")
            open(r + "/proc/cmdline", "w").write("untrash.part=ut-sys-a\n")
            st, _ = a.req("/api/update/upload", raw=utslot("0.9"))
            uj = a.req("/api/update")[1]
            check("upload of an older image: accepted, marked older", st == 200 and uj["older"] and uj["image"] == "0.9")
            check("older image: install needs the downgrade confirmation", a.req("/api/update/install", {})[0] == 400
                  and a.req("/api/update/install", {"downgrade": True})[0] == 200)
            # RAID / volumes (untrash-storage test double; the real tool: test-storage-host.sh)
            check("alice: raid 403", u.req("/api/raid")[0] == 403)
            st, rj = a.req("/api/raid")
            check("raid status + idle job", st == 200 and rj["arrays"][0]["md"] == "md2" and rj["free"] == ["disk3", "disk4"]
                  and rj["job"]["state"] == "idle")
            check("unknown raid op refused", a.req("/api/raid/job", {"op": "format-all"})[0] == 400)
            check("create needs FORMAT", a.req("/api/raid/job", {"op": "create", "level": "basic", "disks": ["disk3"],
                                                                       "name": "Neu", "confirm": "ja"})[0] == 400)

            def raid_wait():
                for _ in range(50):
                    j = a.req("/api/raid")[1]["job"]
                    if j["state"] != "running":
                        return j
                    time.sleep(0.1)
                return j
            st, _ = a.req("/api/raid/job", {"op": "create", "level": "basic", "disks": ["disk3"], "name": "Neu",
                                             "confirm": "FORMAT"})
            j = raid_wait()
            jobs = open(r + "/storage-jobs.log").read()
            check("create job ran (args without confirm)", st == 200 and j["state"] == "done" and
                  any("RESULT OK" in x for x in j["log"]) and '"disks": ["disk3"]' in jobs and "FORMAT" not in jobs)
            check("expand without confirmation", a.req("/api/raid/job", {"op": "expand", "md": "md2"})[0] == 200
                  and raid_wait()["state"] == "done")
            check("delete needs DELETE", a.req("/api/raid/job", {"op": "delete", "md": "md9", "confirm": "LOESCHEN"})[0] == 400)
            a.req("/api/raid/job", {"op": "delete", "md": "md9", "confirm": "DELETE"})
            check("failed job reported", raid_wait()["state"] == "failed")
            check("overview hides md0/md1", all(x["name"] not in ("md0", "md1") for x in a.req("/api/overview")[1]["arrays"]))
            # passwords
            check("alice changes own password (old checked)", u.req("/api/password", {"old": PW, "password": "Neues-Pw-12"})[0] == 200)
            check("alice cannot change bob's", u.req("/api/password", {"name": "bob", "password": "Neues-Pw-12"})[0] == 403)
            # way D
            st, sj = a.req("/api/stock")
            check("stock backup found on the stick", st == 200 and sj["stick"] and sj["run"]["name"] == "install-20261010-080000")
            check("rollback needs STOCK", a.req("/api/stock/rollback", {"confirm": "x"})[0] == 400)
            st, _ = a.req("/api/stock/rollback", {"confirm": "STOCK"})
            check("rollback: marker set", st == 200 and os.path.exists(stick + "/UNTRASH/ROLLBACK"))
            # RESET button window: admin password without login
            check("no reset window", a.req("/api/state")[1]["reset_window"] == 0 and
                  Client(port).req("/api/reset-admin", {"password": "Neu-Passwort-1"})[0] == 403)
            os.makedirs(r + "/run/untrash", exist_ok=True)
            open(r + "/run/untrash/admin-reset", "w").close()
            anon = Client(port)
            check("reset window open after the button", 800 < anon.req("/api/state")[1]["reset_window"] <= 900)
            check("reset: short password refused", anon.req("/api/reset-admin", {"password": "kurz"})[0] == 400)
            check("reset: admin password set without login, window closed", anon.req("/api/reset-admin", {"password": "Neu-Passwort-1"})[0] == 200
                  and anon.req("/api/state")[1]["reset_window"] == 0 and not os.path.exists(r + "/run/untrash/admin-reset"))
            # player: probe + remux stream (real ffmpeg), direct play for web formats
            mx = r + "/i-data/aaaa0001/mixed/"
            ff = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=d=2:s=160x120:r=10", "-f", "lavfi", "-i", "sine=d=2",
                  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "10"]
            mk = subprocess.run(ff + ["-c:a", "ac3", mx + "film.mkv"], capture_output=True).returncode == 0
            mp = subprocess.run(ff + ["-c:a", "aac", mx + "web.mp4"], capture_output=True).returncode == 0
            if mk and mp:
                st, pr = u.req("/api/files/probe?share=mixed&path=film.mkv")
                check("probe mkv: h264 + ac3 -> remux, duration", st == 200 and pr["mode"] == "remux" and pr["video"][0]["codec"] == "h264"
                      and pr["audio"][0]["codec"] == "ac3" and 1.5 < pr["duration"] < 2.6)
                st, pr = u.req("/api/files/probe?share=mixed&path=web.mp4")
                check("probe mp4: h264 + aac -> direct", st == 200 and pr["mode"] == "direct")
                st, hd, body = raw("/api/files/stream?share=mixed&path=film.mkv&t=0.5")
                check("stream: fragmented MP4 (ftyp, moof) with H.264 + AAC", st == 200 and hd.get("Content-Type") == "video/mp4"
                      and b"ftyp" in body[:64] and b"moof" in body and b"avc1" in body and b"mp4a" in body)
                check("stream: no access to other shares", u.req("/api/files/stream?share=geheim&path=x.mkv")[0] in (403, 404))
            else:
                check("ffmpeg with libx264 for the player test", False)
            # shares from existing folders (folder picker) and share links
            os.makedirs(r + "/i-data/aaaa0001/alt/Fotos/2025", exist_ok=True)
            open(r + "/i-data/aaaa0001/alt/Fotos/2025/bild.txt", "w").write("x" * 1000)
            st, d = a.req("/api/volumes/dirs?volume=aaaa0001&path=alt")
            check("picker: folders of a volume", st == 200 and [x["name"] for x in d["dirs"]] == ["Fotos"])
            check("picker: no traversal", a.req("/api/volumes/dirs?volume=aaaa0001&path=../../etc")[0] in (200, 400)
                  and "passwd" not in str(a.req("/api/volumes/dirs?volume=aaaa0001&path=../../etc")[1]))
            st, _ = a.req("/api/shares/save", {"new": True, "name": "Fotos", "volume": "aaaa0001", "folder": "alt/Fotos"})
            sp = [x for x in a.req("/api/shares")[1]["shares"] if x["name"] == "Fotos"]
            check("share on an existing folder", st == 200 and sp and sp[0]["path"].endswith("/aaaa0001/alt/Fotos") and sp[0]["present"])
            check("same folder not shared twice", a.req("/api/shares/save", {"new": True, "name": "Fotos2", "volume": "aaaa0001",
                                                                             "folder": "alt/Fotos"})[0] == 400)
            check("missing folder refused", a.req("/api/shares/save", {"new": True, "name": "Nix", "volume": "aaaa0001",
                                                                      "folder": "alt/gibtsnicht"})[0] == 400)
            check("picker marks shared folders", any(x["shared"] == "Fotos" for x in a.req("/api/volumes/dirs?volume=aaaa0001&path=alt")[1]["dirs"]))
            st, lk = u.req("/api/links/create", {"share": "mixed", "path": "readme.txt", "days": 7})
            check("link created (user with access)", st == 200 and lk["url"].startswith("/s/"))
            anon = Client(port)
            rq = urllib.request.Request(anon.base + lk["url"])
            with urllib.request.urlopen(rq) as resp:
                body = resp.read()
            check("link: public download without login", body == b"hallo\n")
            st, lk2 = a.req("/api/links/create", {"share": "Fotos", "path": "", "days": 1, "password": "geheim1"})
            page = urllib.request.urlopen(anon.base + lk2["url"]).read()
            check("password link asks first", b'name="pw"' in page)
            try:
                urllib.request.urlopen(urllib.request.Request(anon.base + lk2["url"], data=b"pw=falsch"))
                bad = False
            except urllib.error.HTTPError as e:
                bad = e.code == 403
            check("wrong link password refused", bad)
            import io, zipfile
            zb = urllib.request.urlopen(urllib.request.Request(anon.base + lk2["url"], data=b"pw=geheim1")).read()
            zn = zipfile.ZipFile(io.BytesIO(zb)).namelist()
            check("folder link: ZIP with the files", zn == ["Fotos/2025/bild.txt"])
            check("user sees only own links", len(u.req("/api/links")[1]["links"]) == 1 and len(a.req("/api/links")[1]["links"]) == 2)
            check("user cannot delete another's link", u.req("/api/links/delete", {"token": lk2["token"]})[0] == 404)
            check("no link without access", u.req("/api/links/create", {"share": "geheim", "path": "", "days": 7})[0] in (403, 404))
            dl = a.req("/api/links/delete", {"token": lk["token"]})[0]
            try:
                urllib.request.urlopen(anon.base + lk["url"])
                gone = False
            except urllib.error.HTTPError as e:
                gone = e.code == 404 and b"expired" in e.read()
            check("deleted link answers 404", dl == 200 and gone)
            # export: USB targets (never the UntrashOS stick), copy job runs to the end, rights
            os.makedirs(r + "/media/usb-x", exist_ok=True)
            os.makedirs(r + "/run/untrash", exist_ok=True)
            json.dump({"sdz1": {"id": "U1", "fs": "vfat", "mnt": "/media/usb-x", "name": "Stick", "label": "DATA"},
                       "sdy1": {"id": "U2", "fs": "vfat", "mnt": "/media/usb-x", "name": "", "label": "UNTRASHPK"}},
                      open(r + "/run/untrash/usb.json", "w"))
            st, tg = u.req("/api/export/targets")
            check("export: USB drives listed, UntrashOS stick hidden", st == 200 and [x["id"] for x in tg["usb"]] == ["U1"])
            st, ej = u.req("/api/export/start", {"sources": [{"share": "mixed", "path": "readme.txt"}], "target": {"usb": "U1"},
                                                 "folder": "Test-Export", "mode": "copy"})
            for _ in range(100):
                jobs = u.req("/api/export/jobs")[1]["jobs"]
                if jobs and jobs[0]["state"] not in ("waiting", "running"):
                    break
                time.sleep(0.05)
            check("export: copy job done", st == 200 and jobs[0]["state"] == "done" and jobs[0]["percent"] == 100)
            check("export: file on the USB drive", open(r + "/media/usb-x/Test-Export/readme.txt").read() == "hallo\n")
            check("export: no source without access", u.req("/api/export/start", {"sources": [{"share": "geheim", "path": ""}],
                                                                                  "target": {"usb": "U1"}})[0] in (403, 404))
            check("export: unknown USB refused", u.req("/api/export/start", {"sources": [{"share": "mixed", "path": "readme.txt"}],
                                                                             "target": {"usb": "U2"}})[0] == 400)
            check("export: admin removes a finished job", a.req("/api/export/cancel", {"id": ej["id"], "remove": True})[0] == 200
                  and u.req("/api/export/jobs")[1]["jobs"] == [])
            # feedback info (a local name must not shadow disks())
            st, fi = a.req("/api/feedback/info")
            check("feedback: info with issue address and system data", st == 200 and "/issues" in fi.get("issues", "") and fi.get("info"))
            # every admin GET answers without an internal error
            bad = [x for x in sorted(ADMIN_GETS) if a.req(x)[0] >= 500]
            check("no admin GET endpoint fails with 500 %s" % bad, not bad)
            # ad filter: off by default, switching = flag + start/stop (no daemon-reload), rules validated
            st, ab = a.req("/api/adblock")
            check("adblock: off by default, default lists", st == 200 and ab["active"] is False and ab["lists"][0]["on"])
            check("adblock: admins only", u.req("/api/adblock")[0] == 403)
            st, ab = a.req("/api/adblock/save", {"active": True})
            check("adblock: on = flag file + restart, first list download", st == 200 and ab["active"] and
                  os.path.exists(r + "/var/lib/untrash/adblock/enabled"))
            st, ab = a.req("/api/adblock/save", {"allow": ["Good.Example.com"], "block": ["*.ads.test", "ads.test"]})
            check("adblock: rules normalised and deduplicated", st == 200 and ab["allow"] == ["good.example.com"] and
                  ab["block"] == ["*.ads.test", "ads.test"])
            check("adblock: invalid domain refused", a.req("/api/adblock/save", {"block": ["not a domain"]})[0] == 400)
            check("adblock: invalid list address refused", a.req("/api/adblock/save", {"lists": [{"url": "ftp://x"}]})[0] == 400)
            log = r + "/run/untrash/adblock/query.log"
            os.makedirs(os.path.dirname(log), exist_ok=True)
            ts = time.strftime("%b %d %H:%M:%S")
            open(log, "w").write(
                "%s dnsmasq[9]: 1 192.168.1.20/5000 query[A] ads.test from 192.168.1.20\n"
                "%s dnsmasq[9]: 1 192.168.1.20/5000 config ads.test is 0.0.0.0\n"
                "%s dnsmasq[9]: 2 192.168.1.21/5001 query[A] example.org from 192.168.1.21\n"
                "%s dnsmasq[9]: 2 192.168.1.21/5001 forwarded example.org to 192.168.1.1\n" % (ts, ts, ts, ts))
            st, lg = a.req("/api/adblock/log?blocked=1")
            check("adblock: query log, blocked filter", st == 200 and [x["name"] for x in lg["rows"]] == ["ads.test"])
            st, ab = a.req("/api/adblock/save", {"active": False})
            check("adblock: off removes the flag", st == 200 and not os.path.exists(r + "/var/lib/untrash/adblock/enabled"))
            # media server window + broadcast channels
            st, m = a.req("/api/media")
            check("media: state without a running minidlna", st == 200 and m["running"] is False and "tv" in m
                  and any(x["name"] == "mixed" for x in m["shares"]))
            check("media: admins only", u.req("/api/media")[0] == 403)
            st, m = a.req("/api/media/save", {"active": True, "shares": {"mixed": 5}})
            sm = json.load(open(r + "/etc/untrash/settings.json"))["services"]["mediaserver"]
            check("media: types per share saved, server on", st == 200 and sm["active"] and sm["shares"].get("mixed") == 5)
            check("media: unknown share refused", a.req("/api/media/save", {"shares": {"nix": 1}})[0] == 404)
            check("media: rescan restarts minidlna", a.req("/api/media/rescan", {})[0] == 200)
            st, c = a.req("/api/tv/save", {"name": "Kanal 1", "items": [{"share": "mixed", "path": "readme.txt"}], "profile": "480"})
            check("tv: channel saved", st == 200 and len(c["id"]) == 6)
            check("tv: missing file refused", a.req("/api/tv/save", {"name": "x", "items": [{"share": "mixed", "path": "nix.mp4"}]})[0] == 404)
            check("tv: users see channel names only", u.req("/api/tv")[1]["channels"][0]["name"] == "Kanal 1"
                  and "items" not in u.req("/api/tv")[1]["channels"][0])
            check("tv: users cannot create channels", u.req("/api/tv/save", {"name": "y", "items": []})[0] == 403)
            m3u = urllib.request.urlopen(Client(port).base + "/tv/channels.m3u").read().decode()
            check("tv: M3U channel list in the home network without login", m3u.startswith("#EXTM3U") and
                  "Kanal 1" in m3u and "/tv/%s/index.m3u8" % c["id"] in m3u)
            try:
                urllib.request.urlopen(Client(port).base + "/tv/%s/index.m3u8" % c["id"])
                nofile = False
            except urllib.error.HTTPError as e:
                nofile = e.code == 400
            check("tv: channel without playable files does not start", nofile)
            a.req("/api/media/save", {"lan_open": False})
            try:
                urllib.request.urlopen(Client(port).base + "/tv/channels.m3u")
                closed = False
            except urllib.error.HTTPError as e:
                closed = e.code == 401
            check("tv: closed for the home network = login needed", closed)
            check("tv: delete", a.req("/api/tv/delete", {"id": c["id"]})[0] == 200 and a.req("/api/tv")[1]["channels"] == [])
            # sounds: save, show, play on the (logged) buzzer, import a sound set, reset
            st, sd = a.req("/api/sound")
            check("sound: built-in scores listed", st == 200 and "boot" in sd["builtin"] and sd["user"] == {})
            st, sd = a.req("/api/sound/save", {"event": "boot", "notes": [[1047, 160], [0, 80], [831, 480]], "tempo": 1.5})
            check("sound: user score saved", st == 200 and sd["user"]["boot"]["tempo"] == 1.5)
            check("sound: out-of-range note refused", a.req("/api/sound/save", {"event": "boot", "notes": [[5, 100]]})[0] == 400)
            check("sound: users may not change sounds", u.req("/api/sound/save", {"event": "boot", "notes": [[440, 100]]})[0] == 403)
            # editor scores: tied notes and the editor's own data are kept; the driver's limits apply
            score = {"v": 1, "bpm": 120, "grid": 16, "key": "C", "scale": "major", "patterns": [{"name": "A", "notes": [{"t": 0, "d": 250, "hz": 523.25}]}],
                     "arrangement": [{"p": 0, "n": 2}]}
            st, sd = a.req("/api/sound/save", {"event": "warning", "notes": [[523, 20, 1], [540, 20], [0, 100]], "tempo": 1, "score": score})
            check("sound: tied notes and the editor score saved", st == 200 and sd["user"]["warning"]["notes"][0] == [523, 20, 1]
                  and sd["user"]["warning"]["score"]["arrangement"] == [{"p": 0, "n": 2}])
            check("sound: the buzzer's limits (100..4000 Hz)", a.req("/api/sound/save", {"event": "boot", "notes": [[90, 100]]})[0] == 400
                  and a.req("/api/sound/save", {"event": "boot", "notes": [[4100, 100]]})[0] == 400)
            check("sound: at most 60 s", a.req("/api/sound/save", {"event": "boot", "notes": [[440, 1000]] * 61})[0] == 400)
            check("sound: score must be an object", a.req("/api/sound/save", {"event": "boot", "notes": [[440, 100]], "score": [1]})[0] == 400)
            open(r + "/tones", "w").close()
            a.req("/api/sound/play", {"notes": [[440, 100]], "tempo": 2})
            for _ in range(30):
                if "440 200" in open(r + "/tones").read():
                    break
                time.sleep(0.1)
            check("sound: preview played on the NAS buzzer (tempo applied)", "440 200" in open(r + "/tones").read())
            ss = {"title": "Test-Set", "events": {"shutdown": {"notes": [{"frequency_hz": 784, "duration_ms": 300}]},
                                                  "nope": {"notes": []}}}
            st, sd = a.req("/api/sound/import", {"soundset": ss})
            check("sound: sound set imported (known events only)", st == 200 and sd["imported"] == 1
                  and sd["user"]["shutdown"]["source"] == "Test-Set")
            st, sd = a.req("/api/sound/save", {"event": "boot", "reset": True})
            check("sound: reset to built-in", st == 200 and "boot" not in sd["user"] and "shutdown" in sd["user"])
            # logout + lockout
            check("logout", a.req("/api/logout", {})[0] == 200 and a.req("/api/me")[0] == 401)
            x = Client(port)
            for _ in range(3):
                x.req("/api/login", {"user": "admin", "password": "falsch"})
            check("lockout after failures", x.req("/api/login", {"user": "admin", "password": PW})[0] == 429)
        finally:
            srv.terminate()
            out = srv.communicate()[0].decode(errors="replace")
            if fails:
                print(out[-2000:])
        # HTTPS listener with the uploaded certificate, HTTP redirects (force)
        import ssl
        e3 = dict(env_for(r, stick, port + 2), ZT_DESK_TLS_PORT=str(port + 3))
        srv = subprocess.Popen([sys.executable, os.path.join(FILES, "usr/lib/untrash/untrash-desk")], env=e3,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            for _ in range(50):
                try:
                    socket_ok = urllib.request.urlopen("https://127.0.0.1:%d/api/state" % (port + 3),
                                                       context=ssl._create_unverified_context()).status == 200
                    break
                except OSError:
                    socket_ok = False
                    time.sleep(0.1)
            check("https listener answers", socket_ok)

            class NoRedir(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *x, **k):
                    return None
            try:
                urllib.request.build_opener(NoRedir).open("http://127.0.0.1:%d/api/state" % (port + 2))
                loc = ""
            except urllib.error.HTTPError as e:
                loc = e.headers.get("Location", "")
            check("http redirected to https (force)", loc == "https://127.0.0.1:%d/api/state" % (port + 3))
        finally:
            srv.terminate()
            srv.communicate()
        # first setup (way A)
        w2 = os.path.join(w, "fresh")
        os.makedirs(w2)
        r2, stick2 = build_root(w2, fresh=True)
        srv = subprocess.Popen([sys.executable, os.path.join(FILES, "usr/lib/untrash/untrash-desk")],
                               env=env_for(r2, stick2, port + 1), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            for _ in range(50):
                try:
                    urllib.request.urlopen("http://127.0.0.1:%d/api/state" % (port + 1))
                    break
                except OSError:
                    time.sleep(0.1)
            f = Client(port + 1)
            check("fresh: not initialized", f.req("/api/state")[1]["initialized"] is False)
            check("fresh: login impossible", f.req("/api/login", {"user": "admin", "password": PW})[0] == 401)
            check("setup: short password refused", f.req("/api/setup", {"name": "meine-nas", "password": "kurz"})[0] == 400)
            st, _ = f.req("/api/setup", {"name": "meine-nas", "password": "Sehr-Geheim-1"})
            check("setup done", st == 200 and f.req("/api/state")[1]["initialized"])
            check("setup only once", f.req("/api/setup", {"name": "x", "password": "Sehr-Geheim-1"})[0] == 409)
            check("setup: takeover marker + public share", os.path.exists(r2 + "/etc/untrash/zyxel/takeover.json") and
                  os.path.isdir(r2 + "/i-data/aaaa0001/public") and "[public]" in open(r2 + "/etc/samba/smb.conf").read())
            s4 = json.load(open(r2 + "/etc/untrash/settings.json"))
            check("setup: hostname + netbios", s4["hostname"] == "meine-nas" and s4["netbios"]["name"] == "MEINE-NAS")
        finally:
            srv.terminate()
            srv.communicate()
    print("DESK HOST TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", len(fails)))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    if "--serve" in sys.argv:
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        serve(int(args[0]) if args else 8790, "--fresh" in sys.argv)
    else:
        main()
