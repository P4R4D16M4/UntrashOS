#!/usr/bin/env python3
"""Offline tests for untrash-import-zyxel (no root, no hardware).

  python3 image/tests/test_import_zyxel.py

With ZT_STOCK_SHARE_FUNC=<decompiled stock share_func.py> the share sections
are also compared against the stock get_share_smbconf() (the decompiled
vendor code stays local, it is not part of the repository).
"""
import importlib.machinery
import importlib.util
import os
import re
import sqlite3
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "rootfs", "usr", "sbin", "untrash-import-zyxel")


def load_tool():
    loader = importlib.machinery.SourceFileLoader("untrash_import_zyxel", TOOL)
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# Stock schema (share_func.create_share_table, user_grp_func.create_user_grp_table)
SCHEMA = """
CREATE TABLE smb_user (uid integer PRIMARY KEY NOT NULL, uname TEXT NOT NULL, create_type TEXT, utype TEXT, passwd TEXT, description TEXT, UNIQUE (uname COLLATE NOCASE));
CREATE TABLE smb_group (gid integer PRIMARY KEY NOT NULL, gname TEXT NOT NULL, gtype TEXT, description TEXT, UNIQUE (gname COLLATE NOCASE));
CREATE TABLE group_member (gid integer, gname TEXT, uid integer, uname TEXT);
CREATE TABLE ugs_misc (key TEXT PRIMARY KEY NOT NULL, value TEXT);
CREATE TABLE smb_share (s_name TEXT primary key NOT NULL, s_path TEXT NOT NULL, create_type TEXT, s_desc TEXT, s_enable TEXT, browseable TEXT, recycle TEXT, mdaserv_public_type INT, web_public TEXT, UNIQUE (s_name COLLATE NOCASE));
CREATE TABLE share_user_privilege (s_name TEXT, uid INT, uname TEXT, privilege TEXT);
CREATE TABLE share_group_privilege (s_name TEXT, gid INT, gname TEXT, privilege TEXT);
"""
H = "B757BF5C0D87772FAAD3B435B51404EE:7CE21F17C0AEE7FB9CEBA532D0546AD6"  # stock default "1234"
USERS = [(501, "admin", "bulit-in", "admin", H, ""), (502, "pc-guest", "bulit-in", "guest", H, ""),
         (504, "alice", "user-create", "user", H, "A"), (505, "bob", "user-create", "user", H, "")]
GROUPS = [(500, "everyone", "local", "System default group"), (501, "family", "local", "")]
MEMBERS = [(500, "everyone", 504, "alice"), (500, "everyone", 505, "bob"), (501, "family", 504, "alice")]
SHARES = [  # s_name, s_path, create_type, desc, enable, browseable, recycle
    ("admin", "/i-data/sysvol/admin", "built-in", "System default share", "y", "y", "n"),
    ("guestonly", "/i-data/aaaa0001/guestonly", "user-create", "", "y", "y", "n"),
    ("mixed", "/i-data/aaaa0001/mixed", "user-create", "Mixed", "y", "n", "y"),
    ("groups", "/i-data/aaaa0001/groups", "user-create", "", "y", "y", "n"),
    ("nobody", "/i-data/aaaa0001/nobody", "user-create", "", "y", "y", "n"),
    ("guestplus", "/i-data/aaaa0001/guestplus", "user-create", "", "y", "y", "n"),
    ("off", "/i-data/aaaa0001/off", "user-create", "", "n", "y", "n"),
    ("gone", "/i-data/bbbb0002/gone", "user-create", "", "y", "y", "n"),
]
UPRIV = [("admin", "admin", "rw"), ("guestonly", "pc-guest", "rw"),
         ("mixed", "admin", "rw"), ("mixed", "alice", "ro"), ("mixed", "bob", "deny"),
         ("groups", "admin", "rw"),
         ("guestplus", "pc-guest", "rw"), ("guestplus", "bob", "deny")]
GPRIV = [("groups", "family", "ro"), ("groups", "everyone", "deny")]


def make_db(path):
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    c.executemany("INSERT INTO smb_user VALUES (?,?,?,?,?,?)", USERS)
    c.executemany("INSERT INTO smb_group VALUES (?,?,?,?)", GROUPS)
    c.executemany("INSERT INTO group_member VALUES (?,?,?,?)", MEMBERS)
    c.execute("INSERT INTO ugs_misc VALUES ('admin_shadow_passwd', '$1$$iC.dUsGpxNNJGeOm1dFio/')")
    c.executemany("INSERT INTO smb_share VALUES (?,?,?,?,?,?,?,0,'n')", SHARES)
    uid = {u[1]: u[0] for u in USERS}
    gid = {g[1]: g[0] for g in GROUPS}
    c.executemany("INSERT INTO share_user_privilege VALUES (?,?,?,?)",
                  [(s, uid[u], u, p) for s, u, p in UPRIV])
    c.executemany("INSERT INTO share_group_privilege VALUES (?,?,?,?)",
                  [(s, gid[g], g, p) for s, g, p in GPRIV])
    c.commit()
    c.close()


PYCONF = """[system]
    hostname = NAS540
    [[servername]]
        servername = TESTNAS
        description = Test box
        workgroupname = TESTWG
        nomaster = false
[backup]
    [[time_machine]]
        active = false
"""

