#!/usr/bin/env python3
"""PC test of image/tools/untrash-wdt.c (watchdog keeper), a plain file
standing in for /dev/watchdog (ioctl fails there, the keeper then writes).

- feeds regularly while the liveness probe (systemd) answers
- stops feeding once the probe has failed for DEAD seconds
- a hanging probe counts as failure (killed after its timeout)
- SIGTERM: exits 0 without the magic close 'V' (watchdog stays armed)
"""
import os
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "tools", "untrash-wdt.c")
FAIL = 0


def check(name, ok):
    global FAIL
    print(("ok   " if ok else "FAIL ") + name, flush=True)
    FAIL += 0 if ok else 1


def run(w, probe, times, secs):
    dev = os.path.join(w, "wdt-%s" % probe.split()[0])
    open(dev, "w").close()
    env = dict(os.environ, ZT_WDT_PROBE=probe, ZT_WDT_TIMES=times)
    p = subprocess.Popen([w + "/wdt", dev], env=env, stderr=subprocess.PIPE, text=True)
    sizes = []
    for _ in range(secs * 2):
        time.sleep(0.5)
        sizes.append(os.path.getsize(dev))
    p.send_signal(signal.SIGTERM)
    rc = p.wait(10)
    return sizes, rc, open(dev).read(), p.stderr.read()


def main():
    with tempfile.TemporaryDirectory() as w:
        subprocess.run(["gcc", "-Wall", "-Wextra", "-Werror", "-O2", "-o", w + "/wdt", SRC], check=True)
        s, rc, data, _e = run(w, "true", "1 1 2 3", 6)
        check("probe ok: keeps feeding", s[-1] > s[3] > 0)
        check("SIGTERM: exit 0, no magic close", rc == 0 and "V" not in data)
        s, rc, _d, err = run(w, "false", "1 1 2 2", 7)
        check("probe failing: stops feeding after DEAD", s[-1] == s[-4] and "no more feeding" in err)
        s, rc, _d, err = run(w, "sleep 30", "1 1 1 2", 7)
        check("hanging probe counts as failure", s[-1] == s[-4] and "no more feeding" in err)
    print("FAILURES %d" % FAIL)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
