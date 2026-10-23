# Taking over a stock NAS542

How UntrashOS reads the disks and the configuration of the Zyxel firmware and
continues with them (installer ways B and C).  Tool:
`image/rootfs/usr/sbin/untrash-import-zyxel`; settings:
`untrash-config import-stock`.

Evidence tags: `[DEC]` decompiled stock models (firmware 5.21(ABAG.15),
`web_framework/models/*.pyc`), `[NAND]` read from the stock configuration
partition, `[TEST]` covered by a PC test in `image/tests/`.

## 1. Disk layout of the stock firmware `[DEC storage_def/storage_func]`

Every internal disk: GPT, three partitions, all with the `raid` flag.

| Part. | Range | md | Content |
|---|---|---|---|
| 1 | 0 – 2048 MB (3 997 696 sectors) | `md0` | firmware, RAID1 over all four bays (`missing` for empty ones), metadata **1.2**, ext4 |
| 2 | 2048 – 4096 MB (3 999 744 sectors) | `md1` | swap, RAID1 like md0 |
| 3 | 4096 MB – end | `md2…md5` | data: `linear` (JBOD), `raid0`, `raid1` (also "basic" with one disk), `raid5`, `raid6`, `raid10`; metadata **1.2**, chunk 64 KiB |

Volumes on a data array come in two types:
- **md:** ext4 directly on the array, mounted at `/i-data/<md-uuid8>` (first
  8 hex digits of the md UUID).
- **lvm:** PV on the array, VG `vg_<md-uuid8>` with `vg_info_area` (100 MiB,
  ext4, mounted at `/mnt/vg_info_area/<vg>`, holds the disk group name) and one
  `lv_<rand8>` per volume, mounted at `/i-data/<rand8>`.  LVs are linear.
- ext4: `mkfs.ext4 -E discard,stride=16,stripe-width=16*n -b 4096 -j -m 0
  -O large_file,extents,uninit_bg`; mounted
  `rw,usrquota,noatime,data=ordered,barrier=1`, then `chmod 777` on the mount
  point and `quotaon -u`.
- Display name: `<mnt>/.system/name_label`.  System volume: file
  `<mnt>/.system/sysvol_<MAC without colons>`; links `/i-data/sysvol`,
  `/i-data/.system`, `/i-data/.media`.  Default folders `admin/download/torrent`,
  `music`, `photo`, `video`.
- USB: `/e-data/<uuid>`, name table `/etc/zyxel/storage/extuuid.table`
  (`Name|UUID`); file systems FAT16/32, NTFS, exFAT, ext2/3/4, HFS+, ISO9660/UDF.

## 2. Where the configuration lives `[NAND]`

`/etc/zyxel` is UBIFS in the UBI volume `ubi_config` on the NAND partition
"config" (offset 0, 10 MiB; 80 PEBs of 128 KiB, VID header at 2048, data at
4096).

| File | Content |
|---|---|
| `ugs_conf.db` | SQLite: users, groups, members, shares, permissions (§3) |
| `py_conf` | ConfigObj: `system.hostname`, `system.servername.*`, `system.date_time.*`, `network.interface.*`, `backup.time_machine.*`, services (http/https/ssh/ftp/…) |
| `storage/extuuid.table`, `storage/pwron.int` | USB names; power-on behaviour |
| `webdav/*.flag`, `storage/enable_nfs.flag`, `hd-idle.conf`, `pkg_conf/` | service switches, spin-down, packages |
| `ssh/`, `cert/` | host and TLS keys (SSH host keys are not taken over) |

## 3. Users, groups, shares `[DEC ugs_comm_def/user_grp_func/share_func]`

Schema of `ugs_conf.db`: `smb_user(uid, uname, create_type, utype, passwd,
description)`, `smb_group(gid, gname, gtype, description)`,
`group_member(gid, gname, uid, uname)`, `ugs_misc(key, value)`,
`smb_share(s_name, s_path, create_type, s_desc, s_enable, browseable, recycle,
mdaserv_public_type, web_public)`, `share_user_privilege(s_name, uid, uname,
privilege)`, `share_group_privilege(s_name, gid, gname, privilege)`.

