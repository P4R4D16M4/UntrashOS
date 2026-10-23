#!/usr/bin/env bash
# PC test of untrash-storage (RAID/volume management in the stock format), as root:
#   sudo test-storage-host.sh TOOLROOT
# TOOLROOT: extracted Debian mdadm/lvm2/dmsetup debs (os/loader/tests/test-zt-blk-host.sh).
# Four sparse loop disks are the bays.  Checks the stock layout (GPT p1/p2
# sizes, md0/md1 RAID1 over 4 slots, metadata 1.2, chunk 64, ext4 flags and
# stride, /i-data/<uuid8>, name_label, sysvol marker + links, default
# folders), the stock level changes basic -> raid1 -> raid5 -> raid6, spare
# add/remove, failed disk + repair, adding a disk, LVM disk group with
# vg_info_area + lv_<id> (create/extend/delete/rename), delete (shares on the
# volume leave the stock database), refusals (UntrashOS disk, busy disk,
# wrong counts) and that user data survives every step.
set -Eeuo pipefail
[[ -n "${ZT_IN_NS:-}" ]] || exec unshare -m --propagation private env ZT_IN_NS=1 "$0" "$@"
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../.." && pwd)
TR=$(readlink -f "${1:?toolroot}")
W=$(mktemp -d); LOOPS=(); fail=0
export LD_LIBRARY_PATH=$TR/lib/x86_64-linux-gnu:$TR/usr/lib/x86_64-linux-gnu
T="$W/tools"; mkdir -p "$T"
ln -s "$TR/sbin/mdadm" "$T/mdadm"; ln -s "$TR/sbin/dmsetup" "$T/dmsetup"
mkdir -p "$W/lvm"; printf 'devices {\n filter = [ "a|^/dev/md|", "r|.*|" ]\n use_devicesfile = 0\n}\nactivation {\n udev_sync = 1\n udev_rules = 0\n verify_udev_operations = 1\n}\n' >"$W/lvm/lvm.conf"
export LVM_SYSTEM_DIR="$W/lvm"
for c in lvm pvcreate vgcreate lvcreate vgchange vgremove pvremove lvremove lvextend pvresize pvs lvs vgs; do ln -s "$TR/sbin/lvm" "$T/$c"; done
# the PC has no quota tools: record the calls
for c in quotacheck quotaon; do printf '#!/bin/sh\necho "%s $*" >>%s/quota.log\n' "$c" "$W" >"$T/$c"; chmod +x "$T/$c"; done
export PATH="$T:/usr/sbin:/usr/bin:/sbin:/bin"
ST="$ROOT/image/rootfs/usr/sbin/untrash-storage"
cleanup() {
	set +e
	for m in $(findmnt -rn -o TARGET | grep "^$W" | sort -r); do umount -l "$m"; done
	vgchange -an >/dev/null 2>&1
	for d in $(dmsetup ls 2>/dev/null | awk 'index($1, "vg_") == 1 {print $1}'); do dmsetup remove "$d"; done
	for m in /dev/md12[0-3] /dev/md11[01]; do [ -e "$m" ] && mdadm --stop "$m" >/dev/null 2>&1; done
	for l in "${LOOPS[@]}"; do losetup -d "$l" 2>/dev/null; done
	rm -rf "$W"
}
trap cleanup EXIT
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }

for i in 1 2 3 4; do
	truncate -s $((5 + i))G "$W/d$i.img"; L=$(losetup -f --show -P "$W/d$i.img"); LOOPS+=("$L"); eval "D$i=$L"
done

export ZT_STORAGE_DISKS="disk1=$D1,disk2=$D2,disk3=$D3,disk4=$D4"
export ZT_STORAGE_MDNAMES="md120 md121 md122 md123" ZT_STORAGE_MDFW=md110 ZT_STORAGE_MDSWAP=md111
export ZT_STORAGE_IDATA="$W/i-data" ZT_STORAGE_STATE="$W/state/takeover.json" ZT_STORAGE_RUN="$W/run"
export ZT_STORAGE_DB="$W/state/stock-config/ugs_conf.db" ZT_STORAGE_MAC=02:5a:54:11:22:33 ZT_STORAGE_NOSWAPON=1
export ZT_STORAGE_BACKUPDIR="$W/bk" ZT_STORAGE_FAST=1 ZT_IMPORT_TOOL="$ROOT/image/rootfs/usr/sbin/untrash-import-zyxel"
export ZT_IMPORT_DEVGLOB="/dev/loop*p[0-9]"
mkdir -p "$W/i-data" "$W/state/stock-config"
sqlite3 "$ZT_STORAGE_DB" "CREATE TABLE smb_share (s_name TEXT primary key, s_path TEXT); CREATE TABLE share_user_privilege (s_name TEXT, uid INT, uname TEXT, privilege TEXT); CREATE TABLE share_group_privilege (s_name TEXT, gid INT, gname TEXT, privilege TEXT);"

