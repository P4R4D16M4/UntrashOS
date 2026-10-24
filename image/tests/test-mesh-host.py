#!/usr/bin/env python3
"""PC test of untrash-mesh: three nodes, roster, address book, gossip.

  python3 image/tests/test-mesh-host.py

Three daemons on 127.0.0.1 (each with its own state directory, sync and join
port); WireGuard is a JSON file per node (ZT_MESH_FAKE_WG), mesh addresses
map to the local ports (ZT_MESH_ADDRMAP).  Checked: create, invite, join
(one-time, bound to the secret), roster spreads, an endpoint change reaches
every member (directly and, when the changed node cannot reach one, through
a third), observed public endpoint, /etc/hosts names, removal, and forged
records or rosters are refused.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OS = os.path.abspath(os.path.join(HERE, "..", ".."))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-mesh")
fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += not ok


W = tempfile.mkdtemp(prefix="ut-mesh-")
SIG = os.path.join(W, "zt-sig")
subprocess.run(["gcc", "-O2", "-I" + os.path.join(OS, "third_party/tweetnacl"), "-o", SIG,
                os.path.join(OS, "slot/zt-sig.c"), os.path.join(OS, "third_party/tweetnacl/tweetnacl.c")], check=True)
BASE = 27400 + os.getpid() % 500 * 6
NODES = {}
for i, n in enumerate("abc"):
    d = os.path.join(W, n)
    os.makedirs(d)
    open(d + "/ep", "w").write("192.168.1.%d:51820" % (10 + i))
    open(d + "/hosts", "w").write("127.0.0.1\tlocalhost\n")
    NODES[n] = {"env": dict(os.environ, ZT_MESH_DIR=d + "/state", ZT_SIG=SIG, ZT_MESH_FAKE_WG=d + "/wg.json",
                            ZT_MESH_ADDRMAP=d + "/addrmap", ZT_MESH_JOIN_HOST="127.0.0.1", ZT_MESH_ENDPOINTS=d + "/ep",
                            ZT_MESH_SYNC_PORT=str(BASE + 2 * i), ZT_MESH_JOIN_PORT=str(BASE + 2 * i + 1),
                            ZT_MESH_HOSTS=d + "/hosts", ZT_MESH_TICK="0.5", ZT_MESH_TEST_SELF="203.0.113.%d:41000" % (10 + i),
                            # never the real router: a's router is the stand-in, b and c have none
                            ZT_UPNPC=os.path.join(HERE, "fake-upnpc") if n == "a" else "/nonexistent/upnpc",
                            ZT_FAKE_UPNP_STATE=d + "/router.json",
                            ZT_MESH_SMB=d + "/smb-mesh.conf", ZT_MESH_PDATA=d + "/p-data", ZT_MESH_FAKE_MOUNT=d + "/mounts.json",
                            ZT_MESH_FAKE_ACCOUNTS=d + "/accounts.json", ZT_MESH_FAKE_DRBD=d + "/drbd.json",
                            ZT_MESH_HOST_MNT=d + "/no-host"),
                "dir": d, "proc": None}


def cli(n, *a):
    r = subprocess.run([TOOL] + list(a), env=NODES[n]["env"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": r.stdout}


def start(n):
    NODES[n]["proc"] = subprocess.Popen([TOOL, "run"], env=NODES[n]["env"], stdout=open(NODES[n]["dir"] + "/log", "a"), stderr=subprocess.STDOUT)


def addrmap(reach):
    """Each node's view: which mesh addresses it can reach (and on which port)."""
    st = {n: cli(n, "status") for n in NODES}
    for n in NODES:
        m = {st[o]["address"]: "127.0.0.1:%d" % (BASE + 2 * "abc".index(o)) for o in reach[n] if st[o].get("address")}
        open(NODES[n]["dir"] + "/addrmap", "w").write(json.dumps(m))


def wait(cond, secs=15):
    t = time.time()
    while time.time() - t < secs:
        if cond():
            return True
        time.sleep(0.3)
    return False


