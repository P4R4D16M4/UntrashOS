#!/bin/bash
# On the NAS (UntrashOS, root): build synthetic stock NAS542 disks on loop
# files exactly like the stock firmware does (storage_func.py), then check
# that untrash-import-zyxel finds and mounts them and changes no single byte.
#   nas-takeover-selftest.sh [WORKDIR]     (default /state/zt-selftest)
# Uses sparse files (~60 MB really written); cleans up on exit.
set -Eeuo pipefail
W=${1:-/state/zt-selftest}
T=/usr/sbin/untrash-import-zyxel
LOOPS=()
cleanup() {
	set +e
	ZT_IMPORT_DEVGLOB='/dev/loop*p[0-9]' $T release >/dev/null 2>&1
	umount -q /run/zt-st/* 2>/dev/null
	for v in $(vgs --noheadings -o vg_name 2>/dev/null | grep vg_); do vgchange -an "$v" >/dev/null; done
	for m in /dev/md/zt-st-* /dev/md/zyx-*; do [ -e "$m" ] && mdadm --stop "$m" >/dev/null 2>&1; done
	for l in "${LOOPS[@]}"; do losetup -d "$l"; done
	rm -rf "$W" /run/zt-st
}
trap cleanup EXIT
mkdir -p "$W" /run/zt-st
modprobe -a raid1 dm_mod quota_v2 >/dev/null 2>&1 || true

modprobe loop
[ -e /dev/loop-control ] || { echo "no loop devices"; exit 1; }
DISK=
disk() {	# stock PartedInternalDisk(); result in $DISK (no subshell: LOOPS)
	truncate -s 6G "$W/$1.img"
	local l; l=$(losetup -f --show -P "$W/$1.img"); LOOPS+=("$l")
	parted -s "$l" mklabel gpt
	parted -s "$l" mkpart primary 0% 2048MB;   parted -s "$l" toggle 1 raid
	parted -s "$l" mkpart primary 2048MB 4096MB; parted -s "$l" toggle 2 raid
	parted -s "$l" mkpart extended 4096MB 100%; parted -s "$l" toggle 3 raid
	partprobe "$l"; udevadm settle
	[ -b "${l}p3" ] || { echo "no partitions on $l"; exit 1; }
	DISK=$l
}
disk d1; D1=$DISK; disk d2; D2=$DISK; disk d3; D3=$DISK
for d in "$D1" "$D2" "$D3"; do echo "$d p1=$(cat /sys/class/block/$(basename $d)p1/size) p2=$(cat /sys/class/block/$(basename $d)p2/size)"; done

# disk group 1: raid1 over d1+d2, LVM (vg_<md uuid8>, vg_info_area, lv_<rand8>)
mdadm --create /dev/md/zt-st-a --run --metadata=1.2 --level=raid1 --assume-clean --force \
	--raid-devices=2 "${D1}p3" "${D2}p3"
U=$(mdadm --detail /dev/md/zt-st-a | awk '/UUID/ {print $3}' | tr -d : | cut -c1-8)
pvcreate -y -ff /dev/md/zt-st-a >/dev/null; vgcreate "vg_$U" /dev/md/zt-st-a >/dev/null
lvcreate --addtag ext4 -L100M -n vg_info_area "vg_$U" >/dev/null
LV=lv_$(cut -c1-8 /proc/sys/kernel/random/uuid)
lvcreate --addtag ext4 -L300M -n "$LV" "vg_$U" >/dev/null
for lv in vg_info_area "$LV"; do
	mkfs.ext4 -E discard,stride=16,stripe-width=16 -b 4096 -q -j -m 0 -O large_file,extents,uninit_bg "/dev/vg_$U/$lv"
done
mount -t ext4 "/dev/vg_$U/vg_info_area" /run/zt-st; mkdir -p /run/zt-st/.system
echo "Disk Group 1" >/run/zt-st/.system/name_label; umount /run/zt-st
V=/run/zt-st/v1; mkdir -p "$V"
mount -t ext4 -o rw,usrquota,noatime "/dev/vg_$U/$LV" "$V"
mkdir -p "$V/.system" "$V/.media" "$V/admin/download" "$V/music" "$V/photo" "$V/video" "$V/Medien"
echo "Volume1" >"$V/.system/name_label"; : >"$V/.system/sysvol_001122334455"
head -c 5M /dev/urandom >"$V/Medien/file.bin"; chown 504:500 "$V/Medien/file.bin"; chmod -R 777 "$V"
quotacheck -u "$V" 2>/dev/null || true
umount "$V"; vgchange -an "vg_$U" >/dev/null; mdadm --stop /dev/md/zt-st-a >/dev/null

# disk group 2: single-disk "basic" raid1, ext4 directly on md (volType md)
mdadm --create /dev/md/zt-st-b --run --metadata=1.2 --level=raid1 --assume-clean --force \
	--raid-devices=1 "${D3}p3"
mkfs.ext4 -E discard,stride=16,stripe-width=16 -b 4096 -q -j -m 0 -O large_file,extents,uninit_bg /dev/md/zt-st-b
U2=$(mdadm --detail /dev/md/zt-st-b | awk '/UUID/ {print $3}' | tr -d : | cut -c1-8)
V=/run/zt-st/v2; mkdir -p "$V"; mount -t ext4 /dev/md/zt-st-b "$V"
mkdir -p "$V/.system" "$V/Series"; echo "Volume2" >"$V/.system/name_label"; umount "$V"
mdadm --stop /dev/md/zt-st-b >/dev/null

sync
before=$(sha256sum "$W"/d?.img)
echo "--- volumes --mount (read-only)"
ZT_IMPORT_DEVGLOB='/dev/loop*p[0-9]' $T volumes --mount | tee "$W/volumes.json"
fail=0
check() { if eval "$2"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
check "lvm volume mounted ro at /i-data/${LV#lv_}" "findmnt -no OPTIONS /i-data/${LV#lv_} | grep -q '^ro'"
check "md volume mounted ro at /i-data/$U2" "findmnt -no OPTIONS /i-data/$U2 | grep -q '^ro'"
check "sysvol -> lvm volume" "[ \"\$(readlink /i-data/sysvol)\" = /i-data/${LV#lv_} ]"
check "file content and owner kept" "[ \"\$(stat -c %u:%g /i-data/sysvol/Medien/file.bin)\" = 504:500 ]"
check "write refused" "! touch /i-data/sysvol/x 2>/dev/null"
ZT_IMPORT_DEVGLOB='/dev/loop*p[0-9]' $T release
sync
after=$(sha256sum "$W"/d?.img)
check "disk images byte-identical after mount+release" "[ \"\$before\" = \"\$after\" ]"
echo "SELFTEST $([ $fail = 0 ] && echo PASS || echo FAIL)"
exit $fail