job() {   # job OP JSON [expect-fail]
	local rc=0
	python3 "$ST" run "$1" "$2" >"$W/job.log" 2>&1 || rc=$?
	if [ "${3:-}" = fail ]; then
		check "$1 refused: $(grep -o 'RESULT FAIL.*' "$W/job.log" | cut -c13-90)" "[ $rc != 0 ] && grep -q 'RESULT FAIL' '$W/job.log'"
	else
		check "$1 $2" "[ $rc = 0 ] && grep -q 'RESULT OK' '$W/job.log'"
		[ $rc = 0 ] || { tail -25 "$W/job.log"; exit 1; }
	fi
}
S() { python3 "$ST" status; }
q() { S | python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
md_of() { q "[a['md'] for a in d['arrays']][${1:-0}]"; }
lvl() { q "[a['level'] for a in d['arrays'] if a['md']=='$1'][0]"; }
stat_() { q "[a['state'] for a in d['arrays'] if a['md']=='$1'][0]"; }
vol() { q "[a['volumes'][${2:-0}]['mnt'] for a in d['arrays'] if a['md']=='$1'][0]"; }

echo "--- status, refusals"
check "4 free bays" "[ \"\$(q 'len(d[\"free\"])')\" = 4 ]"
job create '{"level":"raid5","disks":["disk1","disk2"],"name":"V"}' fail
job create '{"level":"raid10","disks":["disk1","disk2","disk3"],"name":"V"}' fail
job create '{"level":"basic","disks":["disk1"],"name":"bad/name"}' fail

echo "--- basic volume on disk1 (stock layout)"
job create '{"level":"basic","disks":["disk1"],"name":"Volume1"}'
M=$(md_of); MNT=$(vol "$M"); U8=$(basename "$MNT")
check "p1/p2 stock sizes" "[ \$(cat /sys/class/block/$(basename $D1)p1/size) = 3997696 ] && [ \$(cat /sys/class/block/$(basename $D1)p2/size) = 3999744 ]"
check "GPT raid flags" "parted -s $D1 print | grep -c raid | grep -qx 3"
check "md0/md1 raid1 over 4 slots" "[ \$(cat /sys/block/md110/md/raid_disks) = 4 ] && [ \$(cat /sys/block/md111/md/raid_disks) = 4 ] && [ \$(cat /sys/block/md110/md/level) = raid1 ]"
check "md1 swap, md0 ext4" "blkid -o value -s TYPE /dev/md111 | grep -qx swap && blkid -o value -s TYPE /dev/md110 | grep -qx ext4"
check "data array basic, metadata 1.2" "[ \$(lvl $M) = basic ] && mdadm --detail /dev/$M | grep -q 'Version : 1.2'"
check "mount /i-data/<uuid8>" "[ \"$U8\" = \"\$(mdadm --detail --export /dev/$M | sed -n 's/^MD_UUID=//p' | tr -d : | cut -c1-8)\" ] && mountpoint -q '$MNT'"
check "mount options" "findmnt -n -o OPTIONS '$MNT' | grep -q usrquota && findmnt -n -o OPTIONS '$MNT' | grep -q noatime"
check "ext4 stock flags, stride 16" "dumpe2fs -h /dev/$M 2>/dev/null | grep -q 'RAID stride: *16' && dumpe2fs -h /dev/$M 2>/dev/null | grep -q 'Reserved block count: *0$'"
check "name label" "[ \"\$(cat '$MNT/.system/name_label')\" = Volume1 ]"
check "sysvol marker + links" "[ -f '$MNT/.system/sysvol_025a54112233' ] && [ \"\$(readlink $W/i-data/sysvol)\" = '$MNT' ] && [ -L $W/i-data/.media ]"
check "default folders" "[ -d '$MNT/admin/download/torrent' ] && [ -d '$MNT/music' ] && [ -d '$MNT/photo' ] && [ -d '$MNT/video' ]"
check "takeover state rw" "grep -q '\"rw\": true' '$ZT_STORAGE_STATE'"
check "quota switched on" "grep -q 'quotaon -uv $MNT' $W/quota.log"
head -c 30M /dev/urandom >"$MNT/data.bin"; SUM=$(sha256sum <"$MNT/data.bin"); sync
data_ok() { check "data intact ($1)" "[ \"\$(sha256sum <'$MNT/data.bin')\" = \"$SUM\" ]"; }
sqlite3 "$ZT_STORAGE_DB" "INSERT INTO smb_share VALUES ('music','$MNT/music'); INSERT INTO smb_share VALUES ('other','/i-data/xyz/other'); INSERT INTO share_user_privilege VALUES ('music',1000,'u','rw');"
python3 "$ZT_IMPORT_TOOL" volumes >"$W/imp.json" 2>&1 || true
check "importer sees a stock data array" "grep -q '\"role\": \"stock-data\"' $W/imp.json" || true
grep -q '"role": "stock-data"' "$W/imp.json" || head -30 "$W/imp.json"

echo "--- basic -> raid1 -> raid5 -> spare"
job change-level "{\"md\":\"$M\",\"level\":\"raid1\",\"disks\":[\"disk2\"]}"
check "raid1, 2 disks, Normal" "[ \$(lvl $M) = raid1 ] && [ \$(cat /sys/block/$M/md/raid_disks) = 2 ] && [ \$(stat_ $M) = Normal ]"
check "md0 now 2 members" "mdadm --detail /dev/md110 | grep -q 'Working Devices : 2'"
data_ok raid1
S1=$(df -B1 --output=size "$MNT" | tail -1)
job change-level "{\"md\":\"$M\",\"level\":\"raid5\",\"disks\":[\"disk3\"]}"
check "raid5, 3 disks" "[ \$(lvl $M) = raid5 ] && [ \$(cat /sys/block/$M/md/raid_disks) = 3 ]"
check "filesystem grown" "[ \$(df -B1 --output=size '$MNT' | tail -1) -gt \$((S1 * 3 / 2)) ]"
check "stride-width 32" "dumpe2fs -h /dev/$M 2>/dev/null | grep -q 'RAID stripe width: *32'"
data_ok raid5
job add-spare "{\"md\":\"$M\",\"disks\":[\"disk4\"]}"
check "disk4 is spare" "q \"[m['state'] for a in d['arrays'] for m in a['members'] if m['bay']=='disk4'][0]\" | grep -qx spare"
job remove-spare "{\"md\":\"$M\",\"disks\":[\"disk4\"]}"
check "disk4 free again" "q \"'disk4' in d['free']\" | grep -qx True"

echo "--- disk2 fails, repair"
mdadm --manage /dev/$M --fail "${D2}p3" >/dev/null 2>&1
for i in 1 2 3 4; do for c in green red; do mkdir -p "$W/leds/hdd$i-$c"; : >"$W/leds/hdd$i-$c/brightness"; done; done
ZT_STORAGE_LEDS="$W/leds" python3 "$ST" leds
check "bay LEDs: red at the faulty disk (disk2), green at the others" "[ \$(cat $W/leds/hdd2-red/brightness) = 1 ] && [ \$(cat $W/leds/hdd1-red/brightness) = 0 ] && [ \$(cat $W/leds/hdd1-green/brightness) = 1 ]"
mdadm --manage /dev/$M --remove "${D2}p3" >/dev/null 2>&1
check "Degraded, repair offered" "[ \$(stat_ $M) = Degraded ] && q \"[a['actions'] for a in d['arrays']][0]\" | grep -q repair"
job add-disks "{\"md\":\"$M\",\"disks\":[\"disk4\"]}" fail
job repair "{\"md\":\"$M\",\"disks\":[\"disk2\"]}"
check "Normal after repair" "[ \$(stat_ $M) = Normal ] && [ \$(lvl $M) = raid5 ]"
data_ok repair

echo "--- add disk4 (raid5 over 4), then raid6 refused (no free bay)"
job add-disks "{\"md\":\"$M\",\"disks\":[\"disk4\"]}"
check "raid5, 4 disks" "[ \$(cat /sys/block/$M/md/raid_disks) = 4 ] && [ \$(stat_ $M) = Normal ]"
data_ok raid5x4
job change-level "{\"md\":\"$M\",\"level\":\"raid6\",\"disks\":[]}" fail
job delete '{"md":"md110"}' fail

echo "--- delete"
job delete "{\"md\":\"$M\"}"
check "unmounted, array gone" "! mountpoint -q '$MNT' && [ ! -e /sys/block/$M/md/level ]"
check "superblocks zeroed" "! mdadm --examine ${D1}p3 >/dev/null 2>&1"
check "share on the volume dropped, other kept" "[ \"\$(sqlite3 $ZT_STORAGE_DB 'SELECT group_concat(s_name) FROM smb_share')\" = other ] && [ \$(sqlite3 $ZT_STORAGE_DB 'SELECT count(*) FROM share_user_privilege') = 0 ]"
check "sysvol links removed" "[ ! -e $W/i-data/sysvol ]"
check "all 4 bays free" "[ \"\$(q 'len(d[\"free\"])')\" = 4 ]"

echo "--- LVM disk group (raid0), volumes"
job create '{"level":"raid0","disks":["disk1","disk2"],"name":"Gruppe1","type":"lvm","volume":"Daten","size":"1G"}'
M=$(md_of); VG=$(q "d['arrays'][0]['vg']"); U8=$(mdadm --detail --export /dev/$M | sed -n 's/^MD_UUID=//p' | tr -d : | cut -c1-8)
check "vg_<uuid8>, vg_info_area 100M" "[ $VG = vg_$U8 ] && lvs --noheadings -o lv_size --units m $VG/vg_info_area | grep -q '100.00m'"
check "group name in vg_info_area" "[ \"\$(cat $W/run/vg_info_area/$VG/.system/name_label)\" = Gruppe1 ]"
LV1=$(lvs --noheadings -o lv_name $VG | grep lv_ | tr -d ' ')
check "lv_<id> 1G at /i-data/<id>, ext4 tag" "[ -n '$LV1' ] && mountpoint -q $W/i-data/\${LV1#lv_} && lvs --noheadings -o lv_tags $VG/$LV1 | grep -q ext4"
check "first volume is sysvol" "[ \"\$(readlink $W/i-data/sysvol)\" = $W/i-data/\${LV1#lv_} ]"
job lv-extend "{\"md\":\"$M\",\"lv\":\"$LV1\",\"size\":\"2G\"}"
check "extended to 2G (fs too)" "[ \$(df -B1G --output=size $W/i-data/\${LV1#lv_} | tail -1 | tr -d ' ') -ge 2 ]"
job lv-create "{\"md\":\"$M\",\"volume\":\"Rest\",\"size\":\"max\"}"
check "2 volumes, VG full" "[ \$(q 'len(d[\"arrays\"][0][\"volumes\"])') = 2 ] && [ \$(q 'd[\"arrays\"][0][\"vg_free\"]') -lt 104857600 ]"
LV2=$(lvs --noheadings -o lv_name $VG | grep lv_ | grep -v $LV1 | tr -d ' ')
job rename "{\"md\":\"$M\",\"lv\":\"$LV2\",\"name\":\"Archiv\"}"
check "renamed" "[ \"\$(cat $W/i-data/\${LV2#lv_}/.system/name_label)\" = Archiv ]"
job lv-delete "{\"md\":\"$M\",\"lv\":\"$LV2\"}"
check "volume deleted" "! lvs $VG/$LV2 >/dev/null 2>&1 && ! mountpoint -q $W/i-data/\${LV2#lv_}"

echo "--- refusals: UntrashOS disk, busy disk"
release() {   # take a disk out of md0/md1 and wipe it (test setup only)
	local d=$1
	mdadm --manage /dev/md110 --fail "${d}p1" --remove "${d}p1" >/dev/null 2>&1 || true
	mdadm --manage /dev/md111 --fail "${d}p2" --remove "${d}p2" >/dev/null 2>&1 || true
	mdadm --zero-superblock "${d}p1" "${d}p2" "${d}p3" >/dev/null 2>&1 || true
	wipefs -aq "$d"; partprobe "$d"; sleep 1
}
release "$D3"; release "$D4"
parted -s "$D3" mklabel gpt mkpart ut-data 1MiB 100MiB; partprobe "$D3"; sleep 1
check "disk3 = system" "q \"[x['role'] for x in d['disks'] if x['bay']=='disk3'][0]\" | grep -qx system"
job create '{"level":"basic","disks":["disk3"],"name":"X"}' fail
job create '{"level":"basic","disks":["disk1"],"name":"X"}' fail
parted -s "$D4" mklabel gpt mkpart p 1MiB 100MiB; partprobe "$D4"; sleep 1; mkfs.ext4 -q "${D4}p1"; mkdir -p "$W/busy"; mount "${D4}p1" "$W/busy"
check "disk4 = busy" "q \"[x['role'] for x in d['disks'] if x['bay']=='disk4'][0]\" | grep -qx busy"
job create '{"level":"basic","disks":["disk4"],"name":"X"}' fail
umount "$W/busy"
job delete "{\"md\":\"$M\"}"
check "VG gone" "! vgs $VG >/dev/null 2>&1"

echo "--- raid5 on 3 disks, then raid6 with disk4"
release "$D3"; release "$D4"
job create '{"level":"raid5","disks":["disk1","disk2","disk3"],"name":"R5"}'
M=$(md_of); MNT=$(vol "$M"); head -c 20M /dev/urandom >"$MNT/data.bin"; SUM=$(sha256sum <"$MNT/data.bin"); sync
job change-level "{\"md\":\"$M\",\"level\":\"raid6\",\"disks\":[\"disk4\"]}"
check "raid6, 4 disks, Normal" "[ \$(lvl $M) = raid6 ] && [ \$(cat /sys/block/$M/md/raid_disks) = 4 ] && [ \$(stat_ $M) = Normal ]"
data_ok raid6
job delete "{\"md\":\"$M\"}"

[ $fail = 0 ] && echo "ALL OK" || { echo "FAILURES"; exit 1; }