- UIDs: `admin` 501, guest `pc-guest` 502, own users from 504; group
  `everyone` GID 500 (primary group of all).
- `smb_user.passwd` = `LM:NT` (32 hex digits each); imported with
  `pdbedit -i smbpasswd:`, so **SMB passwords stay valid**.
- Unix password only for `admin`/`root`: md5-crypt in
  `ugs_misc.admin_shadow_passwd`.
- Permissions `rw`/`ro`/`deny` per user or group apply **only in Samba**; on
  the file system everything is 0777 (`force create mode`/`force directory
  mode` 777).  Rules of `get_share_smbconf()`: `valid users` = all rw+ro
  (groups with `+`), omitted when only `pc-guest` and no ro/deny;
  `read list` = ro; `invalid users` = deny; `pc-guest` in rw/ro →
  `guest ok = yes`; no permissions at all → `valid users = nobody`,
  `invalid users = +everyone`.  Shares with `s_enable=n` or a missing path are
  left out.  Recycle bin: `vfs recycle`, folder `recycle`.
- Global: `map to guest = Bad User`, `guest account = pc-guest`,
  `security = user`, workgroup and name from `py_conf`.

## 4. Importer `untrash-import-zyxel`

| Command | Effect | Writes |
|---|---|---|
| `config-from-nand DEST` | attach UBI on NAND "config" (parent MTD not writable → UBI `ro_mode`), mount UBIFS `ro`, copy the tree to DEST | DEST only |
| `volumes [--mount]` | find and classify the stock arrays (`mdadm --examine`); `--mount`: `mdadm --assemble --readonly`, LVM with `metadata_read_only=1` + `read_only_volume_list`, ext4 `ro,noload` under `/i-data` (tmpfs), sysvol links | nothing on the disks |
| `release` | unmount, deactivate VGs, stop arrays | – |
| `plan CONFIG` | users, groups, shares, path present/missing | – |
| `render CONFIG [--out F]` | smb.conf by the stock rules | F |
| `apply CONFIG --yes-take-over` | conflict check (UID/GID/names), copy to `/etc/untrash/zyxel/stock-config`, groups and users with the stock IDs, admin hash, SMB hashes into tdbsam, `takeover.json`; then `untrash-zyxel.service` (volumes `rw,usrquota` after `e2fsck -p`, smb.conf, Samba) | the system, and after confirmation the volumes |

Protection in the image (`mkslot-erofs.sh`): `mdadm.conf` `AUTO -all` and LVM
`auto_activation_volume_list = []`, so udev never assembles plugged-in stock
disks on its own.  Samba stays off until `apply`.

Differences from stock: tdbsam instead of an smbpasswd file, no LANMAN, no
`wide links`; Time Machine over SMB (`vfs_fruit`) instead of AFP.  The old
paths (`/i-data/<id>/…`, `/i-data/sysvol`) stay the same.

## 5. Settings and stock functions

`untrash-config import-stock` (after `untrash-import-zyxel apply`, service
`untrash-takeover-firstboot`) writes `/etc/untrash/settings.json`;
`untrash-config render/apply` generates the system files from it.  A service
runs only if it was on under stock.  Test:
`image/tests/test_untrash_config.py` `[TEST]`.

