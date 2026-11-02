#!/usr/bin/env python3
"""The Nextcloud app "untrash" against a real Nextcloud (Docker) and the NAS
side of this repository.

  python3 nextcloud/tests/test_nextcloud_docker.py APACHEROOT [IMAGE]

APACHEROOT: unpacked Debian debs apache2-bin libapr1 libaprutil1 (as for
image/tests/test-webdav-host.py).  IMAGE: default nextcloud:25-apache.  Docker
via "sudo -n docker".  The container runs in the host network (Apache on
port 18080), so it reaches the NAS services on 127.0.0.1 like a server in
the LAN would.

NAS side: untrash-mesh (mesh admin, fake WireGuard), untrash-cloudlink with
a fake feed (the test appends the paths it changes), and Apache with
WebDAV on one share plus the /untrash-cloudlink/ pass-through.

Checked: canonical JSON and signatures agree between PHP and the NAS;
occ untrash:join with a cloud invitation; the NAS pushes records to the
Nextcloud directory and learns its IP there; a forged sync is refused;
external storage (WebDAV, "check for changes: never") updated by
occ untrash:feed: a new file appears only after the feed, a deleted one
disappears, a change in a subfolder changes the etags up to the mount;
the admin settings page answers; removing the cloud on the NAS ends the
directory (403, address book cleared).
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OS = os.path.abspath(os.path.join(HERE, "..", ".."))
APP = os.path.join(HERE, "..", "untrash")
LIB = os.path.join(OS, "image", "rootfs", "usr", "lib", "untrash")
MESH, CLOUDLINK = os.path.join(LIB, "untrash-mesh"), os.path.join(LIB, "untrash-cloudlink")
if len(sys.argv) < 2:
    sys.exit(__doc__)
AR = os.path.abspath(sys.argv[1])
IMAGE = sys.argv[2] if len(sys.argv) > 2 else "nextcloud:25-apache"
NAME = "ut-nc-test"
NC_PORT = 18080
NC = "http://127.0.0.1:%d" % NC_PORT
ADMIN_PW = "untrash-test-admin"         # throwaway container, never a real account
fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name, flush=True)
    fails += not ok


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def docker(*a, check=True, input=None):
    r = subprocess.run(["sudo", "-n", "docker"] + list(a), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, input=input)
    if check and r.returncode:
        raise RuntimeError("docker %s: %s" % (" ".join(a[:3]), r.stdout[:1500]))
    return r.stdout


def occ(*a, check=True):
    return docker("exec", "-u", "www-data", NAME, "php", "occ", "--no-ansi", *a, check=check)


def wait(cond, secs=30):
    t = time.time()
    while time.time() - t < secs:
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def jf(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


def nc_dav(path, depth="1"):
    """Names below admin's files/<path> as Nextcloud's own WebDAV lists them (from its cache)."""
    rq = urllib.request.Request(NC + "/remote.php/dav/files/admin/" + path, method="PROPFIND", headers={
        "Depth": depth, "Authorization": "Basic " + base64.b64encode(("admin:" + ADMIN_PW).encode()).decode()},
        data=b'<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:getetag/></d:prop></d:propfind>')
    body = urllib.request.urlopen(rq, timeout=30).read().decode()
    import re
    hrefs = re.findall(r"<d:href>([^<]+)</d:href>\s*<d:propstat>\s*<d:prop>\s*<d:getetag>([^<]*)</d:getetag>", body)
    return {urllib.parse.unquote(h).rstrip("/").rsplit("/", 1)[-1]: e for h, e in hrefs}


import urllib.parse  # noqa: E402

W = tempfile.mkdtemp(prefix="ut-nc-")
procs = []
try:
    SIG = os.path.join(W, "zt-sig")
    subprocess.run(["gcc", "-O2", "-I" + os.path.join(OS, "third_party/tweetnacl"), "-o", SIG,
                    os.path.join(OS, "slot/zt-sig.c"), os.path.join(OS, "third_party/tweetnacl/tweetnacl.c")], check=True)

    # ---------------------------------------------------------------- Nextcloud
    docker("rm", "-f", NAME, check=False)
    docker("run", "-d", "--name", NAME, "--network", "host",
           "-e", "SQLITE_DATABASE=nc", "-e", "NEXTCLOUD_ADMIN_USER=admin", "-e", "NEXTCLOUD_ADMIN_PASSWORD=" + ADMIN_PW,
           "-e", "NEXTCLOUD_TRUSTED_DOMAINS=127.0.0.1 localhost",
           "-v", os.path.abspath(APP) + ":/untrash-app:ro",       # copied in after the install (custom_apps must stay writable)
           "--entrypoint", "sh", IMAGE, "-c",
           "sed -i 's/^Listen 80$/Listen %d/' /etc/apache2/ports.conf && sed -i 's/:80>/:%d>/' "
           "/etc/apache2/sites-enabled/000-default.conf && exec /entrypoint.sh apache2-foreground" % (NC_PORT, NC_PORT))
    check("Nextcloud container installed and answering", wait(lambda: json.load(urllib.request.urlopen(
        NC + "/status.php", timeout=5)).get("installed") is True, 240))
    occ("config:system:set", "overwrite.cli.url", "--value", NC)
    docker("exec", NAME, "sh", "-c", "rm -rf /var/www/html/custom_apps/untrash && cp -r /untrash-app /var/www/html/custom_apps/untrash"
           " && chown -R www-data: /var/www/html/custom_apps/untrash")
    occ("app:enable", "files_external")
    out = occ("app:enable", "untrash", check=False)
    check("app enabled (info.xml, dependencies incl. sodium)", "enabled" in out)
    if "enabled" not in out:
        print(out)
        raise SystemExit(1)

    # canonical JSON and signatures, PHP vs the NAS (Python + zt-sig)
    sample = {"z": [1, {"b": "Grüße/\"x\"\n", "a": {}}], "a": "€   \x7f", "sig": "drop me", "n": None, "t": True}
    php = ("require '/var/www/html/custom_apps/untrash/lib/Mesh/Canon.php';"
           " echo \\OCA\\Untrash\\Mesh\\Canon::encode(json_decode(file_get_contents('php://stdin')));")
    got = docker("exec", "-i", "-u", "www-data", NAME, "php", "-r", php, input=json.dumps(sample)).strip().splitlines()[-1]
    want = json.dumps({k: v for k, v in sample.items() if k != "sig"}, sort_keys=True, separators=(",", ":"))
    check("canonical JSON: PHP == Python (unicode, slashes, {} vs [], sig dropped)", got == want)

    # ---------------------------------------------------------------- NAS side
    R = os.path.join(W, "root")                 # cloudlink's root: stock database and share paths below it
    share = R + "/i-data/v1/Photos"
    os.makedirs(share + "/2026")
    open(share + "/old.jpg", "w").write("old")
    nasdir = os.path.join(W, "nas")
    os.makedirs(nasdir)
    open(nasdir + "/hosts", "w").write("")
    jp, sp, ap, cp = free_port(), free_port(), free_port(), free_port()
    nenv = dict(os.environ, ZT_MESH_DIR=nasdir + "/state", ZT_SIG=SIG, ZT_MESH_FAKE_WG=nasdir + "/wg.json",
                ZT_MESH_ADDRMAP="{}", ZT_MESH_JOIN_HOST="127.0.0.1", ZT_MESH_ENDPOINTS="192.168.1.10:51820",
                ZT_MESH_SYNC_PORT=str(sp), ZT_MESH_JOIN_PORT=str(jp), ZT_MESH_HOSTS=nasdir + "/hosts", ZT_MESH_TICK="0.5",
                ZT_MESH_DIR_EVERY="1", ZT_UPNPC="/nonexistent", ZT_MESH_SMB=nasdir + "/smb.conf", ZT_MESH_PDATA=nasdir + "/p",
                ZT_MESH_FAKE_MOUNT=nasdir + "/m.json", ZT_MESH_FAKE_ACCOUNTS=nasdir + "/a.json", ZT_MESH_FAKE_DRBD=nasdir + "/d.json",
                ZT_MESH_HOST_MNT=nasdir + "/nohost")

    def mesh(*a):
        r = subprocess.run([MESH] + list(a), env=nenv, stdout=subprocess.PIPE, text=True)
        return json.loads(r.stdout.strip().splitlines()[-1])
    nas = mesh("create", "home")
    mesh("rename", "nas-test")
    procs.append(subprocess.Popen([MESH, "run"], env=nenv, stdout=open(W + "/mesh.log", "w"), stderr=subprocess.STDOUT))
    # stock database for cloudlink: one share
    import sqlite3
    os.makedirs(R + "/etc/untrash/zyxel/stock-config")
    open(R + "/etc/untrash-version", "w").write("test\n")
    db = sqlite3.connect(R + "/etc/untrash/zyxel/stock-config/ugs_conf.db")
    db.execute("CREATE TABLE smb_share (s_name, s_path, s_enable)")
    db.execute("INSERT INTO smb_share VALUES ('Photos', '/i-data/v1/Photos', 'y')")
    db.commit()
    db.close()
    feed = W + "/feed"
    open(feed, "w").close()
    cenv = dict(nenv, ZT_CLOUDLINK_ROOT=R, ZT_CLOUDLINK_PORT=str(cp), ZT_CLOUDLINK_FAKE_FEED=feed,
                ZT_CLOUDLINK_FAKE_HEALTH=W + "/health.json")
    json.dump({"disks": [], "raid": []}, open(W + "/health.json", "w"))
    procs.append(subprocess.Popen([CLOUDLINK, "run"], env=cenv,
                                  stdout=open(W + "/cloudlink.log", "w"), stderr=subprocess.STDOUT))
    # Apache: WebDAV on the share (no auth: the rights are test-webdav-host.py's subject) + the pass-through
    os.makedirs(W + "/run")
    mods = ["mpm_event", "authz_core", "alias", "mime", "dav", "dav_fs", "dav_lock", "proxy", "proxy_http", "dir"]
    conf = ["ServerRoot " + W, "ServerName localhost", "PidFile %s/run/httpd.pid" % W, "Mutex file:%s/run default" % W,
            "DefaultRuntimeDir %s/run" % W, "ErrorLog %s/apache.log" % W, "TypesConfig /dev/null", "Listen 127.0.0.1:%d" % ap]
    conf += ["LoadModule %s_module %s/usr/lib/apache2/modules/mod_%s.so" % (m, AR, m) for m in mods]
    conf += ["DavLockDB %s/run/DavLock" % W, "Alias /webdav/Photos " + share, "<Directory %s>" % share, "  Require all granted",
             "</Directory>", "<Location /webdav/Photos>", "  Dav On", "</Location>",
             "ProxyPass /untrash-cloudlink/ http://127.0.0.1:%d/ timeout=180" % cp]
    open(W + "/httpd.conf", "w").write("\n".join(conf) + "\n")
    procs.append(subprocess.Popen([AR + "/usr/sbin/apache2", "-DFOREGROUND", "-f", W + "/httpd.conf"],
                                  env=dict(os.environ, LD_LIBRARY_PATH=AR + "/usr/lib/x86_64-linux-gnu")))
    check("NAS: WebDAV answers", wait(lambda: urllib.request.urlopen("http://127.0.0.1:%d/webdav/Photos/old.jpg" % ap).read() == b"old", 10))

    # ---------------------------------------------------------------- join
    inv = mesh("invite-cloud", "1", '["Photos"]')["invitation"]
    out = occ("untrash:join", inv, "--name", "nc-test", check=False)
    if '"mesh"' not in out:
        print(out)
    st = json.loads(occ("untrash:status"))
    nid = st["node"]
    check("occ untrash:join: member of the NAS mesh", st.get("mesh", {}).get("id") == nas["mesh"]["id"]
          and st["dir"] == NC + "/index.php/apps/untrash/mesh")
    mc = [m for m in mesh("status")["members"] if m["node"] == nid]
    check("NAS: Nextcloud is a cloud member with its directory URL and Photos", mc and mc[0]["kind"] == "cloud"
          and mc[0]["dir"] == st["dir"] and mc[0]["shares"] == ["Photos"])
    check("Nextcloud has the NAS's record (join answer)", any(m["node"] == nas["node"] and m["endpoints"] for m in st["members"]))
    check("the NAS synced with the directory (online, IP seen)", wait(lambda: any(
        m["node"] == nid and m["online"] for m in mesh("status")["members"]), 20)
          and jf(nasdir + "/state/mesh.json").get("dirseen", {}).get(nid, {}).get("ip") == "127.0.0.1")
    forged = {"items": [], "have": {}, "roster": 0, "from": nas["node"], "ts": int(time.time()), "nonce": "ab" * 16, "sig": "00" * 64}
    try:
        urllib.request.urlopen(urllib.request.Request(st["dir"] + "/v1/sync", data=json.dumps(forged).encode(),
                                                      headers={"Content-Type": "application/json"}), timeout=10)
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    check("directory refuses a request with a wrong signature (403)", code == 403)

    # ---------------------------------------------------------------- feed
    occ("untrash:nas", nas["node"], "http://127.0.0.1:%d/untrash-cloudlink" % ap)
    out = occ("files_external:create", "/NAS", "dav", "password::password", "-c", "host=127.0.0.1:%d" % ap,
              "-c", "root=webdav/Photos", "-c", "secure=false", "-c", "user=x", "-c", "password=y")
    mid = out.strip().split()[-1]
    occ("files_external:option", mid, "filesystem_check_changes", "0")
    occ("files:scan", "admin")
    check("mount scanned once: old.jpg and 2026/", {"old.jpg", "2026"} <= set(nc_dav("NAS")))
    r = json.loads(occ("untrash:feed", "--once").strip().splitlines()[-1])
    check("first feed round: cursor taken, Photos rescanned", r.get(nas["node"], {}).get("ok") and r[nas["node"]]["rescan"] == ["Photos"])
    open(share + "/new.jpg", "w").write("new")
    time.sleep(1)
    check("without the feed Nextcloud does not see new.jpg (never checks)", "new.jpg" not in nc_dav("NAS"))
    open(feed, "a").write(share + "/new.jpg\n")
    r = json.loads(occ("untrash:feed", "--once").strip().splitlines()[-1])
    check("after the feed new.jpg is there", r[nas["node"]]["changes"] == 1 and "new.jpg" in nc_dav("NAS"))
    etag_mount = nc_dav("", "1").get("NAS")
    open(share + "/2026/deep.jpg", "w").write("deep")
    open(feed, "a").write(share + "/2026/deep.jpg\n")
    occ("untrash:feed", "--once")
    check("a file in a subfolder: listed there", "deep.jpg" in nc_dav("NAS/2026"))
    check("... and the etag of the mount changed (clients sync it)", nc_dav("", "1").get("NAS") != etag_mount)
    os.remove(share + "/old.jpg")
    open(feed, "a").write(share + "/old.jpg\n")
    occ("untrash:feed", "--once")
    check("a deleted file disappears", "old.jpg" not in nc_dav("NAS"))
    st = json.loads(occ("untrash:status"))
    last = [m for m in st["members"] if m["node"] == nas["node"]][0]["feed"]["last"]
    check("status shows the last feed round", last and last["ok"])

    # settings page and controller (admin session)
    import http.cookiejar
    jar = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    page = jar.open(urllib.request.Request(NC + "/index.php/settings/admin/untrash", headers={
        "Authorization": "Basic " + base64.b64encode(("admin:" + ADMIN_PW).encode()).decode()}), timeout=30).read().decode()
    check("admin settings page has the UntrashOS section", 'id="untrash-admin"' in page and "untrash/js/admin" in page)

    # ---------------------------------------------------------------- removal
    mesh("remove", nid)
    check("removed on the NAS: the directory clears its address book", wait(lambda: not any(
        m["endpoints"] for m in json.loads(occ("untrash:status"))["members"] if not m["self"]), 20))
    check("... and reports itself as removed (settings page shows it)", json.loads(occ("untrash:status")).get("removed") is True)
finally:
    for p in procs:
        p.terminate()
    if fails:
        print("logs in", W)
        print(docker("logs", "--tail", "30", NAME, check=False))
    else:
        shutil.rmtree(W, ignore_errors=True)
    if not os.environ.get("UT_KEEP_NC"):
        docker("rm", "-f", NAME, check=False)

print("%d failed" % fails if fails else "all ok")
sys.exit(1 if fails else 0)
