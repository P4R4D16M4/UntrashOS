#!/usr/bin/env python3
"""PC test: the Desk answers the UntrashApp on its UntrashMesh address.

  python3 image/tests/test-desk-mesh-host.py

The other Desk tests reach the app endpoints over 127.0.0.1
(ZT_MESH_ADDRMAP), which hid that the Desk listened on IPv4 only: the first
phone (2026-10-31) paired, brought its tunnel up and still reached no Desk.
This test runs in a network namespace of its own (unshare -rn, no root
needed) without ZT_MESH_ADDRMAP: the NAS and the app get their real mesh
addresses on lo, the app's signed request comes from its mesh address.

Checked: the Desk binds its mesh address as soon as a mesh exists, before
the address is on any interface (IPV6_FREEBIND); a signed app request over
IPv6 acts as the linked user; the same request from another address is
refused (mesh only); IPv4 keeps working; after leaving the mesh the
listener is gone.  Skipped (exit 0) where user namespaces are not allowed.
"""
import hashlib
import http.client
import importlib.machinery
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "rootfs")

if not os.environ.get("UT_IN_NETNS"):
    try:
        r = subprocess.run(["unshare", "-rn", sys.executable, os.path.abspath(__file__)],
                           env=dict(os.environ, UT_IN_NETNS="1"))
    except OSError:
        print("skip desk mesh test (no unshare)")
        sys.exit(0)
    if r.returncode == 99:
        print("skip desk mesh test (user namespaces not allowed)")
        sys.exit(0)
    sys.exit(r.returncode)

try:
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)
except (OSError, subprocess.CalledProcessError):
    sys.exit(99)

sys.path.insert(0, HERE)
_l = importlib.machinery.SourceFileLoader("desk_host", os.path.join(HERE, "test-desk-host.py"))
t = types.ModuleType("desk_host")
t.__file__ = _l.path
_l.exec_module(t)

fails = []


def check(name, ok):
    print(("ok   " if ok else "FAIL ") + name)
    if not ok:
        fails.append(name)


def mesh_address(mesh_id, pub):
    h = hashlib.sha256(("untrash-mesh:" + mesh_id).encode()).digest()
    iid = hashlib.sha256(bytes.fromhex(pub)).digest()[:8]
    import ipaddress
    return str(ipaddress.IPv6Address(b"\xfd" + h[:5] + b"\0\0" + iid))


def wait(f, tries=60):
    for _ in range(tries):
        if f():
            return True
        time.sleep(0.1)
    return False


def listening(addr, port):
    s = socket.socket(socket.AF_INET6)
    s.settimeout(0.5)
    try:
        s.connect((addr, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main():
    w = tempfile.mkdtemp(prefix="desk-mesh-")
    port = 8080
    r, stick = t.build_root(w)
    env = t.env_for(r, stick, port)
    env.pop("ZT_MESH_ADDRMAP")                  # the real address checks
    env.update(ZT_DESK_MESH_POLL="0.2")
    log = open(w + "/desk.log", "w")
    srv = subprocess.Popen([sys.executable, os.path.join(FILES, "usr/lib/untrash/untrash-desk")], env=env,
                           stdout=log, stderr=subprocess.STDOUT)
    try:
        def up():
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close()
                return True
            except OSError:
                return False
        wait(up, 150)
        a = t.Client(port)
        a.req("/api/login", {"user": "admin", "password": t.PW})
        check("no mesh: the Desk listens on IPv4 only", "UntrashMesh" not in open(w + "/desk.log").read())
        st, mj = a.req("/api/mesh/create", {"name": "home"})
        mdir = env["ZT_MESH_DIR"]
        mesh = json.load(open(mdir + "/mesh.json"))["mesh"]["id"]
        nas = mesh_address(mesh, open(mdir + "/node.pub", "rb").read().hex())
        check("mesh created: the Desk binds its mesh address before ut-mesh has it",
              st == 200 and wait(lambda: ("UntrashMesh [%s]:%d" % (nas, port)) in open(w + "/desk.log").read()))
        subprocess.run(["ip", "-6", "addr", "add", nas + "/128", "dev", "lo"], check=True)
        check("the mesh address answers once it is on the interface", wait(lambda: listening(nas, port)))

        # an app member linked to alice, with its own mesh address
        sig = os.path.join(r, "zt-sig")
        sec, pubf = os.path.join(w, "app.sec"), os.path.join(w, "app.pub")
        subprocess.run([sig, "keygen", sec, pubf], check=True)
        pub = open(pubf, "rb").read().hex()
        node = hashlib.sha256(bytes.fromhex(pub)).hexdigest()[:16]
        ms = json.load(open(mdir + "/mesh.json"))
        ms["roster"]["members"][node] = {"pub": pub, "wg": "x", "name": "phone", "role": "member", "kind": "app", "added": 1}
        json.dump(ms, open(mdir + "/mesh.json", "w"))
        check("app linked to alice", a.req("/api/mesh/app-link", {"node": node, "user": "alice"})[0] == 200)
        app = mesh_address(mesh, pub)
        subprocess.run(["ip", "-6", "addr", "add", app + "/128", "dev", "lo"], check=True)

        def signed(path, source):
            ts, nonce = str(int(time.time())), os.urandom(12).hex()
            msg = "\n".join(["UTAPP1", "GET", path, ts, nonce, hashlib.sha256(b"").hexdigest()]).encode()
            mf, sf = os.path.join(w, "m"), os.path.join(w, "s")
            open(mf, "wb").write(msg)
            subprocess.run([sig, "sign", sec, mf, sf], check=True)
            c = http.client.HTTPConnection(nas, port, timeout=5, source_address=(source, 0))
            c.request("GET", path, headers={"Authorization": "UntrashApp node=%s, ts=%s, nonce=%s, sig=%s"
                                            % (node, ts, nonce, open(sf, "rb").read().hex())})
            resp = c.getresponse()
            body = resp.read()
            c.close()
            try:
                return resp.status, json.loads(body)
            except ValueError:
                return resp.status, {}

        st, info = signed("/api/app/info", app)
        check("signed app request over the mesh address acts as alice", st == 200 and info.get("user") == "alice")
        st, rq = signed("/api/app/requests", app)
        check("app requests over the mesh address", st == 200 and rq.get("requests") == [])
        check("the same request from another address is refused (mesh only)", signed("/api/app/info", "::1")[0] == 401)
        check("IPv4 keeps working", a.req("/api/me")[1].get("user") == "admin")

        st, _ = a.req("/api/mesh/leave", {})
        check("mesh left: the mesh listener is gone", st == 200 and wait(lambda: not listening(nas, port)))
    finally:
        srv.terminate()
        srv.wait(10)
        shutil.rmtree(w, ignore_errors=True)
    print("DESK MESH TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", len(fails)))
    sys.exit(1 if fails else 0)


main()
