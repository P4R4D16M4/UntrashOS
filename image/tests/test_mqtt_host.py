#!/usr/bin/env python3
"""PC test of untrash-mqtt (the NAS as a Home Assistant device over MQTT)
against a small MQTT 3.1.1 broker in this file, on a fake root (/proc,
mdstat, fan.json, volumes) with a fake smartctl (one disk awake, one asleep)
and a fake systemctl for the buttons.

- CONNECT with client id, user/password and the retained last will "offline"
- discovery: retained configs below the prefix with unique ids, device,
  availability; buttons only with commands=true
- state: one retained JSON with every value; a sleeping disk is null + ON
- a degraded array is a problem, its recovery progress a value
- commands: PRESS runs systemctl; retained PRESS is ignored and cleared;
  without commands=true nothing runs
- Home Assistant's birth message "online" sends the discovery again
- a volume that is gone gets an empty config (removed in Home Assistant)
- a clean stop publishes "offline"
- untrash-config: smarthome.mqtt -> /etc/untrash/mqtt.json (0600) and the unit
- Home Assistant over the mesh: smarthome.ha_proxy -> ha-proxy.env, units
"""
import importlib.machinery
import importlib.util
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "rootfs")
TOOL = os.path.join(FILES, "usr/lib/untrash/untrash-mqtt")
CFG_TOOL = os.path.join(FILES, "usr/sbin/untrash-config")
FAIL = 0


def check(name, ok):
    global FAIL
    print(("ok   " if ok else "FAIL ") + name, flush=True)
    FAIL += 0 if ok else 1


def load(path, name):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _str(s):
    b = s.encode() if isinstance(s, str) else s
    return struct.pack("!H", len(b)) + b


def _packet(ptype, body):
    n, rl = len(body), b""
    while True:
        d, n = n % 128, n // 128
        rl += bytes([d | (0x80 if n else 0)])
        if not n:
            return bytes([ptype]) + rl + body


class Broker:
    """One client at a time; records CONNECT, PUBLISH (topic -> list of
    (payload, retain)), SUBSCRIBE; can send a PUBLISH to the client."""

    def __init__(self):
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.connects, self.pubs, self.subs, self.log = [], {}, [], []
        self.conn, self.lock = None, threading.Lock()
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            self.conn = c
            try:
                self.client(c)
            except (OSError, ValueError):
                pass

    def _read(self, c, n):
        b = b""
        while len(b) < n:
            d = c.recv(n - len(b))
            if not d:
                raise ValueError("closed")
            b += d
        return b

    def client(self, c):
        while True:
            h = self._read(c, 1)[0]
            n, mult = 0, 1
            while True:
                b = self._read(c, 1)[0]
                n += (b & 0x7f) * mult
                mult *= 128
                if not b & 0x80:
                    break
            body = self._read(c, n) if n else b""
            t = h >> 4
            if t == 1:
                self.connects.append(self.parse_connect(body))
                c.sendall(b"\x20\x02\x00\x00")
            elif t == 3:
                tl = struct.unpack("!H", body[:2])[0]
                topic, payload = body[2:2 + tl].decode(), body[2 + tl:]
                with self.lock:
                    self.pubs.setdefault(topic, []).append((payload, bool(h & 1)))
                    self.log.append(topic)
            elif t == 8:
                pid, rest, topics = body[:2], body[2:], []
                while rest:
                    tl = struct.unpack("!H", rest[:2])[0]
                    topics.append(rest[2:2 + tl].decode())
                    rest = rest[3 + tl:]
                self.subs += topics
                c.sendall(_packet(0x90, pid + b"\x00" * len(topics)))
            elif t == 12:
                c.sendall(b"\xd0\x00")
            elif t == 14:
                c.close()
                return

    @staticmethod
    def parse_connect(body):
        p = body[10:]
        fields = []
        while p:
            n = struct.unpack("!H", p[:2])[0]
            fields.append(p[2:2 + n].decode())
            p = p[2 + n:]
        flags = body[7]
        out = {"flags": flags, "keepalive": struct.unpack("!H", body[8:10])[0], "client_id": fields.pop(0)}
        if flags & 0x04:
            out["will"] = (fields.pop(0), fields.pop(0))
        if flags & 0x80:
            out["username"] = fields.pop(0)
        if flags & 0x40:
            out["password"] = fields.pop(0)
        return out

    def send(self, topic, payload, retain=False):
        self.conn.sendall(_packet(0x30 | (1 if retain else 0), _str(topic) + payload.encode()))

    def last(self, topic):
        with self.lock:
            v = self.pubs.get(topic)
            return v[-1] if v else None

    def count(self, prefix):
        with self.lock:
            return sum(1 for t in self.log if t.startswith(prefix))


