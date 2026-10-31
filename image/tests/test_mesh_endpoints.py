#!/usr/bin/env python3
"""PC test: which endpoints untrash-mesh announces in its node record.

  python3 image/tests/test_mesh_endpoints.py

The router's external address is announced when the UPnP forward worked
(first) and also when the router refused it (last: the port may be
forwarded by hand; a phone on mobile data has no other way in). LAN and
carrier-grade NAT addresses are never announced as public.
"""
import importlib.machinery
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
OS = os.path.abspath(os.path.join(HERE, "..", ".."))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-mesh")
fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += not ok


w = tempfile.mkdtemp(prefix="ut-mesh-ep-")
try:
    sig = os.path.join(w, "zt-sig")
    subprocess.run(["gcc", "-O2", "-I" + os.path.join(OS, "third_party/tweetnacl"), "-o", sig,
                    os.path.join(OS, "slot/zt-sig.c"), os.path.join(OS, "third_party/tweetnacl/tweetnacl.c")], check=True)
    os.environ.update(ZT_MESH_DIR=w + "/state", ZT_SIG=sig, ZT_MESH_FAKE_WG=w + "/wg.json",
                      ZT_MESH_ENDPOINTS="192.168.1.20:51820", ZT_MESH_HOSTS=w + "/hosts")
    loader = importlib.machinery.SourceFileLoader("mesh", TOOL)
    m = types.ModuleType("mesh")
    loader.exec_module(m)
    now = int(time.time())

    def eps(upnp, observed=None):
        st = {"name": "nas", "upnp": upnp, "observed": observed or {}}
        if os.path.exists(w + "/state/book.json"):
            os.remove(w + "/state/book.json")
        return m.own_record(st)[0]["ep"]

    check("forward worked: external address right after the LAN ones",
          eps({"ok": True, "ext": "91.0.0.7", "t": now}) == ["192.168.1.20:51820", "91.0.0.7:51820"])
    check("forward refused: external address still announced, last",
          eps({"ok": False, "ext": "91.0.0.7", "t": now}, {"x": {"ep": "91.0.0.7:41000", "t": now}})
          == ["192.168.1.20:51820", "91.0.0.7:41000", "91.0.0.7:51820"])
    check("router behind a router (LAN external address): not announced",
          eps({"ok": False, "ext": "192.168.0.2", "t": now}) == ["192.168.1.20:51820"])
    check("carrier-grade NAT (100.64/10): not announced", eps({"ok": False, "ext": "100.70.1.2", "t": now}) == ["192.168.1.20:51820"])
    check("stale router answer (over 2 h): not announced", eps({"ok": False, "ext": "91.0.0.7", "t": now - 8000}) == ["192.168.1.20:51820"])
    check("no router: LAN only", eps({"ok": False, "t": now}) == ["192.168.1.20:51820"])
finally:
    shutil.rmtree(w, ignore_errors=True)
print("MESH ENDPOINTS TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", fails))
sys.exit(1 if fails else 0)
