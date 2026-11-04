#!/usr/bin/env python3
"""untrash-cloud-wg (root) checks what the app's PHP printed before it reaches
wg, ip or the WireGuard UAPI socket: injected lines, addresses outside the
mesh prefix and malformed keys are dropped, a bad prefix stops the round."""
import importlib.machinery
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_l = importlib.machinery.SourceFileLoader("cwg", os.path.join(HERE, "..", "server", "untrash-cloud-wg"))
_s = importlib.util.spec_from_loader("cwg", _l)
cwg = importlib.util.module_from_spec(_s)
_l.exec_module(cwg)
cwg.log = lambda msg: None
fails = 0


def check(name, ok):
    global fails
    print(("ok   " if ok else "FAIL ") + name)
    fails += not ok


K = "lV28Q6vKDrvJoC2oGFs8iy3GHACty2abkN6gOcWeEII="
GOOD = {"mesh": "m", "prefix": "fd12:3456:789a::/48", "address": "fd12:3456:789a:0:1::1",
        "peers": [{"node": "a", "wg": K, "address": "fd12:3456:789a:0:2::2"},
                  {"node": "inject", "wg": K, "address": "fd12:3456:789a:0:2::3/128\nallowed_ip=::/0"},
                  {"node": "outside", "wg": K, "address": "2001:db8::1"},
                  {"node": "self", "wg": K, "address": "fd12:3456:789a:0:1::1"},
                  {"node": "badkey", "wg": K + "\nlisten_port=1", "address": "fd12:3456:789a:0:2::4"}]}
r = cwg.checked(GOOD)
check("only the well-formed peer stays (no injected line, no outside or own address, no bad key)",
      [p["node"] for p in r["peers"]] == ["a"])


def refused(**kw):
    try:
        cwg.checked(dict(GOOD, **kw))
        return False
    except RuntimeError:
        return True
check("a prefix that is not a ULA /48 stops the round", refused(prefix="::/0") and refused(prefix="2001:db8::/48"))
check("an own address outside the prefix stops the round", refused(address="fd00::1"))
check("a prefix with an injected line stops the round", refused(prefix="fd12:3456:789a::/48\n"))
print("%d failed" % fails if fails else "all ok")
sys.exit(1 if fails else 0)