| Stock | Source | UntrashOS |
|---|---|---|
| Users, groups, shares, permissions, SMB passwords, admin password | `ugs_conf.db` | as in §4; sign-in to Untrash Desk and FTP with the **SMB password** (NT hash against tdbsam, `pylib/untrash_auth.py`, PAM `pam_exec`) |
| Host name, NetBIOS name, description, workgroup | `py_conf system.*` | `/etc/hostname`, smb.conf |
| Time zone `+01:00/City`, NTP server | `system.date_time` | IANA zone, chrony |
| LAN 1/2 DHCP or static, MTU, manual DNS | `network.interface.egiga0/1`, `nameserver` | systemd-networkd; the stock MAC addresses are kept |
| SSH on/port/SFTP | `system.service.ssh` | sshd, `AllowUsers root admin` |
| FTP: port, TLS, anonymous, connections, passive range, rates | `system.service.ftp` | vsftpd; per user a view `/run/untrash/ftp/<user>` of bind mounts with exactly the share permissions |
| NFS | `storage/enable_nfs.flag`, exports | nfs-kernel-server |
| Media server (DLNA) per share video/photo/music | `mdaserv_public_type` (1/2/4) | minidlna `media_dir=VPA,…` |
| Time Machine | `backup.time_machine` | SMB with `vfs_fruit` on the target share, Avahi |
| Recycle bin per share, expiry in days | `recycle`, `ugs_misc.rbm_expire_day` | `vfs recycle`, timer `untrash-recycle-expire` |
| Disk spin-down | `hd-idle.conf`, `pwrmg.pwr_turnOffHD` | hd-idle |
| USB volumes `/e-data/<md5(UUID)>`, names | `storage/extuuid.table`, `storage_func` | `untrash-usb` (udev), same paths and mount options per file system |
| User quotas | `aquota.user` on the volumes | stay in effect (`usrquota`, `quotaon`); `setquota`/`repquota` in the Desk |
| RAID and volume management (basic/JBOD/0/1/5/6/10, volume directly or disk group/LVM, repair, add disks, basic→1→5→6, spare, expand, delete, rename; LVM volumes) | `storage_func`/`storage_submain` `[DEC]` | `untrash-storage` with the same commands and the same on-disk format (§1); Desk "Storage" with a job log and typed confirmation; test `test-storage-host.sh` `[TEST]`.  `--chunk` only for striped levels (current mdadm refuses it for RAID1) |
| WebDAV (`webdav/dav.flag`, `dav_anonymous.flag`) | Apache mod_dav `[DEC]` | `apache2-bin` + `mod_authnz_external` as `untrash-webdav.service`, `http://NAS:5002/webdav/<share>`, https 5003 (as stock); read for ro+rw, write for rw only; anonymous = guest shares; sign-in with the SMB password through `untrash-authd`; test `test-webdav-host.py` `[TEST]` |
| DynDNS (`system.service.dydns`) | `dydns_main_model` `[DEC]` | inadyn 2; providers dyndns, noip, 3322, zoneedit (+ duckdns, freedns, dynv6); providers that no longer exist are listed as not taken over |
| E-mail notification (`maintenance.log.mail`) | `zylog_main_model` `[DEC]` | `untrash-notify`: alerts on mdadm events, SMART, volume ≥ 95 %; log report by `untrash-log-report.timer` (hourly/daily/weekly as stock); test mail from the Desk |
| Syslog to a server (`maintenance.log.syslog`) | `zylog_main_model` `[DEC]` | `untrash-syslog-forward` (journal → RFC 3164/UDP) |
| Syslog server (`syslog-ng/enable_syslog.flag`, `syslog.table`) | `syslogng_main_model` `[DEC]` | `untrash-syslogd` (514 UDP+TCP), files `<path>/<YYYYMM>/<source IP>_<YYYYMMDD>.txt`, formats simple/full/custom, old months deleted |
| UPS (apcupsd on hotplug, `pwr_minimumUPSCapacity` → `BATTERYLEVEL`) | `pwrmg_main_model` `[DEC]` | apcupsd, started by a udev rule when an APC UPS is plugged in |
| Web publishing (`system.service.webpublish`, `smb_share.web_public`) | `web_publish_main_model` `[DEC]` | port 80: the Desk serves `/MyWeb/<share>` (public, read-only, sandboxed); another port: Apache virtual host as stock |
| Link aggregation (`network.interface.bond0`) | `network_main_model_back` `[DEC]` | systemd-networkd `bond0`, same modes, miimon 100 |
| Printers (USB, CUPS raw queues, Samba `[printers]`) | `prt_main_model` `[DEC]` | `cups-daemon`, `untrash-printer` (udev `usblp`), `[printers]` as stock; Desk: list, delete jobs |
| Cloud apps: Dropbox, Google Drive, Upload Manager (FTP) | stock App Center | `untrash-cloud` + rclone: accounts, two-way (`bisync`), upload only, download only, interval; Desk "Cloud"; test `test-cloud-host.py` `[TEST]` |
| Download service (HTTP/FTP/BitTorrent/magnet, target and watched folder, bandwidth, time window, seeding, BT port, DHT, mail) | `dservice_main_model` `[DEC]` | aria2 (`untrash-aria2.service`, RPC local only), `untrash-downloads`; Desk "Downloads" |
| Backup Planner (archive with versions, sync, rsync to another NAS; schedule, retention, bandwidth, restore) | `BackupPlanner_main_model` `[DEC]` | `untrash-backup` with rsync (archive = dated folders with hard links), timer; Desk "Backup"; test `test-backup-host.py`.  Stock archives (zydar format) and stock jobs (`backupjob.db`) are **not** taken over |
| COPY/SYNC button (`storage/usbcopy.table`, `usbzync.table`) | `copy_sync_btn_main_model` `[DEC]` | `untrash-copybtn` (short press = copy to `<date>/Extvolume<N>`, 3 s = sync; LED copy-green/-red); Desk "COPY button"; test `test-copybtn-host.py` |
| RESET button (2 s: IP + admin password, 7 s: factory defaults, data kept) | stock help | same button service; 2 s = DHCP + 15 minutes "new admin password without sign-in" in the Desk; 7 s = settings, users and shares to defaults, old configuration kept as `/var/lib/untrash/factory-reset-*.tar` |
| HTTPS for the web interface, certificate (`/etc/zyxel/cert/default.cer`, `key/default_key.cer`) | `CA_main_model` `[DEC]` | Desk with TLS port and redirect; the stock certificate is taken over; create/upload in the Desk; also used by FTPS and WebDAV |
| UPnP port forwarding (`upnp.db`) | `upnp_main_model` `[DEC]` | `untrash-upnp` (miniupnpc), renewed by a timer; Desk "Network" |
| iSCSI (LIO, file LUNs `<volume>/.iscsi_Lun/`, CHAP/mutual, initiator list) | `iscsi_main_model` `[DEC]` | `untrash-iscsi` directly over configfs; Desk "Storage"; test `test-iscsi-host.py`.  Existing LUN files stay; stock targets are not recreated automatically |
| Photo, music and video apps | stock apps | Files window: photo viewer, audio/video player, PDF reader |
| After power loss (`pwr_pwron` 1/2/3), Wake-on-LAN (`pwr_wol`) | `pwrmg_main_model`, `rcS2`, `rc.shutdown` `[DEC]` | `untrash-power` (board MCU 0x0a, same commands as stock) |
| Power on/off/restart schedule (`backupjob.db` types 6/7/8) | `pwrmg_main_model`, `rtcAccess` `[DEC]` | power-on through the RTC alarm (`rtc-ht1382` `wakealarm`, set at shutdown), off/restart by timer; Desk "Power".  "Monthly by week" is not taken over |
| Bays and bay LEDs | `storage_def` `DISKX_BUS_MAP` | `pylib/untrash_bays.py` (detect GPIOs, table `/etc/untrash/bays.json`), green/red LEDs (`untrash-leds.timer`) |

Not taken over (listed in `settings.unsupported` after the takeover if they
were on under stock): Telnet, iTunes server (DAAP), Upload Manager to
Flickr/YouTube, Memopal, myZyXELcloud, rsync server.

## 6. Tests

- `image/tests/test_import_zyxel.py`: synthetic stock database with every
  permission case.  With `ZT_STOCK_SHARE_FUNC=<decompiled share_func.py>` the
  generated shares are compared with the original function.
- `image/tests/nas-takeover-selftest.sh` (on the NAS): builds three stock
  disks as sparse loop files with the stock commands (RAID1+LVM over two,
  "basic"+ext4 on one) and checks the read-only mount, sysvol, ownership, write
  protection and that the disk images are bit-identical after mount+release.