def wait(cond, secs=10):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def fake_root(r):
    def wr(path, text):
        os.makedirs(os.path.dirname(r + path), exist_ok=True)
        open(r + path, "w").write(text)
    wr("/proc/stat", "cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 50 0 50 400 0 0 0 0 0 0\ncpu1 50 0 50 400 0 0 0 0 0 0\n")
    wr("/proc/meminfo", "MemTotal: 1000000 kB\nMemAvailable: 250000 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n")
    wr("/proc/loadavg", "0.50 0.40 0.30 1/100 1234\n")
    wr("/proc/uptime", "3600.00 7000.00\n")
    wr("/proc/net/dev", "Inter-|\n face |\n  eth0: 1000 10 0 0 0 0 0 0 2000 20 0 0 0 0 0 0\n")
    wr("/proc/mdstat", "Personalities : [raid1] [raid5]\n"
       "md0 : active raid1 sda1[0]\n      1999808 blocks super 1.2 [4/1] [U___]\n\n"
       "md3 : active raid1 sda4[0] sdb4[1]\n      1999808 blocks super 1.2 [2/2] [UU]\n\n"
       "md120 : active linear sda5[0] sdb5[1]\n      29282301696 blocks super 1.2 64k rounding\n\n"
       "md2 : active raid5 sdc3[2] sda3[0] sdb3[1]\n      3902384128 blocks level 5, 64k chunk [3/2] [UU_]\n"
       "      [=>...................]  recovery =  7.5% (146367488/1951192064) finish=300min speed=100000K/sec\n\n"
       "unused devices: <none>\n")
    wr("/run/untrash/fan.json", json.dumps({"temp_c": 47, "rpm_reg": 1, "level": 2, "pwm_low": 9, "time": int(time.time()) + 3600}))
    wr("/etc/untrash-version", "1.2-test\n")
    wr("/etc/machine-id", "0123456789abcdef0123456789abcdef\n")
    wr("/usr/share/untrash/board.json", json.dumps({"title": "Zyxel NAS542"}))
    wr("/i-data/1a2b3c4d/.system/name_label", "Volume1\n")
    wr("/i-data/5e6f7a8b/.system/name_label", "Archiv\n")
    wr("/sys/block/sda/removable", "0\n")
    wr("/sys/block/sdb/removable", "0\n")
    wr("/var/lib/untrash/update/state.json", json.dumps({"available": {"version": "1.2.1"}}))


FAKE_SMART = """#!/bin/sh
case "$*" in
  *sda*) printf '194 Temperature_Celsius     0x0022   038   045   000    Old_age   Always       -       38 (Min/Max 20/45)\\n'; exit 0;;
  *sdb*) echo "Device is in STANDBY mode, exit(2)"; exit 2;;
esac
"""


def run_daemon(w, root, conf, bin_dir):
    conf_path = os.path.join(w, "mqtt.json")
    json.dump(conf, open(conf_path, "w"))
    env = dict(os.environ, ZT_MQTT_ROOT=root, ZT_MQTT_CONF=conf_path, ZT_MQTT_STATE=os.path.join(w, "state.json"),
               ZT_UPDATE_STATE=root + "/var/lib/untrash/update/state.json", ZT_VERSION_FILE="/etc/untrash-version",
               ZT_MQTT_POWER_CMD=os.path.join(bin_dir, "systemctl"), PATH=bin_dir + ":" + os.environ["PATH"])
    # host name decides the node id: run under a fixed one via a wrapper
    code = ("import socket,runpy,sys; socket.gethostname=lambda: 'TestNAS'; sys.argv=[%r]; "
            "runpy.run_path(%r, run_name='__main__')" % (TOOL, TOOL))
    return subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)


