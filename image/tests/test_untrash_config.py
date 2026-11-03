#!/usr/bin/env python3
"""PC test of untrash-config (way B: stock settings -> UntrashOS), the
importer's access/Time-Machine/NetBIOS additions and the password check.
  python3 image/tests/test_untrash_config.py
A synthetic stock /etc/zyxel (py_conf in the stock ConfigObj layout, the test
ugs_conf.db of test_import_zyxel.py with media flags, hd-idle.conf,
pwrmg.db, extuuid.table, NFS flag + exports) goes through import-stock and
render into a temporary root; the files are checked line by line."""
import importlib.machinery
import importlib.util
import glob
import json
import os
import sqlite3
import subprocess
import sys
import shutil
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = os.path.join(HERE, "..", "rootfs")
CFG_TOOL = os.path.join(FILES, "usr/sbin/untrash-config")
IMPORT = os.path.join(FILES, "usr/sbin/untrash-import-zyxel")
fails = 0


def check(name, cond):
    global fails
    print(("ok   " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


def load(path, name):
    spec = importlib.util.spec_from_loader(name, importlib.machinery.SourceFileLoader(name, path))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


t = load(os.path.join(HERE, "test_import_zyxel.py"), "t")

PYCONF = """[system]
    hostname = TestNAS
    [[fw_upgrade]]
        auto_check = true
    [[service]]
        [[[ssh]]]
            active = true
            port = 2222
            sftp_active = false
        [[[mediaserver]]]
            active = true
        [[[itune]]]
            active = false
        [[[webpublish]]]
            active = true
            port = 8080
        [[[https]]]
            port = 8443
            active = true
            force_https = true
        [[[printer]]]
            [[[[ABC123]]]]
                prt_name = Laser_Buero
                seri_num = ABC123
                lp_num = 0
                status = on-line
        [[[ftp]]]
            active = true
            with_encrypt = true
            conn_limit = 3
            idle_timeout = 15
            cmd_port = 21
            allow_anonymous = n
            data_port_range_set = manual
            data_port_min = 50000
            data_port_max = 50100
            normal_up_speed = 0
            normal_dl_speed = 100
            anonymous_up_speed = 0
            anonymous_dl_speed = 0
        [[[dydns]]]
            active = true
            provider = noip
            username = dd-user
            password = dd"pw
            hostname = nas.example.net
    [[date_time]]
        timeServerActive = true
        timeServerAddr = time.example.org
        timezoneCountry = +01:00/Amsterdam
    [[servername]]
        servername = TESTNAS
        description = Test box
        workgroupname = TESTWG
        nomaster = false
[network]
    [[interface]]
        default_gateway = egiga0
        [[[nameserver]]]
            fetch = manual
            name_server_1 = 10.0.0.53
            name_server_2 =
        [[[bond0]]]
            activate = yes
            slave = egiga1 egiga0
            mode = 4
            type = static
            address = 10.0.0.50/24
            gateway = 10.0.0.1
            mtu = 1500
        [[[egiga0]]]
            type = static
            address = 10.0.0.42/24
            gateway = 10.0.0.1
            mtu = 1500
        [[[egiga1]]]
            type = dhcp
            address = 0.0.0.0/0
            mtu = 1500
[backup]
    [[time_machine]]
        active = true
        target_share = Medien
[maintenance]
    [[log]]
        [[[mail]]]
            enable = yes
            address = smtp.example.net:2525
            authentication = yes
            username = mailer
            password = m-pw
            from = nas@example.net
            send-alerts-to = admin@example.net
            send-log-to = log@example.net
            subject = NAS-Test
            alert = yes
            levelall =
            schedule = weekly
            day = 1
            hour = 3
            miniute = 30
        [[[syslog]]]
            enable = yes
            address = 10.0.0.9
"""

with tempfile.TemporaryDirectory() as W:
    cfg = os.path.join(W, "cfg")
    os.makedirs(os.path.join(cfg, "storage"))
    os.makedirs(os.path.join(cfg, "webdav"))
    t.make_db(os.path.join(cfg, "ugs_conf.db"))
    c = sqlite3.connect(os.path.join(cfg, "ugs_conf.db"))
    names = [r[0] for r in c.execute("SELECT s_name FROM smb_share WHERE s_enable='y' ORDER BY s_name")]
    media_share, other = names[0], names[1]
    c.execute("UPDATE smb_share SET mdaserv_public_type=? WHERE s_name=?", (1 | 2 | 4, media_share))
    c.execute("UPDATE smb_share SET mdaserv_public_type=4 WHERE s_name=?", (other,))
    c.execute("INSERT INTO ugs_misc VALUES ('rbm_expire_day', '30')")
    c.commit()
    c.close()
    open(os.path.join(cfg, "py_conf"), "w").write(PYCONF)
    open(os.path.join(cfg, "hd-idle.conf"), "w").write("15\n")
    p = sqlite3.connect(os.path.join(cfg, "pwrmg.db"))
    p.execute("CREATE TABLE pwrmg (id VARCHAR(30) PRIMARY KEY UNIQUE NOT NULL, value INTEGER)")
    p.executemany("INSERT INTO pwrmg VALUES (?,?)", [("pwr_turnOffHD", 15), ("pwr_wol", 0), ("pwr_minimumUPSCapacity", 30),
                                                     ("pwr_pwron", 1), ("pwrsch_default_onoff", 1)])
    p.commit()
    p.close()
    open(os.path.join(cfg, "storage", "extuuid.table"), "w").write("USB-Platte|0123456789abcdef0123456789abcdef\n")
    open(os.path.join(cfg, "storage", "enable_nfs.flag"), "w").close()
    open(os.path.join(cfg, "exports"), "w").write("/i-data/aaaa0001/Medien 10.0.0.0/24(rw,sync,no_subtree_check)\n")
    open(os.path.join(cfg, "webdav", "dav.flag"), "w").close()
    open(os.path.join(cfg, "storage", "usbcopy.table"), "w").write("/i-data/aaaa0001/Medien|/i-data/aaaa0001/Alt|cp2USB|n")
    open(os.path.join(cfg, "storage", "usbzync.table"), "w").write("/i-data/aaaa0001/Sync||sync2Vol")
    import datetime as _d
    st0 = int(_d.datetime(2026, 1, 5, 7, 30).timestamp())
    st1 = int(_d.datetime(2026, 1, 5, 23, 15).timestamp())
    bj = sqlite3.connect(os.path.join(cfg, "backupjob.db"))
    bj.executescript("CREATE TABLE BackupJobScheduler (ID TEXT, Jobname TEXT, Command TEXT, type TEXT, IsRunning TEXT, TimeType TEXT, StartTime TEXT, "
                     "LastRunTime TEXT, NextRunTime TEXT, Interval TEXT, DayOfWeek TEXT, DayOfMonth TEXT, MonthOfYear TEXT, IsActivated TEXT);")
    bj.executemany("INSERT INTO BackupJobScheduler VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        ("1", "", "/sbin/rtcAccess", "6", "0", "1", str(st0), "0", "0", "1", "1,5", "", "", "1"),
        ("2", "", "/sbin/poweroff", "7", "0", "0", str(st1), "0", "0", "1", "", "", "", "1"),
        ("3", "", "/sbin/reboot", "8", "0", "3", str(st1), "0", "0", "1", "", "", "", "1"),
        ("4", "backup", "x", "1", "0", "0", str(st1), "0", "0", "1", "", "", "", "1")])
    bj.commit()
    bj.close()
    u = sqlite3.connect(os.path.join(cfg, "upnp.db"))
    u.executescript("CREATE TABLE upnpInfo (service TEXT PRIMARY KEY, lan_port INTAGER, wan_port INTAGER, url_path TEXT, description TEXT, IsModifyFlag TEXT);"
                    "INSERT INTO upnpInfo VALUES ('HTTP',80,8000,'','','NO'),('FTP',21,-1,'','','NO'),('WEBDAV_HTTP',5002,5002,'','','NO');")
    u.close()
    open(os.path.join(cfg, "dropbox-sync.conf"), "w").write("ENABLED = True\nGRACE-PERIOD = 1\n")
    open(os.path.join(cfg, "youtube-ul.conf"), "w").write("ENABLED = True\n")
    open(os.path.join(cfg, "ftp-ul.conf"), "w").write("BANDWIDTH = 0\nENABLED = False\n")
    os.makedirs(os.path.join(cfg, "cert", "key"))
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2", "-subj", "/CN=NAS",
                    "-keyout", os.path.join(cfg, "cert", "key", "default_key.cer"), "-out", os.path.join(cfg, "cert", "default.cer")],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    os.makedirs(os.path.join(cfg, "syslog-ng"))
    open(os.path.join(cfg, "syslog-ng", "enable_syslog.flag"), "w").write("enable\r\n")
    open(os.path.join(cfg, "syslog-ng", "syslog.table"), "w").write("/i-data/aaaa0001/logs/|full|3\r\n")

    env = dict(os.environ, ZT_SETTINGS=os.path.join(W, "settings.json"), ZT_IMPORT_TOOL=IMPORT)
    r = subprocess.run([sys.executable, CFG_TOOL, "import-stock", cfg], env=env, stdout=subprocess.PIPE, text=True)
    check("import-stock runs", r.returncode == 0)
    s = json.load(open(env["ZT_SETTINGS"]))
    check("hostname from system.hostname", s["hostname"] == "TestNAS")
    check("netbios name/workgroup/description", s["netbios"] == {"name": "TESTNAS", "workgroup": "TESTWG",
                                                                 "description": "Test box", "nomaster": False})
    check("time zone +01:00/Amsterdam -> Europe/Amsterdam", s["time"]["timezone"] == "Europe/Amsterdam")
    check("NTP server", s["time"]["ntp"] and s["time"]["ntp_server"] == "time.example.org")
    check("eth0 static 10.0.0.42/24 gw 10.0.0.1", s["network"]["eth0"]["mode"] == "static" and
          s["network"]["eth0"]["address"] == "10.0.0.42/24" and s["network"]["eth0"]["gateway"] == "10.0.0.1")
    check("eth1 dhcp", s["network"]["eth1"]["mode"] == "dhcp" and s["network"]["eth1"]["address"] == "")
    check("manual DNS", s["network"]["dns"] == {"auto": False, "servers": ["10.0.0.53"]})
    check("ssh on, port 2222, no sftp", s["services"]["ssh"] == {"active": True, "port": 2222, "sftp": False})
    f = s["services"]["ftp"]
    check("ftp on, tls, 3 conn, pasv 50000-50100, 100 KB/s down",
          f["active"] and f["tls"] and f["conn_limit"] == 3 and f["pasv_min"] == 50000 and
          f["pasv_max"] == 50100 and f["down_kbs"] == 100 and not f["anonymous"])
    check("media server on, shares by stock mask", s["services"]["mediaserver"]["active"] and
          s["services"]["mediaserver"]["shares"] == {media_share: 7, other: 4})
    check("time machine on Medien", s["services"]["time_machine"] == {"active": True, "share": "Medien"})
    check("NFS on with stock exports", s["services"]["nfs"]["active"] and
          s["services"]["nfs"]["exports"][0]["clients"] == "10.0.0.0/24")
    check("webdav on, not anonymous (dav.flag)", s["services"]["webdav"] == {"active": True, "anonymous": False})
    check("dyndns no-ip with account", s["services"]["dyndns"] == {"active": True, "provider": "noip", "username": "dd-user",
                                                                  "password": 'dd"pw', "hostname": "nas.example.net"})
    m = s["notify"]["mail"]
    check("mail: server:port split, auth, recipients, weekly Mon 03:30, alerts on, report not all",
          m["active"] and m["server"] == "smtp.example.net" and m["port"] == 2525 and m["auth"] and
          m["username"] == "mailer" and m["alerts_to"] == "admin@example.net" and m["log_to"] == "log@example.net"
          and m["schedule"] == "weekly" and (m["day"], m["hour"], m["minute"]) == (1, 3, 30) and m["alerts"]
          and not m["report_all"] and m["subject"] == "NAS-Test")
    check("syslog forward to 10.0.0.9", s["notify"]["syslog"] == {"active": True, "server": "10.0.0.9", "port": 514})
    check("syslog server: path, full, 3 months", s["services"]["syslog_server"] == {
        "active": True, "path": "/i-data/aaaa0001/logs/", "format": "full", "months": 3})
    check("UPS on, battery level 30", s["services"]["ups"] == {"active": True, "min_capacity": 30})
    check("bond0 802.3ad over eth0+eth1, static", s["network"]["bond"] == {"active": True, "mode": 4, "slaves": ["eth0", "eth1"],
          "mode_ip": "static", "address": "10.0.0.50/24", "gateway": "10.0.0.1", "mtu": 1500})
    check("web publishing on port 8080", s["services"]["webpublish"] == {"active": True, "port": 8080})
    check("printer names from the stock table", s["services"]["printer"] == {"active": True, "names": {"ABC123": "Laser_Buero"}})
    check("COPY/SYNC button tables", s["copybtn"] == {"copy": {"share_path": "/i-data/aaaa0001/Medien", "bak_path": "/i-data/aaaa0001/Alt",
          "direction": "cp2USB", "newdir": False}, "sync": {"share_path": "/i-data/aaaa0001/Sync", "bak_path": "", "direction": "sync2Vol"}})
    check("settings file mode 0600 (passwords)", os.stat(env["ZT_SETTINGS"]).st_mode & 0o777 == 0o600)
    check("spin-down 15 min", s["power"]["spindown_min"] == 15)
    check("recycle expiry 30 days", s["recycle"]["expire_days"] == 30)
    check("USB name table", s["usb"]["names"] == {"0123456789abcdef0123456789abcdef": "USB-Platte"})
    check("cloud apps that were on are listed (tokens not transferable)", s["unsupported"] == [
        "Dropbox was on: connect the account again under Cloud and create the job",
        "Upload Manager YouTube was on: left out of UntrashOS on purpose",
        "Schedule “monthly by week” (reboot) not taken over"])
    check("UPnP forwardings from upnp.db", s["upnp"]["services"] == {"HTTP": 8000, "WEBDAV_HTTP": 5002})
    check("power: always on after power loss, schedule from backupjob.db (Mon+Fri on 07:30, daily off 23:15)",
          s["power"]["pwron"] == "always" and s["power"]["schedule_active"] and s["power"]["schedule"] == [
              {"action": "on", "hour": 7, "minute": 30, "kind": "weekly", "day": 0},
              {"action": "on", "hour": 7, "minute": 30, "kind": "weekly", "day": 4},
              {"action": "off", "hour": 23, "minute": 15, "kind": "daily"}])
    check("https: port 8443, forced", s["services"]["https"] == {"active": True, "port": 8443, "force": True})
    tls = os.path.join(W, "tls")
    check("stock certificate taken over (key 0600)", open(tls + "/untrash.crt").read() == open(os.path.join(cfg, "cert", "default.cer")).read()
          and os.stat(tls + "/untrash.key").st_mode & 0o777 == 0o600)
    r = subprocess.run([sys.executable, CFG_TOOL, "import-stock", cfg], env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    check("second import refused without --force", r.returncode != 0)
    # --once (takeover retried): keeps settings changed in the Desk since the import
    sp = env.get("ZT_SETTINGS")
    st = json.load(open(sp)); st["hostname"] = "ChangedInDesk"; json.dump(st, open(sp, "w"))
    r = subprocess.run([sys.executable, CFG_TOOL, "import-stock", cfg, "--once"], env=env, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
    check("import --once after an import keeps the Desk's changes",
          r.returncode == 0 and json.load(open(sp))["hostname"] == "ChangedInDesk")
    st["hostname"] = "TestNAS"; json.dump(st, open(sp, "w"))

    root = os.path.join(W, "root")
    os.makedirs(root + "/etc/untrash/zyxel")
    import shutil
    shutil.copytree(cfg, root + "/etc/untrash/zyxel/stock-config")
    # media folders: two with files, every other one missing or empty
    sp = dict(sqlite3.connect(os.path.join(cfg, "ugs_conf.db")).execute("SELECT s_name, s_path FROM smb_share"))
    for n in (media_share, other):
        os.makedirs(root + sp[n], exist_ok=True)
        open(root + sp[n] + "/clip.mkv", "w").close()
    for n in sp:
        if n not in (media_share, other) and sp[n].startswith("/"):
            os.makedirs(root + sp[n] + "/.recycle", exist_ok=True)
    r = subprocess.run([sys.executable, CFG_TOOL, "render", "--root", root], env=env, stdout=subprocess.PIPE, text=True)
    check("render runs", r.returncode == 0)

    def rd(p):
        try:
            return open(root + p).read()
        except OSError:
            return ""
    check("hostname file", rd("/etc/hostname") == "TestNAS\n")
    check("localtime -> Europe/Amsterdam", os.readlink(root + "/etc/localtime") == "/usr/share/zoneinfo/Europe/Amsterdam")
    check("chrony server", rd("/etc/chrony/sources.d/untrash.sources") == "server time.example.org iburst\n")
    nb = rd("/etc/systemd/network/05-untrash-bond0.network")
    check("bond0: netdev 802.3ad miimon 100, links eth0/eth1, address on bond0",
          "Mode=802.3ad" in rd("/etc/systemd/network/04-untrash-bond0.netdev") and
          "MIIMonitorSec=100ms" in rd("/etc/systemd/network/04-untrash-bond0.netdev") and
          "Bond=bond0" in rd("/etc/systemd/network/05-untrash-eth0.network") and
          "Bond=bond0" in rd("/etc/systemd/network/05-untrash-eth1.network") and
          "Address=10.0.0.50/24" in nb and "Gateway=10.0.0.1" in nb and "DNS=10.0.0.53" in nb)
    s2 = json.load(open(env["ZT_SETTINGS"]))
    s2["network"]["bond"]["active"] = False
    json.dump(s2, open(env["ZT_SETTINGS"], "w"))
    subprocess.run([sys.executable, CFG_TOOL, "render", "--root", root], env=env, stdout=subprocess.PIPE)
    check("bond off: netdev removed", not os.path.exists(root + "/etc/systemd/network/04-untrash-bond0.netdev"))
    n0 = rd("/etc/systemd/network/05-untrash-eth0.network")
    check("eth0 static network", "Address=10.0.0.42/24" in n0 and "Gateway=10.0.0.1" in n0 and "DHCP" not in n0
          and "DNS=10.0.0.53" in n0)
    check("no dev recovery address (release)", "169.254.100.64" not in n0)
    n1 = rd("/etc/systemd/network/05-untrash-eth1.network")
    check("eth1 dhcp, no DHCP DNS (manual)", "DHCP=ipv4" in n1 and "UseDNS=no" in n1)
    check("printing: marker + smb-extra printers", os.path.exists(root + "/etc/untrash/printing.enabled") and
          json.loads(rd("/etc/untrash/smb-extra.json"))["printers"] is True)
    check("download service on by default (no dservice.disable)", json.load(open(env["ZT_SETTINGS"]))["services"]["download"]["active"])
    ac = rd("/etc/untrash/aria2.conf")
    check("aria2.conf: dir in admin share, local RPC with secret, stock defaults", "dir=" in ac and ac.split("dir=")[1].split("\n")[0].endswith("/admin/download")
          and "rpc-listen-all=false" in ac and "rpc-secret=" + rd("/etc/untrash/aria2.secret").strip() in ac and
          "seed-ratio=1.00" in ac and "max-concurrent-downloads=3" in ac and os.stat(root + "/etc/untrash/aria2.conf").st_mode & 0o777 == 0o600)
    dlh = load(os.path.join(FILES, "usr/lib/untrash/untrash-downloads"), "dlh")
    import datetime as _dt
    T = lambda h, m: _dt.datetime(2026, 10, 10, h, m)  # noqa: E731
    check("time window 0100:0700 and over midnight 2200:0600", dlh.in_window("0100:0700", T(3, 0)) and not dlh.in_window("0100:0700", T(8, 0))
          and dlh.in_window("2200:0600", T(23, 30)) and dlh.in_window("2200:0600", T(5, 59)) and not dlh.in_window("2200:0600", T(12, 0))
          and dlh.in_window("", T(12, 0)))
    hc0 = rd("/etc/untrash/webdav/httpd.conf")
    check("web publishing vhost on 8080: no published share yet", "Listen 8080" in hc0 and "/MyWeb/" not in hc0)
    ss = rd("/etc/ssh/sshd_config.d/20-untrash.conf")
    check("sshd port 2222, sftp off", "Port 2222" in ss and "Subsystem sftp /bin/false" in ss)
    v = rd("/etc/vsftpd.conf")
    check("vsftpd: tls, pasv range, per-ip limit, rate", "ssl_enable=YES" in v and "pasv_min_port=50000" in v and
          "max_per_ip=3" in v and "local_max_rate=102400" in v and "anonymous_enable=NO" in v)
    check("ftp PAM checks the SMB password", "untrash-checkpw" in rd("/etc/pam.d/untrash-ftp"))
    check("exports", rd("/etc/exports").splitlines()[1] == "/i-data/aaaa0001/Medien 10.0.0.0/24(rw,sync,no_subtree_check)")
    dl = rd("/etc/minidlna.conf")
    paths = dict(sqlite3.connect(os.path.join(cfg, "ugs_conf.db")).execute("SELECT s_name, s_path FROM smb_share"))
    check("minidlna media_dir with stock types", "media_dir=VPA,%s" % paths[media_share] in dl and
          "media_dir=A,%s" % paths[other] in dl and "friendly_name=TestNAS" in dl)
    check("minidlna: empty and missing folders not published", dl.count("media_dir=") == 2)
    check("hd-idle 900 s", 'HD_IDLE_OPTS="-i 900"' in rd("/etc/default/hd-idle") and "START_HD_IDLE=true" in rd("/etc/default/hd-idle"))
    check("usb names", rd("/etc/untrash/usb-names") == "USB-Platte|0123456789abcdef0123456789abcdef\n")
    ina = rd("/etc/inadyn.conf")
    check("inadyn: no-ip provider, quoted password", "provider default@no-ip.com {" in ina and 'password = "dd\\"pw"' in ina
          and 'hostname = "nas.example.net"' in ina and os.stat(root + "/etc/inadyn.conf").st_mode & 0o777 == 0o600)
    nj = json.loads(rd("/etc/untrash/notify.json"))
    check("notify.json 0600 with hostname", nj["server"] == "smtp.example.net" and nj["hostname"] == "TestNAS" and
          os.stat(root + "/etc/untrash/notify.json").st_mode & 0o777 == 0o600)
    check("report timer weekly Mon 03:30", "OnCalendar=Mon *-*-* 03:30:00" in rd("/etc/systemd/system/untrash-log-report.timer"))
    check("mdadm events + smartd -> untrash-notify", "PROGRAM /usr/lib/untrash/untrash-notify" in rd("/etc/mdadm/mdadm.conf")
          and "-M exec /usr/lib/untrash/untrash-notify" in rd("/etc/smartd.conf"))
    check("syslog forward env", rd("/etc/untrash/syslog-forward.env") == "SERVER=10.0.0.9\nPORT=514\n")
    check("apcupsd BATTERYLEVEL 30, usb, UPS enabled marker", "BATTERYLEVEL 30" in rd("/etc/apcupsd/apcupsd.conf") and
          "UPSTYPE usb" in rd("/etc/apcupsd/apcupsd.conf") and os.path.exists(root + "/etc/untrash/ups.enabled"))
    hc = rd("/etc/untrash/webdav/httpd.conf")
    blocks = {b.split("\n", 1)[0].strip(" []#"): b for b in hc.split("\n# [")[1:]}
    mx = blocks.get("mixed", "")
    check("webdav: ports 5002/5003, external auth", "Listen 5002" in hc and "Listen 5003" in hc and
          "DefineExternalAuth untrash pipe /usr/lib/untrash/untrash-webdav-auth" in hc)
    check("webdav mixed: read admin+alice, write admin, bob nowhere",
          'Alias "/webdav/mixed"' in mx and 'Require user "admin" "alice"' in mx.split("<LimitExcept")[0] and
          'Require user "admin"' in mx.split("<LimitExcept")[1] and "bob" not in mx)
    go, gp = blocks.get("guestonly", ""), blocks.get("guestplus", "")
    check("webdav guestonly (everybody rw): login, every user may write",
          "AuthType Basic" in go and 'Require user "admin" "alice" "bob"' in go.split("<LimitExcept")[1])
    check("webdav guestplus (only the guest), anonymous off: closed", "Require all denied" in gp and "AuthType" not in gp)
    check("webdav: nothing outside /webdav", "<Location />\n  Require all denied" in hc)
    extra = json.loads(rd("/etc/untrash/smb-extra.json"))
    check("smb extra: time machine share + netbios", extra["time_machine"] == "Medien" and extra["netbios"]["name"] == "TESTNAS")

    # importer: printers section like stock smb.conf
    open(root + "/etc/untrash/smb-extra.json", "w").write(json.dumps({"printers": True}))
    imp0 = load(IMPORT, "imp0")
    imp0.SMB_EXTRA = root + "/etc/untrash/smb-extra.json"
    txt0, _sk = imp0.render_smbconf(imp0.Stock(cfg), path_exists=lambda p: True)
    check("smb.conf: printing = cups + [printers] (stock)", "printing = cups" in txt0 and "[printers]" in txt0 and
          "use client driver = yes" in txt0 and "load printers = no" not in txt0)
    # importer: render with the extras (NetBIOS from settings, Time Machine on Medien)
    open(root + "/etc/untrash/smb-extra.json", "w").write(json.dumps({"time_machine": "mixed", "netbios": {
        "name": "NEUNAME", "workgroup": "WG2", "description": "d", "nomaster": False}}))
    imp = load(IMPORT, "imp")
    imp.SMB_EXTRA = root + "/etc/untrash/smb-extra.json"
    stock = imp.Stock(cfg)
    text, _sk = imp.render_smbconf(stock, path_exists=lambda p: True)
    sec = t.sections(text)
    check("smb.conf netbios name from settings", "netbios name = NEUNAME" in text and "workgroup = WG2" in text)
    mixed = text.split("[mixed]")[1].split("\n[")[0]
    check("time machine share: fruit before recycle, both kept", "fruit:time machine = yes" in mixed and
          "vfs objects = catia fruit streams_xattr recycle" in mixed and "recycle:repository = recycle" in mixed)
    check("only the time machine share has fruit", text.count("fruit:time machine") == 1)
    check("other shares unchanged by time machine", sec.keys() == t.sections(text).keys())

    # access as Samba decides it, cross-checked against the rendered rules
    for u in ("admin", "alice", "bob", "pc-guest"):
        groups = [g for _gid, g, _t, _d in stock.groups() if u in stock.members(g)] + (["everyone"] if u != "pc-guest" else [])
        acc = imp.user_access(stock, u, groups)
        for share, a in acc.items():
            sc = sec.get(share, {})

            def listed(key):
                items = sc.get(key, "").replace('"', "").split()
                return u in items or any(i.startswith("+") and i[1:] in groups for i in items)
            if listed("invalid users"):
                want = "deny"
            elif "valid users" in sc:
                want = ("ro" if listed("read list") else "rw") if listed("valid users") else "deny"
            else:
                want = "ro" if listed("read list") else "rw"
            if a["access"] != want:
                check("access %s on %s: %s (smb.conf says %s)" % (u, share, a["access"], want), False)
    check("access() agrees with the rendered smb.conf for 4 users", True)

    # password check: SMB hash via (fake) pdbedit, Unix crypt via shadow
    sys.path.insert(0, os.path.join(FILES, "usr/lib/untrash/pylib"))
    import untrash_auth as ua
    fake = os.path.join(W, "pdbedit")
    open(fake, "w").write("#!/bin/sh\n[ \"$4\" = alice ] && echo 'alice:504:%s:%s:[U          ]:LCT-0:'\nexit 0\n" % (
        "X" * 32, ua.nt_hash("Geheim-1")))
    os.chmod(fake, 0o755)
    ua.PDBEDIT = fake
    ua.SHADOW = os.path.join(W, "shadow")
    open(ua.SHADOW, "w").write("admin:%s:1::::::\n" % ua.unix_crypt("Admin-Pw", "$6$abcdefgh$"))
    check("SMB password accepted", ua.check("alice", "Geheim-1"))
    check("wrong SMB password refused", not ua.check("alice", "geheim-1"))
    check("Unix password (admin) accepted", ua.check("admin", "Admin-Pw"))
    check("unknown user refused", not ua.check("mallory", "x"))
    r = subprocess.run([os.path.join(FILES, "usr/lib/untrash/untrash-checkpw")], input=b"Geheim-1\0",
                       env=dict(os.environ, PAM_USER="alice", ZT_PDBEDIT=fake))
    check("untrash-checkpw (pam_exec) exit 0", r.returncode == 0)
    r = subprocess.run([os.path.join(FILES, "usr/lib/untrash/untrash-checkpw")], input=b"falsch\0",
                       env=dict(os.environ, PAM_USER="alice", ZT_PDBEDIT=fake))
    check("untrash-checkpw wrong password exit 1", r.returncode == 1)

    # untrash-notify against a local SMTP sink
    import socketserver
    import threading
    got = []

    class Smtp(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b"220 sink\r\n")
            data = False
            buf = []
            for line in self.rfile:
                if data:
                    if line == b".\r\n":
                        got.append(b"".join(buf).decode())
                        data = False
                        self.wfile.write(b"250 ok\r\n")
                    else:
                        buf.append(line)
                    continue
                cmd = line[:4].upper()
                if cmd in (b"EHLO", b"HELO"):
                    self.wfile.write(b"250-sink\r\n250 AUTH PLAIN LOGIN\r\n")
                elif cmd == b"AUTH":
                    self.wfile.write(b"235 ok\r\n")
                elif cmd == b"DATA":
                    data, buf = True, []
                    self.wfile.write(b"354 go\r\n")
                elif cmd == b"QUIT":
                    self.wfile.write(b"221 bye\r\n")
                    return
                else:
                    self.wfile.write(b"250 ok\r\n")
    socketserver.TCPServer.allow_reuse_address = True
    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Smtp)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    nconf = os.path.join(W, "notify.json")
    json.dump(dict(nj, server="127.0.0.1", port=srv.server_address[1]), open(nconf, "w"))
    nenv = dict(os.environ, ZT_NOTIFY_CONF=nconf, ZT_NOTIFY_STATE=os.path.join(W, "nstate"), ZT_NOTIFY_VOLROOTS=W + "/vols")
    NOTIFY = os.path.join(FILES, "usr/lib/untrash/untrash-notify")
    r = subprocess.run([NOTIFY, "test"], env=nenv, stdout=subprocess.PIPE, text=True)
    check("test mail to alert + log recipients", r.returncode == 0 and len(got) == 2 and "Subject: NAS-Test Test message" in got[0])
    got.clear()
    r = subprocess.run([NOTIFY, "DegradedArray", "/dev/md2"], env=nenv, stdout=subprocess.PIPE, text=True)
    check("mdadm DegradedArray -> alert mail", r.returncode == 0 and len(got) == 1 and "To: admin@example.net" in got[0]
          and "degraded" in got[0])
    got.clear()
    subprocess.run([NOTIFY, "RebuildStarted", "/dev/md2"], env=nenv, stdout=subprocess.PIPE)
    check("mdadm RebuildStarted: journal only", got == [])
    r = subprocess.run([NOTIFY], env=dict(nenv, SMARTD_MESSAGE="Device: /dev/sda, 8 Currently unreadable sectors",
                                          SMARTD_DEVICE="/dev/sda", SMARTD_FAILTYPE="CurrentPendingSector"), stdout=subprocess.PIPE)
    check("smartd warning -> alert mail", r.returncode == 0 and len(got) == 1 and "SMART warning /dev/sda" in got[0])
    srv.shutdown()

    # untrash-syslogd: one UDP message in the stock file layout
    import socket
    import time as _t
    logdir = os.path.join(W, "logs")
    sconf = os.path.join(W, "syslog-server.json")
    json.dump({"active": True, "path": logdir, "format": "full", "months": 3}, open(sconf, "w"))
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    sd = subprocess.Popen([os.path.join(FILES, "usr/lib/untrash/untrash-syslogd")], stdout=subprocess.PIPE,
                          env=dict(os.environ, ZT_SYSLOGD_CONF=sconf, ZT_SYSLOGD_PORT=str(port), ZT_SYSLOGD_BIND="127.0.0.1"))
    sd.stdout.readline()
    os.makedirs(os.path.join(logdir, "200001"))
    u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    u.sendto(b"<30>Oct 10 12:00:01 router dnsmasq[123]: query example.org", ("127.0.0.1", port))
    tc = socket.create_connection(("127.0.0.1", port))
    tc.sendall(b"<11>Oct 10 12:00:02 switch kernel: link down\n")
    tc.close()
    _t.sleep(0.8)
    sd.terminate()
    files = glob.glob(os.path.join(logdir, _t.strftime("%Y%m"), "127.0.0.1_%s.txt" % _t.strftime("%Y%m%d")))
    lines = open(files[0]).read().splitlines() if files else []
    check("syslogd: stock path, full format (udp + tcp)", len(lines) == 2 and
          lines[0].split("\t") == ["Oct 10 12:00:01", "router", "dnsmasq", "1e", "daemon", "info", "query example.org"]
          and lines[1].split("\t")[4:6] == ["user", "err"])
    check("syslogd: month folders older than 3 months pruned", not os.path.exists(os.path.join(logdir, "200001")))

    # WebDAV auth chain: untrash-webdav-auth (www-data) -> socket -> untrash-authd (root)
    sock = os.path.join(W, "authd.sock")
    ls = socket.socket(socket.AF_UNIX)
    ls.bind(sock)
    ls.listen(2)

    def authd_once():
        for _ in range(2):
            c, _a = ls.accept()
            subprocess.run([os.path.join(FILES, "usr/lib/untrash/untrash-authd")], stdin=c, stdout=c,
                           env=dict(os.environ, ZT_PDBEDIT=fake, ZT_SHADOW=ua.SHADOW))
            c.close()
    th = threading.Thread(target=authd_once, daemon=True)
    th.start()
    WA = os.path.join(FILES, "usr/lib/untrash/untrash-webdav-auth")
    r1 = subprocess.run([WA], input=b"alice\nGeheim-1\n", env=dict(os.environ, ZT_AUTHD_SOCK=sock))
    r2 = subprocess.run([WA], input=b"alice\nfalsch\n", env=dict(os.environ, ZT_AUTHD_SOCK=sock))
    check("webdav auth: right password 0, wrong 1", r1.returncode == 0 and r2.returncode == 1)

    # untrash-power: MCU commands (logged), RTC alarm, schedule (board tool, ZT_BOARD_ROOTFS)
    BOARD = os.environ.get("ZT_BOARD_ROOTFS")
    if not BOARD:
        print("skip untrash-power checks (board tool; set ZT_BOARD_ROOTFS)")
    else:
        PW = os.path.join(BOARD, "usr/lib/untrash/untrash-power")
        pset = os.path.join(W, "power.json")
        plog = os.path.join(W, "i2c.log")
        walarm = os.path.join(W, "wakealarm")
        penv = dict(os.environ, ZT_SETTINGS=pset, ZT_POWER_I2C_LOG=plog, ZT_POWER_WAKEALARM=walarm, ZT_POWER_STATE=os.path.join(W, "ptick"))

        def prun(power, cmd):
            json.dump({"power": power}, open(pset, "w"))
            if os.path.exists(plog):
                os.unlink(plog)
            r = subprocess.run([PW, cmd], env=penv, stdout=subprocess.PIPE, text=True)
            return r.returncode, (open(plog).read().split("\n")[:-1] if os.path.exists(plog) else []), r.stdout
        check("boot former + WoL off: 0x0107, 0x0306 (stock rcS2)", prun({"pwron": "former", "wol": False}, "boot")[1] == ["0x0a 0x0107", "0x0a 0x0306"])
        check("boot never + WoL on: 0x0007, 0x0006", prun({"pwron": "never", "wol": True}, "boot")[1] == ["0x0a 0x0007", "0x0a 0x0006"])
        now = _d.datetime.now()
        soon = now + _d.timedelta(days=2)
        rc, lg, out = prun({"pwron": "former", "schedule_active": True, "schedule": [{"action": "on", "kind": "monthly", "mday": soon.day,
                                                                                        "hour": 6, "minute": 45}]}, "shutdown")
        want = int(_d.datetime(soon.year, soon.month, soon.day, 6, 45).timestamp())
        check("shutdown former: 0x0007 (stock rc.shutdown) and RTC alarm at the next power-on", rc == 0 and lg == ["0x0a 0x0007"]
              and open(walarm).read() == str(want))
        rc, lg, out = prun({"pwron": "always", "schedule_active": False, "schedule": []}, "shutdown")
        check("shutdown always, no schedule: no MCU write, alarm cleared", lg == [] and open(walarm).read() == "0")
        t = now + _d.timedelta(minutes=0)
        open(os.path.join(W, "ptick"), "w").write(str((now - _d.timedelta(minutes=1)).timestamp()))
        rc, lg, out = prun({"schedule_active": True, "schedule": [{"action": "off", "kind": "daily", "hour": t.hour, "minute": t.minute}]}, "tick")
        check("tick: scheduled power-off due now", "systemctl poweroff" in lg)
        rc, lg, out = prun({"schedule_active": True, "schedule": [{"action": "off", "kind": "daily", "hour": t.hour, "minute": t.minute}]}, "tick")
        check("tick: not twice", lg == [])
        rc, lg, out = prun({"schedule_active": True, "schedule": [{"action": "on", "kind": "daily", "hour": 7, "minute": 0},
                                                                  {"action": "reboot", "kind": "weekly", "day": 6, "hour": 3, "minute": 0}]}, "next")
        nj = json.loads(out)
        check("next: on daily 07:00, reboot Sunday 03:00", nj["on"].endswith("07:00") and nj["off_action"] == "reboot" and
              _d.datetime.fromisoformat(nj["off"]).weekday() == 6)

    # RESET button: 2 s network + admin window, 7 s factory defaults
    renv = dict(env, ZT_RUN_DIR=os.path.join(W, "run"), ZT_STATE_LIB=os.path.join(W, "lib"))
    s4 = json.load(open(env["ZT_SETTINGS"]))
    s4["network"]["eth0"] = {"mode": "static", "address": "10.9.9.9/24", "gateway": "", "mtu": 1500}
    s4["network"]["bond"]["active"] = True
    json.dump(s4, open(env["ZT_SETTINGS"], "w"))
    r = subprocess.run([sys.executable, CFG_TOOL, "reset-network", "--no-apply"], env=renv, stdout=subprocess.PIPE, text=True)
    s5 = json.load(open(env["ZT_SETTINGS"]))
    check("reset 2 s: DHCP, bond off, admin window marker, other settings kept", r.returncode == 0 and s5["network"]["eth0"]["mode"] == "dhcp"
          and not s5["network"]["bond"]["active"] and os.path.exists(os.path.join(W, "run", "admin-reset")) and s5["hostname"] == "TestNAS")
    fr = os.path.join(W, "fr")
    os.makedirs(fr + "/zyxel/stock-config")
    shutil.copy(env["ZT_SETTINGS"], fr + "/settings.json")
    shutil.copy(os.path.join(cfg, "ugs_conf.db"), fr + "/zyxel/stock-config/ugs_conf.db")
    os.makedirs(fr + "/tls")
    open(fr + "/tls/untrash.key", "w").write("k")
    r = subprocess.run([sys.executable, CFG_TOOL, "factory-reset", "--no-apply"], env=dict(renv, ZT_SETTINGS=fr + "/settings.json"),
                       stdout=subprocess.PIPE, text=True)
    tars = glob.glob(os.path.join(W, "lib", "factory-reset-*.tar"))
    names = subprocess.run(["tar", "-tf", tars[0]], stdout=subprocess.PIPE, text=True).stdout.split() if tars else []
    check("reset 7 s: old configuration archived (0600), DB and keys gone, settings default", r.returncode == 0 and tars and
          os.stat(tars[0]).st_mode & 0o777 == 0o600 and "settings.json" in names and "zyxel/stock-config/ugs_conf.db" in names
          and not os.path.exists(fr + "/zyxel/stock-config/ugs_conf.db") and not os.path.exists(fr + "/tls")
          and json.load(open(fr + "/settings.json"))["hostname"] == "untrash")

    # untrash-upnp against a simulated router
    st_file = os.path.join(W, "upnp-state.json")
    uenv = dict(os.environ, ZT_SETTINGS=env["ZT_SETTINGS"], ZT_UPNPC=os.path.join(HERE, "fake-upnpc"), ZT_FAKE_UPNP_STATE=st_file)
    UP = os.path.join(FILES, "usr/lib/untrash/untrash-upnp")
    r = subprocess.run([UP, "apply"], env=uenv, stdout=subprocess.PIPE, text=True)
    st = json.loads(subprocess.run([UP, "status"], env=uenv, stdout=subprocess.PIPE, text=True).stdout)
    ours = {m["description"]: (m["wan_port"], m["lan_port"]) for m in st["mappings"] if m["ours"]}
    check("upnp apply: the stock Desk HTTP forward is NOT made (unencrypted sign-in), WebDAV 5002, foreign mapping kept",
          r.returncode == 0 and "not forwarded: HTTP" in r.stdout and ours == {"UntrashOS WEBDAV_HTTP": (5002, 5002)}
          and any(m["description"] == "foreign" for m in st["mappings"]) and st["external_ip"] == "203.0.113.5")
    s3 = json.load(open(env["ZT_SETTINGS"]))
    s3["upnp"]["services"] = {"HTTPS": 8443}
    json.dump(s3, open(env["ZT_SETTINGS"], "w"))
    subprocess.run([UP, "apply"], env=uenv, stdout=subprocess.PIPE)
    st = json.loads(subprocess.run([UP, "status"], env=uenv, stdout=subprocess.PIPE, text=True).stdout)
    check("upnp: changed service remapped, removed service unmapped", {m["description"]: m["wan_port"] for m in st["mappings"] if m["ours"]} == {"UntrashOS HTTPS": 8443})
    # a FritzBox shows the description as "UntrashOS.HTTPS": still ours, so it is removed when switched off
    os.remove(st_file)
    denv = dict(uenv, ZT_FAKE_UPNP_DOT="1")
    subprocess.run([UP, "apply"], env=denv, stdout=subprocess.PIPE)
    st = json.loads(subprocess.run([UP, "status"], env=denv, stdout=subprocess.PIPE, text=True).stdout)
    check("upnp (FritzBox names): \"UntrashOS.HTTPS\" counts as ours", [(m["description"], m["service"]) for m in st["mappings"] if m["ours"]]
          == [("UntrashOS.HTTPS", "HTTPS")])
    s3["upnp"]["services"] = {}
    json.dump(s3, open(env["ZT_SETTINGS"], "w"))
    subprocess.run([UP, "apply"], env=denv, stdout=subprocess.PIPE)
    st = json.loads(subprocess.run([UP, "status"], env=denv, stdout=subprocess.PIPE, text=True).stdout)
    check("upnp (FritzBox names): switched off -> the mapping is removed (2026-11-03: it stayed forever)",
          not [m for m in st["mappings"] if m["ours"]] and any(m["description"] == "foreign" for m in st["mappings"]))

    # network name: default "untrash"; Avahi's conflict name is kept (untrash-2), a name of its own never changes
    check("import: stock hostname is not automatic", s["hostname_auto"] is False)
    nset = os.path.join(W, "net.json")
    fb = os.path.join(W, "fake-busctl")
    open(fb, "w").write("#!/bin/sh\ncase $5 in GetState) echo 'i 2' ;; GetHostName) echo 's \"'$ZT_FAKE_AVAHI'\"' ;; esac\n")
    os.chmod(fb, 0o755)
    nenv = dict(os.environ, ZT_SETTINGS=nset, ZT_BUSCTL=fb, ZT_RENDER_ROOT=os.path.join(W, "netroot"),
                ZT_RUN_DIR=os.path.join(W, "netrun"), ZT_NETNAME_STEP="0", ZT_FAKE_AVAHI="untrash")
    subprocess.run([sys.executable, CFG_TOOL, "netname"], env=nenv, check=True)
    n = json.load(open(nset)) if os.path.exists(nset) else {}
    check("netname: default untrash, no conflict -> nothing written", n == {})
    json.dump({}, open(nset, "w"))
    subprocess.run([sys.executable, CFG_TOOL, "netname"], env=dict(nenv, ZT_FAKE_AVAHI="untrash-2"), check=True)
    n = json.load(open(nset))
    check("netname: Avahi chose untrash-2 -> kept (hostname, NetBIOS, /etc/hostname)",
          n["hostname"] == "untrash-2" and n["netbios"]["name"] == "UNTRASH-2" and n["hostname_auto"]
          and open(os.path.join(W, "netroot/etc/hostname")).read() == "untrash-2\n")
    n["hostname"], n["hostname_auto"] = "keller", False
    json.dump(n, open(nset, "w"))
    subprocess.run([sys.executable, CFG_TOOL, "netname"], env=dict(nenv, ZT_FAKE_AVAHI="keller-2"), check=True)
    check("netname: the admin's name stays", json.load(open(nset))["hostname"] == "keller")

print("FAILURES %d" % fails)
sys.exit(1 if fails else 0)
