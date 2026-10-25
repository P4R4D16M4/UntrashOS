#!/usr/bin/env python3
"""PC test of image/tools/untrash-memd.c (proactive memory offloading) on a
fake /proc, /sys and cgroup tree (ZT_MEMD_ROOT); plain files stand in for
the kernel files, a helper thread raises the PSI counters.

- SSD swap, no pressure: reclaims from background/system/user slices, never
  from untrash-interactive.slice; vm.page-cluster 0; mode "ssd"
- pressure above a slice's target: that slice is left alone
- global brake (/proc/pressure/memory full): no reclaim at all
- rotational swap: mode "zswap" while the pool has room, "off" when it is
  nearly full; vm.page-cluster 3
- no swap: mode "off"
- no PSI / no memory cgroup: exits 0 at once
- SIGTERM: exit 0
"""
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "tools", "untrash-memd.c")
SLICES = ("untrash-background.slice", "system.slice", "user.slice", "untrash-interactive.slice")
MiB = 1024 * 1024
FAIL = 0


def check(name, ok):
    global FAIL
    print(("ok   " if ok else "FAIL ") + name, flush=True)
    FAIL += 0 if ok else 1


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def psi(total_some, total_full=0):
    return ("some avg10=0.00 avg60=0.00 avg300=0.00 total=%d\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=%d\n" % (total_some, total_full))


def fake_root(r, swap="ssd", zswap_bytes=0):
    os.makedirs(r + "/run")
    w(r + "/proc/pressure/memory", psi(0))
    w(r + "/proc/meminfo", "MemTotal:        1000000 kB\nMemFree:          100000 kB\n")
    w(r + "/proc/sys/vm/page-cluster", "3\n")
    w(r + "/sys/module/zswap/parameters/enabled", "Y\n")
    w(r + "/sys/module/zswap/parameters/max_pool_percent", "25\n")
    w(r + "/sys/fs/cgroup/memory.stat", "anon 1\nzswap %d\nzswapped %d\n" % (zswap_bytes, 3 * zswap_bytes))
    for s in SLICES:
        d = r + "/sys/fs/cgroup/" + s
        w(d + "/memory.pressure", psi(0))
        w(d + "/memory.current", "%d\n" % (400 * MiB))
        w(d + "/memory.reclaim", "")
    hdr = "Filename\t\t\t\tType\t\tSize\t\tUsed\t\tPriority\n"
    if swap is None:
        w(r + "/proc/swaps", hdr)
        return
    w(r + "/proc/swaps", hdr + "/dev/sdb2                               partition\t4194300\t\t1000\t\t-2\n")
    # /sys/class/block/sdb2 -> devices/.../sdb/sdb2, rotational is on the disk
    w(r + "/sys/devices/ata1/sdb/queue/rotational", "0\n" if swap == "ssd" else "1\n")
    os.makedirs(r + "/sys/devices/ata1/sdb/sdb2", exist_ok=True)
    os.makedirs(r + "/sys/class/block", exist_ok=True)
    os.symlink("../../devices/ata1/sdb/sdb2", r + "/sys/class/block/sdb2")


def run(binary, r, secs, pump=None):
    """run memd for secs; pump(r, i) is called every 50 ms (PSI counters)"""
    env = dict(os.environ, ZT_MEMD_ROOT=r, ZT_MEMD_INTERVAL_MS="200")
    p = subprocess.Popen([binary], env=env, stderr=subprocess.PIPE, text=True)
    stop = threading.Event()

    def loop():
        i = 0
        while not stop.wait(0.05):
            i += 1
            if pump:
                pump(r, i)
    t = threading.Thread(target=loop)
    t.start()
    time.sleep(secs)
    stop.set()
    t.join()
    p.send_signal(signal.SIGTERM)
    rc = p.wait(10)
    try:
        st = json.load(open(r + "/run/untrash/memd.json"))
    except (OSError, ValueError):
        st = {}
    return rc, st, p.stderr.read()


def req(st, name):
    for t in st.get("targets", []):
        if t["name"] == name:
            return t["requested"]
    return None


def main():
    with tempfile.TemporaryDirectory() as tmp:
        b = tmp + "/memd"
        subprocess.run(["gcc", "-Wall", "-Wextra", "-Werror", "-O2", "-o", b, SRC], check=True)

        r = tmp + "/ssd"
        fake_root(r, "ssd")
        rc, st, err = run(b, r, 1.5)
        check("SIGTERM: exit 0", rc == 0 and "stopped" in err)
        check("ssd: mode ssd", st.get("mode") == "ssd")
        check("ssd: reclaims background, system, user",
              all((req(st, s) or 0) > 0 for s in SLICES[:3]))
        check("ssd: background reclaimed fastest", req(st, SLICES[0]) > req(st, SLICES[1]))
        check("interactive slice is never a target", req(st, SLICES[3]) is None)
        check("ssd: reclaim request is a byte count",
              open(r + "/sys/fs/cgroup/system.slice/memory.reclaim").read().isdigit())
        check("ssd: page-cluster 0", open(r + "/proc/sys/vm/page-cluster").read() == "0")
        check("background step capped at 16 MiB",
              int(open(r + "/sys/fs/cgroup/untrash-background.slice/memory.reclaim").read()) <= 16 * MiB)

        r = tmp + "/busy"
        fake_root(r, "ssd")

        def busy(r, i):	# background stalls 50 % of the time (> its 0.5 % target)
            w(r + "/sys/fs/cgroup/untrash-background.slice/memory.pressure", psi(i * 25000))
        rc, st, _ = run(b, r, 1.5, busy)
        check("pressure above target: background left alone", req(st, SLICES[0]) == 0)
        check("pressure above target: system still reclaimed", req(st, SLICES[1]) > 0)

        r = tmp + "/brake"
        fake_root(r, "ssd")

        def brake(r, i):	# whole system: full stall 10 %
            w(r + "/proc/pressure/memory", psi(i * 10000, i * 5000))
        rc, st, _ = run(b, r, 1.5, brake)
        check("global brake: no reclaim at all",
              st.get("brake") is True and all(req(st, s) == 0 for s in SLICES[:3]))

        r = tmp + "/hdd"
        fake_root(r, "hdd", zswap_bytes=10 * MiB)
        rc, st, _ = run(b, r, 1.2)
        check("hdd swap, zswap has room: mode zswap and reclaim",
              st.get("mode") == "zswap" and req(st, SLICES[1]) > 0)
        check("hdd swap: page-cluster 3", open(r + "/proc/sys/vm/page-cluster").read() == "3")

        r = tmp + "/hddfull"
        fake_root(r, "hdd", zswap_bytes=230 * MiB)	# limit 25 % of 1000000 kB = ~244 MiB
        rc, st, _ = run(b, r, 1.2)
        check("hdd swap, zswap nearly full: mode off, no reclaim",
              st.get("mode") == "off" and all(req(st, s) == 0 for s in SLICES[:3]))

        r = tmp + "/noswap"
        fake_root(r, None)
        rc, st, _ = run(b, r, 1.2)
        check("no swap: mode off, no reclaim",
              st.get("mode") == "off" and all(req(st, s) == 0 for s in SLICES[:3]))

        r = tmp + "/oldkernel"
        os.makedirs(r + "/proc")
        t0 = time.time()
        p = subprocess.run([b], env=dict(os.environ, ZT_MEMD_ROOT=r), capture_output=True, text=True, timeout=10)
        check("no PSI/memcg: exits 0 at once",
              p.returncode == 0 and time.time() - t0 < 2 and "nothing to do" in p.stderr)
    print("FAILURES %d" % FAIL)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