ACCESS_KEYS = ("path", "browseable", "valid users", "read list", "invalid users", "guest ok",
               "recycle:repository", "comment")


def sections(text):
    out, cur = {}, None
    for line in text.splitlines():
        m = re.match(r"\s*\[(.+)\]\s*$", line)
        if m:
            cur = out.setdefault(m.group(1), {})
            continue
        m = re.match(r"\s*([^=]+?)\s*=\s*(.*)$", line)
        if m and cur is not None and m.group(1) in ACCESS_KEYS:
            cur[m.group(1)] = m.group(2).strip()
    return out


def stock_render(share_func_py, dbpath):
    """Run the decompiled stock get_share_smbconf() against the test DB."""
    src = open(share_func_py).read()
    start = src.index("def get_share_smbconf(")
    end = src.index("\ndef ", start + 10)
    ns = {"ENABLE": "y", "SHARE_ACCESS_RO": "ro", "SHARE_ACCESS_RW": "rw",
          "SHARE_ACCESS_DENY": "deny", "SMB_GUEST_NAME": "pc-guest", "DEFAULT_GRP_NAME": "everyone",
          "path": types.SimpleNamespace(isdir=lambda p: "gone" not in p, realpath=lambda p: p),
          "get_mntpnt_fstype_map": lambda: {"/i-data/sysvol": "ext4", "/i-data/aaaa0001": "ext4",
                                            "/i-data/bbbb0002": "ext4"}}
    exec(src[start:end], ns)
    c = sqlite3.connect(dbpath)

    class Db:
        def fetchall(self, sql, a=()):
            return c.execute(sql, a).fetchall()

        def fetchcol(self, sql, a=()):
            return [r[0] for r in c.execute(sql, a).fetchall()]
    return ns["get_share_smbconf"](Db())


def main():
    tool = load_tool()
    failures = 0
    def expect(cond, what):
        nonlocal failures
        print(("ok   " if cond else "FAIL ") + what)
        failures += 0 if cond else 1

    # LVM occasionally writes a warning before its otherwise successful
    # stdout report.  It must never be interpreted as a VG/LV name.
    original_run = tool.run
    try:
        tool.run = lambda cmd: types.SimpleNamespace(
            stdout='WARNING: old metadata seen\\n{"report":[{"pv":[{"vg_name":"vg_stock"}]}]}\\n')
        expect(tool.lvm_report_names(["pvs"], "pv", "vg_name") == ["vg_stock"],
               "LVM JSON report ignores diagnostic prefix")
        tool.run = lambda cmd: types.SimpleNamespace(
            stdout='{"report":[{"pv":[{"vg_name":"WARNING:"},{"vg_name":"vg_stock"}]}]}\\n')
        expect(tool.lvm_report_names(["pvs"], "pv", "vg_name") == ["vg_stock"],
               "LVM report ignores warning token in a report cell")
    finally:
        tool.run = original_run
    with tempfile.TemporaryDirectory() as d:
        make_db(os.path.join(d, "ugs_conf.db"))
        with open(os.path.join(d, "py_conf"), "w") as f:
            f.write(PYCONF)
        stock = tool.Stock(d)
        text, skipped = tool.render_smbconf(stock, path_exists=lambda p: "gone" not in p)
        ours = sections(text)

        expect("workgroup = TESTWG" in text and "netbios name = TESTNAS" in text, "py_conf servername")
        expect("off" not in ours, "disabled share left out")
        expect(skipped == [("gone", "/i-data/bbbb0002/gone")], "missing path reported, not rendered")
        expect(ours["guestonly"].get("guest ok") == "yes" and "valid users" not in ours["guestonly"],
               "guest-only share: guest ok, no valid users")
        expect(ours["mixed"].get("valid users") == '"admin" "alice"' and ours["mixed"].get("read list") == '"alice"'
               and ours["mixed"].get("invalid users") == '"bob"', "mixed rw/ro/deny")
        expect(ours["mixed"].get("browseable") == "no" and "recycle:repository" in ours["mixed"], "browseable/recycle")
        expect(ours["nobody"].get("valid users") == "nobody", "no privileges -> nobody")
        expect(ours["guestplus"].get("guest ok") == "yes" and ours["guestplus"].get("valid users") == '"pc-guest"',
               "guest plus deny keeps valid users (stock rule)")
        expect(ours["groups"].get("read list") == '"+family"' and ours["groups"].get("invalid users") == '"+everyone"',
               "group privileges")
        expect(stock.admin_shadow().startswith("$1$"), "admin shadow hash")

        sf = os.environ.get("ZT_STOCK_SHARE_FUNC")
        if sf:
            ref = sections(stock_render(sf, os.path.join(d, "ugs_conf.db")))
            expect(set(ref) == set(ours) - {"global"}, "same share set as stock (%s)" % sorted(ref))
            for name, kv in sorted(ref.items()):
                mine = {k: v for k, v in ours.get(name, {}).items()}
                mine.pop("recycle:repository", None)
                kv = dict(kv)
                kv.pop("recycle:repository", None)
                expect(mine == kv, "stock-equivalent [%s]" % name + ("" if mine == kv else
                                                                     " ours=%s stock=%s" % (mine, kv)))
        else:
            print("skip stock comparison (ZT_STOCK_SHARE_FUNC not set)")
    print("FAILURES %d" % failures)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