def book(n):
    try:
        return json.load(open(NODES[n]["dir"] + "/state/book.json"))
    except (OSError, ValueError):
        return {}


try:
    sa = cli("a", "create", "home")
    check("create: mesh, admin, ULA address", sa.get("mesh", {}).get("name") == "home" and sa["admin"] and sa["address"].startswith("fd"))
    for n in "bc":
        cli(n, "rename", "nas-" + n)
    cli("a", "rename", "nas-a")
    inv = cli("a", "invite")["invitation"]
    start("a")
    time.sleep(1.5)
    sb = cli("b", "join", inv)
    check("join with the invitation: member, same mesh", sb.get("mesh", {}).get("id") == sa["mesh"]["id"] and not sb["admin"])
    check("an invitation works once", "error" in cli("c", "join", inv))   # refused at once (HTTP 403), no retry
    check("a damaged invitation is refused", "error" in cli("c", "join", inv[:-6] + "AAAAAA"))
    inv2 = cli("a", "invite")["invitation"]
    sc = cli("c", "join", inv2)
    check("third node joins", sc.get("mesh", {}).get("id") == sa["mesh"]["id"])
    addrmap({"a": "bc", "b": "ac", "c": "ab"})
    start("b"); start("c")
    check("roster with 3 members reaches every node", wait(lambda: all(len(cli(n, "status")["members"]) == 3 for n in "abc")))
    check("every node has every record (address book)", wait(lambda: all(len(book(n)) == 3 for n in "abc")))
    check("WireGuard peers: the two others, with their mesh /128 and endpoint", wait(lambda: all(
        len(json.load(open(NODES[n]["dir"] + "/wg.json"))["peers"]) == 2 for n in "abc")))
    hosts = open(NODES["c"]["dir"] + "/hosts").read()
    check("names: nas-a.mesh and nas-b.mesh in /etc/hosts of c", "nas-a.mesh" in hosts and "nas-b.mesh" in hosts and "localhost" in hosts)
    check("observed public endpoint is published", wait(lambda: any("203.0.113." in e for e in book("a").get(cli("b", "status")["node"], {}).get("ep", []))))

    na = cli("a", "status")["node"]
    router = json.load(open(NODES["a"]["dir"] + "/router.json"))
    check("UPnP: the router forwards UDP 51820 to a", any(m[0] == "UDP" and m[1] == 51820 for m in router["maps"]))
    check("UPnP: the router's external address is a public endpoint of a", wait(lambda: "203.0.113.5:51820" in book("b").get(na, {}).get("ep", [])))
    check("UPnP: no join port forwarded without a pending invitation", wait(lambda: not any(
        m[1] == BASE + 1 for m in json.load(open(NODES["a"]["dir"] + "/router.json"))["maps"])))

    # b gets a new address; b can reach a, but not c (c learns it through a)
    nb = cli("b", "status")["node"]
    seq0 = book("c").get(nb, {}).get("seq", 0)
    addrmap({"a": "bc", "b": "a", "c": "ab"})
    open(NODES["b"]["dir"] + "/ep", "w").write("10.20.30.40:51820")
    check("endpoint change: new record with a higher seq at a (pushed)", wait(lambda: "10.20.30.40:51820" in book("a").get(nb, {}).get("ep", [])))
    check("... and at c, which b cannot reach (forwarded by a)", wait(lambda: "10.20.30.40:51820" in book("c").get(nb, {}).get("ep", [])
                                                                        and book("c")[nb]["seq"] > seq0))
    check("c's WireGuard peer of b knows the new endpoint", wait(lambda: any("10.20.30.40:51820" in p.get("eps", [])
                                                                          for p in json.load(open(NODES["c"]["dir"] + "/wg.json"))["peers"].values())))

    # forged data
    st_a = json.load(open(NODES["a"]["dir"] + "/state/book.json"))
    forged = dict(st_a[nb], ep=["6.6.6.6:51820"], seq=st_a[nb]["seq"] + 5)
    url = "http://127.0.0.1:%d/v1/sync" % BASE
    urllib.request.urlopen(urllib.request.Request(url, data=json.dumps({"items": [forged], "have": {}}).encode()), timeout=5).read()
    check("a record with a wrong signature is refused", "6.6.6.6:51820" not in book("a")[nb]["ep"])
    ros = json.load(open(NODES["b"]["dir"] + "/state/mesh.json"))["roster"]
    fake = dict(ros, seq=ros["seq"] + 10, by=nb)            # b is no admin
    urllib.request.urlopen(urllib.request.Request(url, data=json.dumps({"items": [fake], "have": {}}).encode()), timeout=5).read()
    check("a roster signed by a non-admin is refused", json.load(open(NODES["a"]["dir"] + "/state/mesh.json"))["roster"]["seq"] == ros["seq"])
    check("only admins invite", "error" in cli("b", "invite"))

    # co-op mode: a offers "Photos" read-only to b; b mounts it as a partner volume
    def jf(n, f):
        try:
            return json.load(open(NODES[n]["dir"] + "/" + f))
        except (OSError, ValueError):
            return {}
    nc = cli("c", "status")["node"]
    r = cli("a", "share", nb, json.dumps({"Photos": {"mode": "ro", "path": "/i-data/v1/Photos"}}))
    check("co-op: offer recorded at a", r.get("offers", {}).get(nb) == {"Photos": "ro"})
    smb = open(NODES["a"]["dir"] + "/smb-mesh.conf").read()
    acct = "mesh-" + nb[:8]
    check("co-op: Samba section only from the mesh prefix, b's account read-only",
          "[ut-mesh-Photos]" in smb and "path = /i-data/v1/Photos" in smb and "hosts allow = fd" in smb and "hosts deny = ALL" in smb
          and "valid users = %s" % acct in smb and "read list = %s" % acct in smb)
    check("co-op: Samba account for b made", acct in jf("a", "accounts.json"))
    mp = NODES["b"]["dir"] + "/p-data/nas-a-Photos"
    check("co-op: b mounts it as partner volume nas-a-Photos", wait(lambda: mp in jf("b", "mounts.json")))
    mnt = jf("b", "mounts.json").get(mp, {})
    check("co-op: mounted from a's mesh address with b's account", mnt.get("source") == "//%s/ut-mesh-Photos" % sa["address"]
          and mnt.get("user") == acct and mnt.get("password") == jf("a", "accounts.json")[acct])
    pv = cli("b", "status")["partner_volumes"]
    check("co-op: partner volume listed (read-only, mounted)", pv and pv[0]["mode"] == "ro" and pv[0]["mounted"] and pv[0]["partner"] == "nas-a")
    cli("a", "share", nc, json.dumps({"Photos": {"mode": "rw", "path": "/i-data/v1/Photos"}}))
    smb = open(NODES["a"]["dir"] + "/smb-mesh.conf").read()
    check("co-op: second partner c read/write in the same section", "mesh-%s" % nc[:8] in smb and "read list = %s\n" % acct in smb)
    cli("a", "share", nb, "{}")
    check("co-op: withdrawn: b unmounts", wait(lambda: mp not in jf("b", "mounts.json")))
    check("co-op: withdrawn: b's account and Samba rights gone at a", wait(lambda: acct not in jf("a", "accounts.json")
                                                                          and acct not in open(NODES["a"]["dir"] + "/smb-mesh.conf").read()))
    check("co-op: a member cannot offer to itself / unknown nodes", "error" in cli("a", "share", sa["node"], "{}") and "error" in cli("a", "share", "0" * 16, "{}"))

    # off-site mirror: a asks b to keep a copy of its volume /i-data/v1 (DRBD faked)
    VOL, SIZE = "/i-data/v1", 64 << 20
    json.dump({"mounts": {VOL: "/dev/vg/lv_v1"}, "sizes": {"/dev/vg/lv_v1": SIZE}}, open(NODES["a"]["dir"] + "/drbd.json", "w"))
    def drbdf(n):
        return jf(n, "drbd.json")
    r = cli("a", "mirror-start", VOL, "Data", nb)
    mo = (r.get("mirrors") or [{}])[0]
    mid = mo.get("id", "")
    check("mirror: request recorded at a (size from the device)", mo.get("state") == "requested" and mo.get("size") == SIZE and mo.get("peer") == nb)
    check("mirror: b sees the request and must agree", wait(lambda: any(c["id"] == mid and c["state"] == "pending" for c in cli("b", "status").get("mirror_copies", []))))
    check("mirror: the same volume cannot be mirrored twice", "error" in cli("a", "mirror-start", VOL, "Data", nc))
    check("mirror: not mounted through DRBD before the partner agreed", cli("a", "mirror-up", "/dev/vg/lv_v1", VOL) == {"device": None})
    bvol = NODES["b"]["dir"] + "/vol"
    os.makedirs(bvol)
    r = cli("b", "mirror-accept", mid, bvol)
    img = bvol + "/.untrash-mirror/%s.img" % mid
    check("mirror: b keeps the copy in a sparse file of the volume's size", os.path.getsize(img) == SIZE and os.stat(img).st_blocks == 0)
    check("mirror: b's copy is up as DRBD secondary (metadata once)", wait(lambda: drbdf("b").get("res", {}).get("ut-" + mid, {}).get("log", [])[:2] == ["create-md --force", "up"]))
    check("mirror: a learns the consent", wait(lambda: cli("a", "status")["mirrors"][0]["state"] == "accepted"))
    r = cli("a", "mirror-up", "/dev/vg/lv_v1", VOL)
    om = cli("a", "status")["mirrors"][0]
    check("mirror: at the next mount a mounts /dev/drbdN", r.get("device") == "/dev/drbd%d" % om["minor"])
    res = drbdf("a")["res"]["ut-" + mid]
    check("mirror: first start: metadata, up, primary --force", res["log"] == ["create-md --force", "up", "primary --force"])
    conf = open(NODES["a"]["dir"] + "/state/drbd/%s.conf" % mid).read()
    sb = cli("b", "status")
    check("mirror: config: protocol A, pull-ahead, both mesh addresses, the volume as disk, meta on a loop file",
          "protocol A;" in conf and "on-congestion pull-ahead" in conf and "[%s]:%d" % (sa["address"], om["port"]) in conf
          and "[%s]:%d" % (sb["address"], om["peer_port"]) in conf and "disk /dev/vg/lv_v1;" in conf and "meta-disk /dev/loop-fake" in conf)
    check("mirror: DRBD metadata in a file outside the volume", os.path.exists(NODES["a"]["dir"] + "/state/mirror/%s.meta" % mid))
    # next boot: no new metadata, no --force
    d = drbdf("a"); d["res"]["ut-" + mid].update(cs="Unconfigured", log=[]); json.dump(d, open(NODES["a"]["dir"] + "/drbd.json", "w"))
    cli("a", "mirror-up", "/dev/vg/lv_v1", VOL)
    check("mirror: later starts: up and primary only", drbdf("a")["res"]["ut-" + mid]["log"] == ["up", "primary"])
    # a boot where DRBD fails: mounted directly, copy marked for a full resync
    d = drbdf("a"); d["res"]["ut-" + mid].update(cs="Unconfigured", md=False, log=[]); json.dump(d, open(NODES["a"]["dir"] + "/drbd.json", "w"))
    r = cli("a", "mirror-up", "/dev/vg/lv_v1", VOL)
    check("mirror: DRBD fails at boot: error, so the volume is mounted directly", "error" in r)
    check("mirror: and the copy is marked for a full resync", cli("a", "status")["mirrors"][0].get("bypassed") is True)
    d = drbdf("a"); d["res"]["ut-" + mid].update(md=True, log=[]); json.dump(d, open(NODES["a"]["dir"] + "/drbd.json", "w"))
    check("mirror: next boot works again", cli("a", "mirror-up", "/dev/vg/lv_v1", VOL).get("device", "").startswith("/dev/drbd"))
    d = drbdf("a"); d["res"]["ut-" + mid]["cs"] = "Connected"; json.dump(d, open(NODES["a"]["dir"] + "/drbd.json", "w"))
    check("mirror: once connected the daemon sends everything again (invalidate-remote)",
          wait(lambda: "invalidate-remote" in drbdf("a")["res"]["ut-" + mid]["log"] and not cli("a", "status")["mirrors"][0].get("bypassed")))
    check("mirror: status shows the live state", cli("a", "status")["mirrors"][0]["live"]["cs"] == "Connected")
    try:
        urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/v1/mirror" % (BASE + 2), data=json.dumps(
            {"type": "stop", "id": mid, "from": "0" * 16}).encode()), timeout=5).read()
        forged = False
    except urllib.error.HTTPError as e:
        forged = e.code == 403
    check("mirror: a stop from a non-member is refused", forged and os.path.exists(img))
    cli("a", "mirror-stop", mid)
    check("mirror: stop: b deletes its copy", wait(lambda: not os.path.exists(img) and not cli("b", "status")["mirror_copies"]))
    check("mirror: stop: a ends it at the next mount", wait(lambda: cli("a", "status")["mirrors"][0]["state"] == "stopped"))
    check("mirror: after the stop the volume is mounted directly", cli("a", "mirror-up", "/dev/vg/lv_v1", VOL) == {"device": None}
          and not cli("a", "status")["mirrors"])
    r = cli("a", "mirror-start", VOL, "Data", nb)
    mid2 = r["mirrors"][0]["id"]
    wait(lambda: cli("b", "status")["mirror_copies"])
    cli("b", "mirror-decline", mid2)
    check("mirror: decline: a sees it, b keeps nothing", wait(lambda: cli("a", "status")["mirrors"][0]["state"] == "declined")
          and not cli("b", "status")["mirror_copies"])
    r = cli("a", "mirror-start", VOL, "Data", nc)
    mid3 = next((o["id"] for o in r.get("mirrors") or [] if o["peer"] == nc), None)
    check("mirror: a declined request does not block a new one", "error" not in r)
    check("mirror: c gets the request", wait(lambda: cli("c", "status").get("mirror_copies")))
    cvol = NODES["c"]["dir"] + "/vol"
    os.makedirs(cvol)
    cli("c", "mirror-accept", mid3, cvol)
    check("mirror: c keeps a copy", wait(lambda: os.path.exists(cvol + "/.untrash-mirror/%s.img" % mid3)))

    # removal

    r = cli("a", "remove", nc)
    check("remove: c out of a's roster", len(r["members"]) == 2)
    check("b learns the removal", wait(lambda: len(cli("b", "status")["members"]) == 2))
    check("co-op: offers to a removed member go (account, Samba section)", wait(lambda: "mesh-%s" % nc[:8] not in jf("a", "accounts.json")
                                                                               and "ut-mesh-Photos" not in open(NODES["a"]["dir"] + "/smb-mesh.conf").read()))
    check("mirror: c removed: a's mirror to c ends, c deletes its copy",
          wait(lambda: any(o["id"] == mid3 and o["state"] == "partner-stopped" for o in cli("a", "status")["mirrors"])
               and not os.path.exists(cvol + "/.untrash-mirror/%s.img" % mid3)))
    check("c notices and leaves (no mesh, no WireGuard, no hosts block)", wait(lambda: not cli("c", "status")["mesh"]
                                                                              and not os.path.exists(NODES["c"]["dir"] + "/wg.json")
                                                                              and "untrash-mesh" not in open(NODES["c"]["dir"] + "/hosts").read()))
finally:
    for n in NODES.values():
        if n["proc"]:
            n["proc"].terminate()
            n["proc"].wait()
    if fails:
        for n in "abc":
            print("---- log %s" % n)
            print(open(NODES[n]["dir"] + "/log").read()[-2000:] if os.path.exists(NODES[n]["dir"] + "/log") else "")
    shutil.rmtree(W, ignore_errors=True)

print("MESH TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", fails))
sys.exit(1 if fails else 0)
