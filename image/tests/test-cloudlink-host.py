#!/usr/bin/env python3
"""PC test of the Nextcloud companion, NAS side: the cloud member of
untrash-mesh (directory) and untrash-cloudlink.

  python3 image/tests/test-cloudlink-host.py

Two NAS nodes (untrash-mesh daemons, WireGuard as JSON files) and a cloud
member (image/tests/mesh-directory-ref, the stand-in for the Nextcloud app).
Checked: cloud invitation and join (kind cloud, directory URL, no WireGuard
peer, no .mesh name), the roster and records reach the directory, the
directory's view of the public IP, recovery of a lost member through the
directory, cloud-link.  untrash-cloudlink with a fake feed: signed requests
only from the linked cloud, info, changes (filtered to its shares, recycle
bin hidden, de-duplicated, long poll, rescan on overflow, unknown cursor),
health.  The fanotify feed itself needs root: test_cloudlink_fanotify_root.py.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OS = os.path.abspath(os.path.join(HERE, "..", ".."))
LIB = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash")
TOOL = os.path.join(LIB, "untrash-mesh")
CLOUDLINK = os.path.join(LIB, "untrash-cloudlink")
REF = os.path.join(HERE, "mesh-directory-ref")
fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += not ok


W = tempfile.mkdtemp(prefix="ut-cloudlink-")
SIG = os.path.join(W, "zt-sig")
subprocess.run(["gcc", "-O2", "-I" + os.path.join(OS, "third_party/tweetnacl"), "-o", SIG,
                os.path.join(OS, "slot/zt-sig.c"), os.path.join(OS, "third_party/tweetnacl/tweetnacl.c")], check=True)
BASE = 29400 + os.getpid() % 500 * 8
DIR_PORT, CL_PORT = BASE + 6, BASE + 7
NODES, PROCS = {}, []
for i, n in enumerate("ab"):
    d = os.path.join(W, n)
    os.makedirs(d)
    open(d + "/ep", "w").write("192.168.1.%d:51820" % (10 + i))
    open(d + "/hosts", "w").write("127.0.0.1\tlocalhost\n")
    open(d + "/addrmap", "w").write("{}")
    NODES[n] = {"env": dict(os.environ, ZT_MESH_DIR=d + "/state", ZT_SIG=SIG, ZT_MESH_FAKE_WG=d + "/wg.json",
                            ZT_MESH_ADDRMAP=d + "/addrmap", ZT_MESH_JOIN_HOST="127.0.0.1", ZT_MESH_ENDPOINTS=d + "/ep",
                            ZT_MESH_SYNC_PORT=str(BASE + 2 * i), ZT_MESH_JOIN_PORT=str(BASE + 2 * i + 1),
                            ZT_MESH_HOSTS=d + "/hosts", ZT_MESH_TICK="0.5", ZT_MESH_DIR_EVERY="1",
                            ZT_UPNPC="/nonexistent/upnpc", ZT_MESH_SMB=d + "/smb-mesh.conf", ZT_MESH_PDATA=d + "/p-data",
                            ZT_MESH_FAKE_MOUNT=d + "/mounts.json", ZT_MESH_FAKE_ACCOUNTS=d + "/accounts.json",
                            ZT_MESH_FAKE_DRBD=d + "/drbd.json", ZT_MESH_HOST_MNT=d + "/no-host"),
                "dir": d}
CD = os.path.join(W, "cloud")
os.makedirs(CD)
CENV = dict(os.environ, ZT_MESH_DIR=CD + "/state", ZT_SIG=SIG, ZT_MESH_DIR_URL="http://127.0.0.1:%d/" % DIR_PORT,
            ZT_MESH_FAKE_WG=CD + "/wg.json", ZT_MESH_HOSTS=CD + "/hosts", ZT_MESH_ADDRMAP=CD + "/addrmap",
            ZT_DIR_TEST_YOU="198.51.100.7")
open(CD + "/hosts", "w").write("")
open(CD + "/addrmap", "w").write("{}")


def cli(n, *a):
    r = subprocess.run([TOOL] + list(a), env=NODES[n]["env"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": r.stdout}


def ref(*a):
    r = subprocess.run([REF] + list(a), env=CENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": r.stdout}


def spawn(cmd, env, log):
    p = subprocess.Popen(cmd, env=env, stdout=open(log, "a"), stderr=subprocess.STDOUT)
    PROCS.append(p)
    return p


def wait(cond, secs=15):
    t = time.time()
    while time.time() - t < secs:
        if cond():
            return True
        time.sleep(0.3)
    return False


def jf(path):
    try:
        return json.load(open(path))
    except (OSError, ValueError):
        return {}


def addrmap(reach):
    st = {n: cli(n, "status") for n in NODES}
    for n in NODES:
        m = {st[o]["address"]: "127.0.0.1:%d" % (BASE + 2 * "ab".index(o)) for o in reach[n]}
        open(NODES[n]["dir"] + "/addrmap", "w").write(json.dumps(m))


def call(path, auth=True, header=None, method="GET"):
    """(status, JSON) of an untrash-cloudlink request, signed by the cloud."""
    hdr = {}
    if auth:
        hdr["Authorization"] = header or subprocess.run([REF, "sign", method, path], env=CENV, stdout=subprocess.PIPE,
                                                        text=True).stdout.strip()
    try:
        with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d%s" % (CL_PORT, path), headers=hdr),
                                    timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")
    except (OSError, urllib.error.URLError):
        return 0, {}


try:
    # ---------------------------------------------------------------- mesh
    sa = cli("a", "create", "home")
    cli("a", "rename", "nas-a")
    cli("b", "rename", "nas-b")
    spawn([TOOL, "run"], NODES["a"]["env"], NODES["a"]["dir"] + "/log")
    time.sleep(1.5)
    sb = cli("b", "join", cli("a", "invite")["invitation"])
    check("nas-b joins", sb.get("mesh", {}).get("id") == sa["mesh"]["id"])
    na, nb = sa["node"], sb["node"]

    inv = cli("a", "invite-cloud", "1", json.dumps(["Photos"]))
    check("cloud invitation", "invitation" in inv)
    fresh = dict(NODES["b"]["env"], ZT_MESH_DIR=os.path.join(W, "fresh"), ZT_MESH_FAKE_WG=os.path.join(W, "fresh-wg.json"))
    r = subprocess.run([TOOL, "join", inv["invitation"]], env=fresh, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    check("a NAS cannot join with a cloud invitation", '"error"' in r.stdout and "refused" in r.stdout)
    subprocess.run([TOOL, "rename", "nextcloud"], env=dict(CENV, ZT_MESH_KIND="cloud"), stdout=subprocess.DEVNULL)
    bad = ref("join", cli("a", "invite")["invitation"])
    check("a cloud cannot join with a NAS invitation", "error" in bad)
    sc = ref("join", inv["invitation"])
    nc = sc.get("node")
    check("cloud joins with the cloud invitation", sc.get("mesh", {}).get("id") == sa["mesh"]["id"])
    spawn([REF, "run", str(DIR_PORT)], CENV, CD + "/log")
    addrmap({"a": "b", "b": "a"})
    spawn([TOOL, "run"], NODES["b"]["env"], NODES["b"]["dir"] + "/log")

    mc = [m for m in cli("a", "status")["members"] if m["node"] == nc]
    check("roster: kind cloud, its directory URL, the linked shares", mc and mc[0]["kind"] == "cloud"
          and mc[0]["dir"] == CENV["ZT_MESH_DIR_URL"] and mc[0]["shares"] == ["Photos"])
    check("clouds.json on a links the cloud to Photos", jf(NODES["a"]["dir"] + "/state/clouds.json").get(nc, {}).get("shares") == ["Photos"])
    check("the roster with 3 members reaches nas-b", wait(lambda: len(cli("b", "status")["members"]) == 3))
    check("... and the directory (pushed over HTTPS, signed)", wait(lambda: len(
        (jf(CD + "/state/mesh.json").get("roster") or {}).get("members", {})) == 3))
    check("the directory holds the records of both NAS", wait(lambda: {na, nb} <= set(jf(CD + "/state/book.json"))))
    peers_a = jf(NODES["a"]["dir"] + "/wg.json").get("peers", {})
    check("no WireGuard peer for the cloud (only nas-b)", wait(lambda: len(jf(NODES["a"]["dir"] + "/wg.json").get("peers", {})) == 1))
    check("no nextcloud.mesh name in /etc/hosts", wait(lambda: "nas-b.mesh" in open(NODES["a"]["dir"] + "/hosts").read())
          and "nextcloud.mesh" not in open(NODES["a"]["dir"] + "/hosts").read())
    check("the IP the directory saw becomes a last endpoint", wait(lambda: (jf(NODES["a"]["dir"] + "/state/book.json")
                                                                           .get(na, {}).get("ep") or [""])[-1] == "198.51.100.7:51820"))
    check("the cloud counts as online (directory reached)", wait(lambda: any(
        m["node"] == nc and m["online"] for m in cli("a", "status")["members"])))

    # recovery: a and b lose each other (no handshakes in the fake WireGuard);
    # b moves; a learns b's new endpoint from the directory only
    addrmap({"a": "", "b": ""})
    seq0 = jf(NODES["a"]["dir"] + "/state/book.json").get(nb, {}).get("seq", 0)
    open(NODES["b"]["dir"] + "/ep", "w").write("10.99.0.2:51820")
    check("lost member: a learns b's new endpoint through the directory", wait(lambda: "10.99.0.2:51820" in
          jf(NODES["a"]["dir"] + "/state/book.json").get(nb, {}).get("ep", []) and
          jf(NODES["a"]["dir"] + "/state/book.json")[nb]["seq"] > seq0, 25))
    check("... and a's WireGuard peer of b has it", wait(lambda: any("10.99.0.2:51820" in p.get("eps", [])
          for p in jf(NODES["a"]["dir"] + "/wg.json").get("peers", {}).values())))
    addrmap({"a": "b", "b": "a"})

    # forged directory request: signed by nobody of the mesh
    body = {"items": [], "have": {}, "roster": 0, "from": nb, "ts": int(time.time()), "nonce": "00" * 16, "sig": "11" * 64}
    try:
        urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/v1/sync" % DIR_PORT,
                                                      data=json.dumps(body).encode()), timeout=5)
        code = 200
    except urllib.error.HTTPError as e:
        code = e.code
    check("reference directory refuses a request with a wrong signature", code == 403)

    # ---------------------------------------------------------------- cloudlink
    R = os.path.join(W, "root")
    for s in ("Photos", "Music"):
        os.makedirs(R + "/i-data/v1/" + s)
    os.makedirs(R + "/etc/untrash/zyxel/stock-config")
    open(R + "/etc/untrash-version", "w").write("1.3-test\n")
    db = sqlite3.connect(R + "/etc/untrash/zyxel/stock-config/ugs_conf.db")
    db.execute("CREATE TABLE smb_share (s_name, s_path, s_enable)")
    db.executemany("INSERT INTO smb_share VALUES (?,?,?)", [("Photos", "/i-data/v1/Photos", "y"),
                                                            ("Music", "/i-data/v1/Music", "y"), ("Old", "/i-data/v1/Old", "n")])
    db.commit()
    db.close()
    feed = os.path.join(W, "feed")
    open(feed, "w").close()
    json.dump({"disks": [{"name": "sda", "asleep": True, "temp": None}], "raid": []}, open(W + "/health.json", "w"))
    clenv = dict(NODES["a"]["env"], ZT_CLOUDLINK_ROOT=R, ZT_CLOUDLINK_PORT=str(CL_PORT), ZT_CLOUDLINK_FAKE_FEED=feed,
                 ZT_CLOUDLINK_FAKE_HEALTH=W + "/health.json")
    spawn([CLOUDLINK, "run"], clenv, W + "/cloudlink.log")
    wait(lambda: call("/v1/info", auth=False)[0] == 401, 10)

    def feed_add(*lines):
        with open(feed, "a") as f:
            f.write("".join(l + "\n" for l in lines))

    P = R + "/i-data/v1/Photos/"
    check("unsigned request: 401", call("/v1/info", auth=False)[0] == 401)
    hdr = subprocess.run([REF, "sign", "GET", "/v1/info"], env=CENV, stdout=subprocess.PIPE, text=True).stdout.strip()
    check("signed for another path: 401", call("/v1/health", header=hdr)[0] == 401)
    check("signed request: 200", call("/v1/info", header=hdr)[0] == 200)
    check("the same nonce again: 401 (replay)", call("/v1/info", header=hdr)[0] == 401)
    benv = dict(CENV, ZT_MESH_DIR=NODES["b"]["dir"] + "/state")
    hb = subprocess.run([REF, "sign", "GET", "/v1/info"], env=benv, stdout=subprocess.PIPE, text=True).stdout.strip()
    check("signed by a NAS member, not a linked cloud: 401", call("/v1/info", header=hb)[0] == 401)
    old = hdr.replace("ts=%s" % hdr.split("ts=")[1].split(",")[0], "ts=%d" % (time.time() - 600))
    check("old timestamp: 401", call("/v1/info", header=old)[0] == 401)

    code, info = call("/v1/info")
    check("info: api 1, version, only the linked share", code == 200 and info["api"] == 1 and info["version"] == "1.3-test"
          and [s["name"] for s in info["shares"]] == ["Photos"] and info["shares"][0]["webdav"] == "/webdav/Photos" and info["shares"][0]["feed"]
          and info["node"] == na)
    code, ch = call("/v1/changes?since=")
    check("changes without cursor: rescan of Photos, a cursor", ch.get("rescan") == ["Photos"] and ch.get("cursor"))
    cur = ch["cursor"]
    feed_add(P + "2026/a.jpg", R + "/i-data/v1/Music/x.mp3", P + ".untrash-recycle/old.jpg", P + "2026/a.jpg", P + "2026")
    time.sleep(0.5)
    code, ch = call("/v1/changes?since=" + cur)
    check("changes: Photos only, recycle bin hidden, de-duplicated", ch.get("changes") == [
        {"share": "Photos", "path": "2026/a.jpg"}, {"share": "Photos", "path": "2026"}] and ch.get("rescan") == [])
    cur = ch["cursor"]
    t0 = time.time()
    code, ch = call("/v1/changes?since=%s&wait=1.5" % cur)
    check("long poll without changes: empty after the wait", ch.get("changes") == [] and 1.2 < time.time() - t0 < 5
          and ch["cursor"] == cur)
    threading.Timer(0.7, feed_add, args=(P + "b.jpg",)).start()
    t0 = time.time()
    code, ch = call("/v1/changes?since=%s&wait=20" % cur)
    check("long poll: answers as soon as a change comes", ch.get("changes") == [{"share": "Photos", "path": "b.jpg"}]
          and time.time() - t0 < 5)
    cur = ch["cursor"]
    feed_add("!overflow " + R + "/i-data/v1")
    time.sleep(0.5)
    code, ch = call("/v1/changes?since=" + cur)
    check("queue overflow on the volume: rescan of Photos", ch.get("rescan") == ["Photos"])
    code, ch = call("/v1/changes?since=0badc0de-5")
    check("cursor of another service run: rescan", ch.get("rescan") == ["Photos"])
    code, h = call("/v1/health")
    check("health: disks (asleep), volume of the linked share", code == 200 and h["disks"][0]["asleep"]
          and h["volumes"] and h["volumes"][0]["shares"] == ["Photos"] and h["volumes"][0]["size"] > 0)

    r = cli("a", "cloud-link", nc, json.dumps(["Photos", "Music"]))
    check("cloud-link: Music added", [m for m in r.get("members", []) if m["node"] == nc][0]["shares"] == ["Music", "Photos"])
    code, info = call("/v1/info")
    check("info now lists both shares", sorted(s["name"] for s in info["shares"]) == ["Music", "Photos"])
    check("cloud-link refuses a NAS member", "error" in cli("a", "cloud-link", nb, "[]"))
    check("cloud-link refuses bad share names", "error" in cli("a", "cloud-link", nc, '["../etc"]'))

    cli("a", "remove", nc)
    check("removed cloud: its link goes", wait(lambda: nc not in jf(NODES["a"]["dir"] + "/state/clouds.json")))
    check("removed cloud: cloudlink refuses it", wait(lambda: call("/v1/info")[0] == 401))
    check("the directory hears of the removal", wait(lambda: nc not in (jf(CD + "/state/mesh.json").get("roster") or {})
                                                     .get("members", {nc: 1})))
    check("... and drops its address book", wait(lambda: jf(CD + "/state/book.json") == {}))
finally:
    for p in PROCS:
        p.terminate()
    for p in PROCS:
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()
    if fails:
        print("logs kept in", W)
    else:
        shutil.rmtree(W, ignore_errors=True)

print("%d failed" % fails if fails else "all ok")
sys.exit(1 if fails else 0)