def main():
    w = tempfile.mkdtemp(prefix="zt-mqtt-")
    root, bin_dir = os.path.join(w, "root"), os.path.join(w, "bin")
    os.makedirs(bin_dir)
    fake_root(root)
    open(os.path.join(bin_dir, "smartctl"), "w").write(FAKE_SMART)
    calls = os.path.join(w, "calls")
    open(os.path.join(bin_dir, "systemctl"), "w").write('#!/bin/sh\necho "$*" >> %s\n' % calls)
    for f in ("smartctl", "systemctl"):
        os.chmod(os.path.join(bin_dir, f), 0o755)
    br = Broker()
    conf = {"server": "127.0.0.1", "port": br.port, "username": "nas", "password": "s3cret",
            "discovery_prefix": "homeassistant", "interval": 10, "commands": True}
    p = run_daemon(w, root, conf, bin_dir)
    base, disc = "untrash/testnas", "homeassistant"
    try:
        check("connects", wait(lambda: br.connects and br.last(base + "/state")))
        c = br.connects[0] if br.connects else {}
        check("CONNECT: client id, user, password", c.get("client_id") == "untrash-testnas" and
              c.get("username") == "nas" and c.get("password") == "s3cret")
        check("last will: retained offline on the status topic", c.get("will") == (base + "/status", "offline")
              and c["flags"] & 0x20)
        check("subscribes to HA status and its command topics", disc + "/status" in br.subs and base + "/cmd/+" in br.subs)
        check("status online, retained", br.last(base + "/status") == (b"online", True))

        cfg = br.last(disc + "/sensor/testnas/cpu/config")
        cj = json.loads(cfg[0]) if cfg else {}
        check("discovery: CPU sensor retained, state topic, %", cfg and cfg[1] and cj.get("state_topic") == base + "/state"
              and cj.get("unit_of_measurement") == "%" and cj.get("availability_topic") == base + "/status")
        dev = cj.get("device", {})
        check("device: model from board.json, version, stable id", dev.get("model") == "Zyxel NAS542" and
              dev.get("sw_version") == "1.2-test" and dev.get("identifiers", [""])[0].startswith("untrash_") and
              cj.get("unique_id") == dev["identifiers"][0] + "_cpu")
        check("discovery: no machine id in clear", "0123456789abcdef" not in cfg[0].decode())
        for topic in ("sensor/testnas/board_temp", "sensor/testnas/disk_sda_temp", "binary_sensor/testnas/disk_sdb_sleeping",
                      "sensor/testnas/vol_1a2b3c4d_used", "sensor/testnas/vol_5e6f7a8b_free", "binary_sensor/testnas/md2_degraded",
                      "sensor/testnas/md2_progress", "update/testnas/update", "button/testnas/reboot", "button/testnas/poweroff"):
            check("discovery: " + topic, br.last("%s/%s/config" % (disc, topic)) is not None)
        vol = json.loads(br.last(disc + "/sensor/testnas/vol_1a2b3c4d_used/config")[0])
        check("volume entity named by its label", vol.get("name") == "Volume1 used")
        btn = json.loads(br.last(disc + "/button/testnas/reboot/config")[0])
        check("button: command topic, restart class", btn.get("command_topic") == base + "/cmd/reboot" and
              btn.get("device_class") == "restart" and "state_topic" not in btn)

        st = json.loads(br.last(base + "/state")[0])
        check("state: memory 75 %, load 0.5, board 47 °C, fan 2", st.get("mem_used") == 75.0 and st.get("load1") == 0.5
              and st.get("board_temp") == 47 and st.get("fan_level") == 2)
        check("state: awake disk 38 °C, sleeping disk null + ON", st.get("disk_sda_temp") == 38 and
              st.get("disk_sda_sleeping") == "OFF" and st.get("disk_sdb_temp") is None and
              st.get("disk_sdb_sleeping") == "ON")
        check("stock firmware mirror md0 ([4/1]) left out", "md0_degraded" not in st)
        check("state: md3 fine, linear md120 fine, md2 degraded in recovery 7.5 %", st.get("md3_degraded") == "OFF" and
              st.get("md120_degraded") == "OFF" and
              st.get("md2_degraded") == "ON" and st.get("md2_job") == "recovery" and st.get("md2_progress") == 7.5)
        check("state: RAID activity, boot time, update 1.2-test -> 1.2.1",
              st.get("activity", "").startswith("RAID md2: recovery") and st.get("boot", "").endswith("+00:00")
              and st.get("installed") == "1.2-test" and st.get("latest") == "1.2.1")
        upd = json.loads(br.last(disc + "/update/testnas/update/config")[0])
        check("update entity template gives installed/latest", "installed_version" in upd.get("value_template", ""))

        # commands
        br.send(base + "/cmd/reboot", "PRESS", retain=True)
        check("retained PRESS cleared on the broker", wait(lambda: br.last(base + "/cmd/reboot") == (b"", True)))
        time.sleep(0.5)
        check("retained PRESS runs nothing", not os.path.exists(calls))
        br.send(base + "/cmd/reboot", "PRESS")
        check("PRESS on reboot runs 'systemctl reboot'", wait(lambda: os.path.exists(calls) and
                                                                open(calls).read() == "reboot\n"))
        br.send(base + "/cmd/../poweroff", "PRESS")
        br.send(base + "/cmd/halt", "PRESS")
        time.sleep(0.5)
        check("unknown commands run nothing", open(calls).read() == "reboot\n")

        # HA restarts: discovery again
        n = br.count(disc + "/sensor/testnas/cpu/config")
        br.send(disc + "/status", "online")
        check("HA birth -> discovery again", wait(lambda: br.count(disc + "/sensor/testnas/cpu/config") > n))

        # a volume goes away -> its config is removed at the next interval
        shutil.rmtree(root + "/i-data/5e6f7a8b")
        check("vanished volume: empty retained config", wait(lambda: br.last(disc + "/sensor/testnas/vol_5e6f7a8b_used/config")
                                                              == (b"", True), 15))
        sent = json.load(open(os.path.join(w, "state.json")))
        check("sent discovery topics kept for the next start", disc + "/sensor/testnas/cpu/config" in sent.get("sent", [])
              and disc + "/sensor/testnas/vol_5e6f7a8b_used/config" not in sent["sent"])
    finally:
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(10)
        except subprocess.TimeoutExpired:
            p.kill()
    check("clean stop: offline published", br.last(base + "/status") == (b"offline", True))
    out = p.stdout.read()

    # commands off: no buttons, the old button configs are removed, PRESS ignored
    br2 = Broker()
    os.remove(calls)
    conf2 = dict(conf, port=br2.port, commands=False)
    p2 = run_daemon(w, root, conf2, bin_dir)
    try:
        check("restart without commands", wait(lambda: br2.last(base + "/state")))
        check("buttons removed (from the saved topic list)", br2.last(disc + "/button/testnas/reboot/config") == (b"", True))
        check("no command subscription", base + "/cmd/+" not in br2.subs)
    finally:
        p2.send_signal(signal.SIGTERM)
        p2.wait(10)

    # untrash-config
    cfgm = load(CFG_TOOL, "untrash_config")
    s = cfgm.merged(cfgm.DEFAULTS, {"smarthome": {"mqtt": {"active": True, "server": "broker.lan", "password": "pw"}}})
    r2 = os.path.join(w, "render")
    cfgm.render_extra(s, r2, [])
    mj = os.path.join(r2, "etc/untrash/mqtt.json")
    check("config: mqtt.json 0600 with the settings", os.path.exists(mj) and os.stat(mj).st_mode & 0o777 == 0o600 and
          json.load(open(mj))["server"] == "broker.lan")
    check("config: unit wanted", cfgm.wanted(s)["mqtt"] and "untrash-mqtt.service" in cfgm.UNITS["mqtt"])
    s["smarthome"]["mqtt"]["active"] = False
    cfgm.render_extra(s, r2, [])
    check("config: off removes mqtt.json, unit not wanted", not os.path.exists(mj) and not cfgm.wanted(s)["mqtt"])
    check("unit file exists", os.path.isfile(os.path.join(FILES, "usr/lib/systemd/system/untrash-mqtt.service")))

    # Home Assistant over the mesh: untrash-config + units
    hpe = os.path.join(r2, "etc/untrash/ha-proxy.env")
    s["smarthome"]["ha_proxy"] = {"active": True, "target": "192.168.1.20:8123"}
    cfgm.render_extra(s, r2, [])
    check("ha-proxy: env with the target, socket wanted", open(hpe).read() == "TARGET=192.168.1.20:8123\n" and
          cfgm.wanted(s)["ha_proxy"] and cfgm.UNITS["ha_proxy"] == ["untrash-ha-proxy.socket"])
    s["smarthome"]["ha_proxy"]["target"] = "[fd00::5]:443"
    cfgm.render_extra(s, r2, [])
    check("ha-proxy: IPv6 target", open(hpe).read() == "TARGET=[fd00::5]:443\n")
    for bad in ("192.168.1.20", "x:99999", "a b:80", "h:80;rm -rf /", ""):
        s["smarthome"]["ha_proxy"]["target"] = bad
        cfgm.render_extra(s, r2, [])
        check("ha-proxy: bad target %r -> off" % bad, not os.path.exists(hpe) and not cfgm.wanted(s)["ha_proxy"])
    sock = open(os.path.join(FILES, "usr/lib/systemd/system/untrash-ha-proxy.socket")).read()
    svc = open(os.path.join(FILES, "usr/lib/systemd/system/untrash-ha-proxy.service")).read()
    check("ha-proxy socket: port 8123 on ut-mesh only", "ListenStream=8123" in sock and "BindToDevice=ut-mesh" in sock
          and "ConditionPathExists=/etc/untrash/ha-proxy.env" in sock)
    check("ha-proxy service: socket-proxyd to ${TARGET}, PartOf socket, DynamicUser",
          "systemd-socket-proxyd" in svc and "${TARGET}" in svc and "PartOf=untrash-ha-proxy.socket" in svc and "DynamicUser=yes" in svc)

    if FAIL:
        print(out)
    shutil.rmtree(w, ignore_errors=True)
    print("untrash-mqtt: %s" % ("FAILED (%d)" % FAIL if FAIL else "all ok"))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
