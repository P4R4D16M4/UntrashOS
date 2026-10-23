#!/usr/bin/env python3
"""PC test of untrash-iscsi against the host's real LIO (as root):
  sudo python3 image/tests/test-iscsi-host.py
Loads target_core_mod/target_core_file/iscsi_target_mod if needed (and
unloads them again), portal only on 127.0.0.1:13260.  Checks: thin and thick
LUN files in <volume>/.iscsi_Lun, two targets (initiator list + CHAP +
mutual CHAP; all initiators without CHAP), configfs objects, the portal
listens, LUN in use cannot be deleted, re-apply after a change, stop leaves
nothing behind, foreign targets untouched."""
import json
import os
import socket
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "lib", "untrash", "untrash-iscsi")
CFS = "/sys/kernel/config/target"
fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name, flush=True)
    fails += 0 if cond else 1


def rd(p):
    return open(p).read().strip()


def main():
    if os.geteuid():
        sys.exit("run as root")
    before = subprocess.run(["lsmod"], stdout=subprocess.PIPE, text=True).stdout
    loaded_here = "iscsi_target_mod" not in before
    subprocess.run(["modprobe", "-a", "target_core_mod", "target_core_file", "iscsi_target_mod"], check=True)
    os.makedirs(CFS + "/iscsi", exist_ok=True)
    W = tempfile.mkdtemp(prefix="zt-iscsi-")
    try:
        vol = W + "/i-data/aaaa0001"
        os.makedirs(vol)
        env = dict(os.environ, ZT_SETTINGS=W + "/settings.json", ZT_ISCSI_SECRETS=W + "/secrets.json",
                   ZT_ISCSI_PORTAL="127.0.0.1:13260")

        def cl(*a):
            r = subprocess.run([TOOL] + list(a), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return r.returncode, r.stdout + r.stderr
        rc, o = cl("create-lun", "lun1", vol, "2", "thin")
        rc2, o2 = cl("create-lun", "lun2", vol, "1", "thick")
        st1, st2 = os.stat(vol + "/.iscsi_Lun/lun1"), os.stat(vol + "/.iscsi_Lun/lun2")
        check("thin LUN sparse, thick LUN allocated", rc == 0 and rc2 == 0 and st1.st_size == 2 << 30 and st1.st_blocks == 0
              and st2.st_blocks * 512 >= 1 << 30)
        check("existing LUN file refused", cl("create-lun", "lun1", vol, "1", "thin")[0] != 0)
        t1, t2 = "iqn.2026-10.local.untrash:t1", "iqn.2026-10.local.untrash:t2"
        ini = "iqn.1993-08.org.debian:01:abcdef"
        cfg = {"iscsi": {"luns": [{"name": "lun1", "path": vol + "/.iscsi_Lun/lun1", "size_gb": 2, "write_cache": True},
                                  {"name": "lun2", "path": vol + "/.iscsi_Lun/lun2", "size_gb": 1}],
                         "targets": [{"name": "Eins", "iqn": t1, "luns": ["lun1", "lun2"], "initiators": [ini], "active": True},
                                     {"name": "Zwei", "iqn": t2, "luns": ["lun2"], "initiators": [], "active": True}]}}
        json.dump(cfg, open(W + "/settings.json", "w"))
        json.dump({t1: {"user": "u1", "password": "geheim123456", "mutual_user": "m1", "mutual_password": "anders123456"}},
                  open(W + "/secrets.json", "w"))
        # a foreign target that must survive
        os.makedirs(CFS + "/iscsi/iqn.2026-10.test.foreign:x/tpgt_1", exist_ok=True)
        rc, o = cl("apply")
        tp1, tp2 = CFS + "/iscsi/%s/tpgt_1" % t1, CFS + "/iscsi/%s/tpgt_1" % t2
        check("apply", rc == 0)
        check("backstores fileio with path and size", rd(CFS + "/core/fileio_77/lun1/enable") == "1" and
              vol + "/.iscsi_Lun/lun1" in rd(CFS + "/core/fileio_77/lun1/info"))
        check("target 1: 2 LUNs, only the initiator, CHAP + mutual", sorted(os.listdir(tp1 + "/lun")) == ["lun_0", "lun_1"] and
              rd(tp1 + "/attrib/generate_node_acls") == "0" and os.listdir(tp1 + "/acls") == [ini] and
              rd(tp1 + "/acls/%s/auth/userid" % ini) == "u1" and rd(tp1 + "/acls/%s/auth/userid_mutual" % ini) == "m1"
              and rd(tp1 + "/attrib/authentication") == "1" and rd(tp1 + "/enable") == "1")
        check("target 2: all initiators, no CHAP", rd(tp2 + "/attrib/generate_node_acls") == "1" and rd(tp2 + "/attrib/authentication") == "0")
        s = socket.create_connection(("127.0.0.1", 13260), 2)
        s.close()
        check("portal listens on 127.0.0.1:13260", True)
        check("LUN in use cannot be deleted", cl("delete-lun", "lun2")[0] != 0)
        cfg["iscsi"]["targets"][1]["active"] = False
        json.dump(cfg, open(W + "/settings.json", "w"))
        rc, o = cl("apply")
        check("re-apply: inactive target gone", rc == 0 and not os.path.exists(CFS + "/iscsi/" + t2) and os.path.isdir(tp1))
        st = json.loads(cl("status")[1])
        check("status", [t["running"] for t in st["targets"]] == [True, False] and st["luns"][0]["present"])
        check("stop", cl("stop")[0] == 0 and not os.path.exists(CFS + "/iscsi/" + t1) and not os.path.exists(CFS + "/core/fileio_77"))
        check("foreign target untouched", os.path.isdir(CFS + "/iscsi/iqn.2026-10.test.foreign:x/tpgt_1"))
        cfg["iscsi"]["targets"] = []
        json.dump(cfg, open(W + "/settings.json", "w"))
        check("delete LUN when unused", cl("delete-lun", "lun2")[0] == 0 and not os.path.exists(vol + "/.iscsi_Lun/lun2"))
    finally:
        subprocess.run([TOOL, "stop"], env=dict(os.environ, ZT_SETTINGS=W + "/settings.json"), stdout=subprocess.DEVNULL)
        for d in (CFS + "/iscsi/iqn.2026-10.test.foreign:x/tpgt_1", CFS + "/iscsi/iqn.2026-10.test.foreign:x"):
            if os.path.isdir(d):
                os.rmdir(d)
        subprocess.run(["rm", "-rf", W])
        if loaded_here:
            try:
                os.rmdir(CFS + "/iscsi")           # the fabric dir holds iscsi_target_mod
            except OSError:
                pass
            mods = ["iscsi_target_mod"] + sorted(l.split()[0] for l in open("/proc/modules") if l.startswith("target_core_") and l.split()[0] != "target_core_mod") + ["target_core_mod"]
            r = subprocess.run(["modprobe", "-r"] + mods + ([] if "uio " in before else ["uio"]),
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            check("modules unloaded again", r.returncode == 0)
    print("ISCSI HOST TEST %s (%d failures)" % ("PASS" if not fails else "FAIL", fails))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
