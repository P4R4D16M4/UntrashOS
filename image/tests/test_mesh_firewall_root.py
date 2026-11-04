#!/usr/bin/env python3
"""The cloud-peer filter of untrash-mesh (fw_ruleset) on a real kernel with
the real nft, in two network namespaces (needs sudo -n and nft):

  python3 image/tests/test_mesh_firewall_root.py

"nas" has the interface ut-mesh (a veth here instead of WireGuard), "cloud"
the other end with a cloud member's address and a NAS member's address.
Checked: the ruleset loads; from the cloud address TCP 5002 connects and
ping works, every other port (SSH, SMB, Desk, mesh sync) is dropped; from
the NAS member address the other ports are not filtered; without cloud
addresses the table is empty and nothing is filtered.
"""
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-mesh")
NFT = "/usr/sbin/nft"
os.environ["ZT_MESH_DIR"] = tempfile.mkdtemp(prefix="ut-fw-")
_l = importlib.machinery.SourceFileLoader("mesh_fw", TOOL)
_s = importlib.util.spec_from_loader("mesh_fw", _l)
mesh = importlib.util.module_from_spec(_s)
_l.exec_module(mesh)
fails = 0
NS = ("utfw-nas", "utfw-cloud")
CLOUD, NASMEMBER, NASADDR = "fd35:dba1:77af:0:aaaa::1", "fd35:dba1:77af:0:bbbb::1", "fd35:dba1:77af:0:cccc::1"


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name, flush=True)
    fails += not ok


def sh(*a, ns=None, input=None, check=True):
    cmd = ["sudo", "-n"] + (["ip", "netns", "exec", ns] if ns else []) + list(a)
    r = subprocess.run(cmd, input=input, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if check and r.returncode:
        raise RuntimeError("%s: %s" % (" ".join(a), r.stdout))
    return r


def connects(port, src):
    """TCP from the cloud namespace to the NAS address, from address src."""
    code = ("import socket,sys\ns=socket.socket(socket.AF_INET6)\ns.settimeout(2)\ns.bind((%r,0))\n"
            "try:\n s.connect((%r,%d)); print('open')\nexcept Exception as e: print('closed', e)") % (src, NASADDR, port)
    return sh("python3", "-c", code, ns=NS[1], check=False).stdout.startswith("open")


if not os.path.exists(NFT) or subprocess.run(["sudo", "-n", "true"]).returncode:
    sys.exit("needs %s and sudo -n" % NFT)
listeners = []
try:
    for n in NS:
        sh("ip", "netns", "add", n, check=False)
    sh("ip", "link", "add", "ut-mesh", "netns", NS[0], "type", "veth", "peer", "name", "peer0", "netns", NS[1])
    sh("ip", "-6", "addr", "add", NASADDR + "/48", "dev", "ut-mesh", "nodad", ns=NS[0])
    sh("ip", "link", "set", "ut-mesh", "up", ns=NS[0])
    sh("ip", "link", "set", "lo", "up", ns=NS[0])
    for a in (CLOUD, NASMEMBER):
        sh("ip", "-6", "addr", "add", a + "/48", "dev", "peer0", "nodad", ns=NS[1])
    sh("ip", "link", "set", "peer0", "up", ns=NS[1])
    for port in (5002, 22, 445, 80, 7340):
        listeners.append(subprocess.Popen(["sudo", "-n", "ip", "netns", "exec", NS[0], "python3", "-c",
                                           "import socket,time\ns=socket.socket(socket.AF_INET6)\ns.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)\n"
                                           "s.bind(('::',%d))\ns.listen(16)\nwhile True:\n c,_=s.accept(); c.close()" % port]))
    import time
    time.sleep(1)
    check("without a filter every port is open from the cloud address", all(connects(p, CLOUD) for p in (5002, 22, 7340)))

    r = sh(NFT, "-f", "-", ns=NS[0], input=mesh.fw_ruleset({CLOUD}), check=False)
    check("the ruleset of untrash-mesh loads in a real kernel (nft -f)", r.returncode == 0)
    if r.returncode:
        print(r.stdout)
    check("cloud address: TCP 5002 (WebDAV, untrash-cloudlink) connects", connects(5002, CLOUD))
    check("cloud address: SSH, SMB, the Desk and mesh sync are dropped", not any(connects(p, CLOUD) for p in (22, 445, 80, 7340)))
    check("cloud address: ping works (ICMPv6)", sh("ping", "-6", "-c1", "-W2", "-I", CLOUD, NASADDR, ns=NS[1], check=False).returncode == 0)
    check("a NAS member's address is not filtered", all(connects(p, NASMEMBER) for p in (22, 445, 7340)))
    r = sh(NFT, "-f", "-", ns=NS[0], input=mesh.fw_ruleset({CLOUD}), check=False)
    check("loading it again replaces the table (no error, no double rules)", r.returncode == 0
          and sh(NFT, "list", "ruleset", ns=NS[0]).stdout.count("@clouds drop") == 1)
    # fw_apply itself (the daemon's code path) against this namespace: a flush is noticed and repaired
    wrap = os.path.join(os.environ["ZT_MESH_DIR"], "nft-ns")
    open(wrap, "w").write("#!/bin/sh\nexec sudo -n ip netns exec %s %s \"$@\"\n" % (NS[0], NFT))
    os.chmod(wrap, 0o755)
    mesh.NFT, mesh.FAKE_NFT, mesh.log = wrap, None, lambda m: None
    mesh._FW.clear()
    check("fw_apply loads the filter (daemon code path)", mesh.fw_apply({CLOUD}) and not connects(22, CLOUD))
    sh(NFT, "flush", "ruleset", ns=NS[0])
    check("after \"nft flush ruleset\" the cloud is unfiltered ...", connects(22, CLOUD))
    check("... and the next fw_apply notices and loads it again", mesh.fw_apply({CLOUD}) and not connects(22, CLOUD)
          and connects(5002, CLOUD))
    r = sh(NFT, "-f", "-", ns=NS[0], input=mesh.fw_ruleset(set()), check=False)
    check("no cloud with a tunnel: the table goes, nothing is filtered", r.returncode == 0
          and "untrash_mesh" not in sh(NFT, "list", "ruleset", ns=NS[0]).stdout and connects(22, CLOUD))
    check("... and removing it twice is fine", sh(NFT, "-f", "-", ns=NS[0], input=mesh.fw_ruleset(set()), check=False).returncode == 0)
finally:
    for p in listeners:
        p.terminate()
    subprocess.run(["sudo", "-n", "pkill", "-f", "s.bind\\(\\('::'"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for n in NS:
        subprocess.run(["sudo", "-n", "ip", "netns", "del", n], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("%d failed" % fails if fails else "all ok")
sys.exit(1 if fails else 0)
