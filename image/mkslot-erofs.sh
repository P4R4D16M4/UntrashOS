#!/usr/bin/env bash
# Build an UntrashOS system slot, format untrash-slot-2 (raw partition image):
#
#   offset 0            erofs root (lz4hc), padded to 4 KiB      = verity data
#   offset N*4096       dm-verity hash tree (no superblock)
#   offset K            kernel zImage (padded to 4 KiB)
#   offset D            DTB (padded to 4 KiB)
#   offset I            slot initrd (mk-slot-initrd.sh, padded to 4 KiB)
#   size-8192           manifest (text, NUL padded)  ┐ trailer, read by the
#   size-4096           Ed25519 signatures (64 bytes ┘ loader with dd
#                       each, up to 8, NUL padded)
#
# The manifest pins kernel, DTB, initrd and the verity root hash.  `cmdline`
# (partition boot, no initrd: loaders before 1.0.3) contains @SLOT@, which the
# loader replaces with the GPT name it booted from.  `cmdline_part` (partition
# boot through the initrd, so modules such as PCIe and the ASM1061 AHCI of the
# NAS542's bays 2/4 are loaded before the root is looked up) has
# untrash.part=@SLOT@ instead.  `cmdline_file` (slot as a file on a stick or a
# stock volume) is used with the initrd; the loader appends untrash.src=,
# untrash.file= and untrash.slot= (the slot initrd of the board).
# A slot FILE (*.utslot, mk-slotfile.sh) is the head (0 .. END) plus the
# trailer; the loader finds the trailer at file size - 8192.
#
#   ZT_BOARD=BOARD_DIR mkslot-erofs.sh ROOTFS_DIR KBUILD_DIR VERSION OUT.img [SLOT_SIZE]
# ROOTFS_DIR = the mkosi tree of image/mkosi.conf, KBUILD_DIR = the board's
# kernel build.  BOARD_DIR (docs/board-interface.md): board.conf, rootfs/
# (copied over image/rootfs), slot-hook.sh (check + root stages) and the slot
# initrd builder.  ZT_TOP = the firmware repo root with build/ and inputs/
# (default: the parent of this repo, which is a submodule there).
# ZT_PROFILE=dev (default) | release:
#   dev      the pinned dev SSH host key (runtime/nas-hostkey), the operator
#            key from mkosi ExtraTrees, recovery address 169.254.100.64/1
#   release  no host key (untrash-ssh-hostkeys makes them on the NAS), no
#            authorized_keys, no snakeoil TLS key, no recovery address
# ZT_SMP=1 (default) starts both Cortex-A9 cores (maxcpus=1 with ZT_SMP=0).
set -Eeuo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); OS=$(cd "$HERE/.." && pwd)
TOP=$(cd "${ZT_TOP:-$OS/..}" && pwd)
BOARD=$(cd "${ZT_BOARD:?ZT_BOARD=board directory}" && pwd)
RFS=${1:?rootfs}; KB=${2:?kbuild}; VER=${3:?version}; OUT=${4:?out}; SIZE=${5:-1073741824}
BOARD_DTB=; BOARD_CMDLINE=; BOARD_MANUAL=; BOARD_INITRD=
. "$BOARD/board.conf"
for v in BOARD_DTB BOARD_CMDLINE BOARD_MANUAL BOARD_INITRD; do [ -n "${!v}" ] || { echo "$BOARD/board.conf: $v missing" >&2; exit 1; }; done
# programs without x bit only fail on the NAS (203/EXEC)
for d in "$HERE/rootfs" "$BOARD/rootfs"; do
	python3 "$HERE/tests/test_exec_bits.py" "$d" >&2 || { echo "exec bits FAILED ($d)" >&2; exit 1; }
done
# signing keys, in order: the first signature is the one every deployed loader
# checks (it reads only the first 64 bytes), so it must be a key those loaders
# know; later ones are read by newer verifiers (Desk update, newer loaders)
if [[ -n ${ZT_SLOT_KEYS:-} ]]; then read -ra SECS <<<"$ZT_SLOT_KEYS"
else SECS=("${ZT_SLOT_KEY:-$TOP/inputs/keys/untrash-dev.sec}")
	[[ -f $TOP/inputs/keys/untrash-release.sec ]] && SECS+=("$TOP/inputs/keys/untrash-release.sec")
fi
(( ${#SECS[@]} <= 8 )) || { echo "at most 8 signing keys" >&2; exit 1; }
PROFILE=${ZT_PROFILE:-dev}; [[ $PROFILE == dev || $PROFILE == release ]] || { echo "ZT_PROFILE dev|release" >&2; exit 1; }
MAXCPUS=; [[ ${ZT_SMP:-1} == 1 ]] || MAXCPUS=" maxcpus=1"
# board checks of the kernel build
"$BOARD/slot-hook.sh" check "$KB"
ZI="$KB/arch/arm/boot/zImage"; DTB="$KB/$BOARD_DTB"
MODS=$(ls -d "$KB"/modules-staging/lib/modules/*); REL=$(basename "$MODS")
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
pad4k() { local s; s=$(stat -c %s "$1"); truncate -s $(( (s + 4095) / 4096 * 4096 )) "$1"; }

# 1. root tree: Debian + our kernel modules
cp -a "$RFS" "$W/root"
mkdir -p "$W/root/usr/lib/modules" "$W/root/usr/lib/firmware"
cp -a "$MODS" "$W/root/usr/lib/modules/"
/usr/sbin/depmod -b "$W/root/usr" "$REL" 2>/dev/null || /sbin/depmod -b "$W/root/usr" "$REL"
rm -f "$W/root/etc/machine-id"; : >"$W/root/etc/machine-id"	# systemd fills it at boot (volatile)
echo "$VER" >"$W/root/etc/untrash-version"
# UntrashOS integration: boot-state confirmation and the USB blackbox
cp -a "$HERE/rootfs/." "$W/root/"
cp -a "$BOARD/rootfs/." "$W/root/"
for d in usr/lib/untrash usr/sbin usr/share/untrash; do find "$W/root/$d" -name __pycache__ -prune -exec rm -rf {} +; done   # PC test leftovers
# design system (design): installer page now, Untrash Desk / Cockpit branding later
DSN="$OS/design"; DD="$W/root/usr/share/untrash/design"
[ -f "$DSN/assets/logo-mark-96.png" ] || python3 "$DSN/mk-assets.py"
mkdir -p "$DD/assets/icons"
cp "$DSN/untrash.css" "$DSN/theme.js" "$DD/"
# UI translations (design/i18n, built by tools/i18n/build.py)
mkdir -p "$DD/i18n" && cp "$DSN"/i18n/{i18n.js,de.json,fr.json} "$DD/i18n/"
cp "$DSN"/assets/{favicon.ico,logo-mark-48.png,logo-mark-96.png,logo-mark-192.png,wordmark-300.png,wallpaper.jpg,wallpaper-blur.jpg,wallpaper-light.jpg,wallpaper-light-blur.jpg} "$DD/assets/"
cp "$DSN"/assets/icons/*-64.png "$DSN"/assets/icons/*-128.png "$DSN"/assets/icons/*.svg "$DD/assets/icons/"
# user manual (docs/user-guide, built by tools/manual/build.py): Desk app and
# installer serve it at /manual/
UG="$TOP/$BOARD_MANUAL"; UM="$W/root/usr/share/untrash/manual"
for f in manual.html UntrashOS-User-Guide.pdf; do [ -f "$UG/$f" ] || { echo "missing $UG/$f (make manual)" >&2; exit 1; }; done
mkdir -p "$UM/img"
cp "$UG/manual.html" "$UM/index.html"
cp "$UG/UntrashOS-User-Guide.pdf" "$UM/"
cp "$UG"/img/*.webp "$UM/img/"
rm -f "$W"/root/etc/ssh/ssh_host_*
echo "$PROFILE" >"$W/root/etc/untrash-profile"
if [[ $PROFILE == dev ]]; then
	# persistent dev SSH host key (gitignored, pinned in runtime/nas-hostkey/known_hosts)
	HKD="$TOP/inputs/dev-hostkey"
	install -m 600 "$HKD/openssh_ed25519_host_key" "$W/root/etc/ssh/ssh_host_ed25519_key"
	install -m 644 "$HKD/openssh_ed25519_host_key.pub" "$W/root/etc/ssh/ssh_host_ed25519_key.pub"
	printf 'HostKey /etc/ssh/ssh_host_ed25519_key\n' >"$W/root/etc/ssh/sshd_config.d/05-untrash-hostkey.conf"
	: >"$W/root/usr/lib/untrash/dev-profile"	# untrash-config: recovery address on eth0
else
	# release: nothing of this PC or operator in the image
	rm -rf "$W/root/root/.ssh" "$W/root/etc/systemd/network/10-recovery.network"
	rm -f "$W"/root/etc/ssl/private/ssl-cert-snakeoil.key "$W"/root/etc/ssl/certs/ssl-cert-snakeoil.pem
	if grep -rqs "BEGIN OPENSSH PRIVATE KEY\|BEGIN RSA PRIVATE KEY\|BEGIN PRIVATE KEY" "$W/root/etc" "$W/root/root"; then
		echo "release image would contain a private key:" >&2
		grep -rls "BEGIN OPENSSH PRIVATE KEY\|BEGIN RSA PRIVATE KEY\|BEGIN PRIVATE KEY" "$W/root/etc" "$W/root/root" >&2; exit 1
	fi
fi
# update check in Untrash Desk: slot signature (slot/zt-sig.c) + keys
arm-linux-gnueabihf-gcc -static -O2 -I"$OS/third_party/tweetnacl" -o "$W/root/usr/lib/untrash/zt-sig" \
	"$OS/slot/zt-sig.c" "$OS/third_party/tweetnacl/tweetnacl.c"
arm-linux-gnueabihf-strip "$W/root/usr/lib/untrash/zt-sig"
# watchdog keeper (image/tools/untrash-wdt.c), source next to it for the record
arm-linux-gnueabihf-gcc -static -O2 -Wall -Werror -o "$W/root/usr/lib/untrash/untrash-wdt" "$OS/image/tools/untrash-wdt.c"
arm-linux-gnueabihf-strip "$W/root/usr/lib/untrash/untrash-wdt"
install -D -m 644 "$OS/image/tools/untrash-wdt.c" "$W/root/usr/share/doc/untrash/untrash-wdt.c"
mkdir -p "$W/root/usr/lib/untrash/keys"; cp "$OS"/slot/keys/*.pub "$W/root/usr/lib/untrash/keys/"
mkdir -p "$W/root/etc/systemd/system/timers.target.wants" "$W/root/etc/systemd/system/sysinit.target.wants"
ln -sf /usr/lib/systemd/system/untrash-mark-good.timer "$W/root/etc/systemd/system/timers.target.wants/"
ln -sf /usr/lib/systemd/system/untrash-recycle-expire.timer "$W/root/etc/systemd/system/timers.target.wants/"
ln -sf /usr/lib/systemd/system/untrash-backup.timer "$W/root/etc/systemd/system/timers.target.wants/"
ln -sf /usr/lib/systemd/system/untrash-leds.timer "$W/root/etc/systemd/system/timers.target.wants/"
ln -sf /usr/lib/systemd/system/untrash-adblock-update.timer "$W/root/etc/systemd/system/timers.target.wants/"
ln -sf /usr/lib/systemd/system/untrash-update.timer "$W/root/etc/systemd/system/timers.target.wants/"
ln -sf /usr/lib/systemd/system/untrash-settings.service "$W/root/etc/systemd/system/sysinit.target.wants/"
ln -sf /usr/lib/systemd/system/untrash-wdt.service "$W/root/etc/systemd/system/sysinit.target.wants/"
# inadyn: native unit in rootfs; the SysV script made every daemon-reload
# run the sysv generator
rm -f "$W/root/etc/init.d/inadyn" "$W"/root/etc/rc?.d/[SK]??inadyn
# Way B: stock takeover on the first start from /.untrash
mkdir -p "$W/root/etc/systemd/system/multi-user.target.wants"
ln -sf /usr/lib/systemd/system/untrash-takeover-firstboot.service "$W/root/etc/systemd/system/multi-user.target.wants/"
# Untrash Desk (port 80, not on the installer stick), way A data partition, SSH host keys,
# service SSH key from the stick
for u in untrash-desk untrash-data untrash-ssh-hostkeys untrash-copybtn untrash-servicekey untrash-adblock untrash-netname untrash-mesh; do
	ln -sf /usr/lib/systemd/system/$u.service "$W/root/etc/systemd/system/multi-user.target.wants/"
done
# services of the stock features run only when untrash-config switches them on (settings),
# not because Debian enables them on installation
for u in inadyn.service apcupsd.service cups.service cups.socket cups.path smartmontools.service smartd.service; do
	find "$W/root/etc/systemd/system" -name "$u" -type l -delete
done
# installer stick (loader appends untrash.installer=1): web installer + name
ln -sf /usr/lib/systemd/system/untrash-installer.service "$W/root/etc/systemd/system/multi-user.target.wants/"
ln -sf /usr/lib/systemd/system/untrash-installer-hostname.service "$W/root/etc/systemd/system/sysinit.target.wants/"

# Mount point of the writable state (image/rootfs/usr/lib/untrash/untrash-init)
mkdir -p "$W/root/state"
# chrony-wait needs PrivateUsers (no CONFIG_USER_NS) and an NTP
# server (none on the recovery link) -> always failed, system "degraded"
ln -sf /dev/null "$W/root/etc/systemd/system/chrony-wait.service"
rm -f "$W/root/etc/systemd/system/multi-user.target.wants/chrony-wait.service"
# chrony.service and chronyd-restricted.service were both enabled (they
# conflict): keep chrony.service
rm -f "$W/root/etc/systemd/system/multi-user.target.wants/chronyd-restricted.service"
# eth0 also asks DHCP; wait-online would wait 2 min and fail without a
# DHCP server (system "degraded").  Nothing here needs network-online.target.
ln -sf /dev/null "$W/root/etc/systemd/system/systemd-networkd-wait-online.service"
rm -f "$W/root/etc/systemd/system/network-online.target.wants/systemd-networkd-wait-online.service"
# Stopping agetty on ttyS0 while the console is busy wedges the CPU
# (watchdog reset instead of power-off).  The assembled NAS has no UART
# access anyway.
ln -sf /dev/null "$W/root/etc/systemd/system/serial-getty@ttyS0.service"
# board: its tools and services (BOARD/slot-hook.sh)
ZT_TOP="$TOP" "$BOARD/slot-hook.sh" root "$W/root" "$KB"
# P4 takeover (docs/architecture/stock-takeover.md): stock mount roots; foreign
# md arrays and LVM VGs are never assembled/activated automatically (only
# untrash-import-zyxel does that, read-only until the operator ran apply);
# Samba starts only after a takeover (untrash-zyxel.service).
mkdir -p "$W/root/i-data" "$W/root/e-data"
printf 'AUTO -all\n' >>"$W/root/etc/mdadm/mdadm.conf"
printf '\nactivation {\n\tauto_activation_volume_list = []\n}\n' >>"$W/root/etc/lvm/lvmlocal.conf"
rm -f "$W"/root/etc/systemd/system/multi-user.target.wants/{smbd,nmbd,samba-ad-dc}.service
# stock services start only as the settings say (untrash-config enables them;
# the installer stick runs none of them)
rm -f "$W"/root/etc/systemd/system/multi-user.target.wants/{vsftpd,minidlna,nfs-server,hd-idle,quotarpc,rpcbind,nbd-server,drbd}.service
rm -f "$W"/root/etc/systemd/system/multi-user.target.wants/nfs-client.target "$W"/root/etc/systemd/system/remote-fs.target.wants/nfs-client.target
rm -f "$W"/root/etc/systemd/system/sockets.target.wants/rpcbind.socket
[[ $PROFILE == dev ]] || rm -f "$W"/root/etc/systemd/system/multi-user.target.wants/ssh.service "$W"/root/etc/systemd/system/sockets.target.wants/ssh.socket

# 2. erofs + verity, with real owners: everything root, then the dpkg
# statoverrides of the image and image/ownership.list (names resolved
# against the image's passwd/group), all inside one fakeroot session.
cat >"$W/own.sh" <<'OWN'
set -e
R=$1; LIST=$2; OUT=$3
id_of() { awk -F: -v n="$1" '$1 == n { print $3 }' "$R/etc/$2"; }
chown -R -h 0:0 "$R"
{ sed 's/^\([^ ]*\) \([^ ]*\) \([^ ]*\) \(.*\)$/\4 \1 \2 \3/' "$R/var/lib/dpkg/statoverride"
  grep -v '^[[:space:]]*\(#\|$\)' "$LIST"; } |
while read -r path owner group mode; do
	[ -e "$R$path" ] || { echo "ownership: $path missing" >&2; continue; }
	u=$(id_of "$owner" passwd); g=$(id_of "$group" group)
	[ -n "$u" ] && [ -n "$g" ] || { echo "ownership: unknown $owner:$group for $path" >&2; exit 1; }
	chown -h "$u:$g" "$R$path"; chmod "$mode" "$R$path"
done
mkfs.erofs -zlz4hc -T 1767225600 -U "$UUID" "$OUT" "$R" >/dev/null
OWN
# reproducible: filesystem UUID and verity salt derive from the version, so
# the same sources and version give the same verity root hash
VH=$(printf 'untrash-slot:%s' "$VER" | sha256sum | cut -c1-64)
UUID="${VH:0:8}-${VH:8:4}-${VH:12:4}-${VH:16:4}-${VH:20:12}"
UUID=$UUID fakeroot -- sh "$W/own.sh" "$W/root" "$HERE/ownership.list" "$W/root.erofs"
pad4k "$W/root.erofs"
N=$(( $(stat -c %s "$W/root.erofs") / 4096 ))
VOUT=$(/usr/sbin/veritysetup format --no-superblock --data-block-size=4096 --hash-block-size=4096 \
	--salt="$VH" --data-blocks="$N" "$W/root.erofs" "$W/root.hash")
RH=$(sed -n 's/^Root hash:[[:space:]]*//p' <<<"$VOUT"); SALT=$(sed -n 's/^Salt:[[:space:]]*//p' <<<"$VOUT")
pad4k "$W/root.hash"
cp "$ZI" "$W/k"; pad4k "$W/k"
cp "$DTB" "$W/d"
fdtput -t s "$W/d" /chosen untrash,stage system
pad4k "$W/d"
ZT_TOP="$TOP" "$BOARD/$BOARD_INITRD" "$MODS" "$W/i" >/dev/null
pad4k "$W/i"

H=$(( N * 4096 )); K=$(( H + $(stat -c %s "$W/root.hash") )); D=$(( K + $(stat -c %s "$W/k") ))
I=$(( D + $(stat -c %s "$W/d") ))
END=$(( I + $(stat -c %s "$W/i") ))
(( END <= SIZE - 8192 )) || { echo "slot too small ($END > $SIZE)" >&2; exit 1; }
SECTORS=$(( N * 8 ))
cat >"$W/manifest" <<M
format=untrash-slot-2
version=$VER
kernel_release=$REL
kernel_off=$K
kernel_len=$(stat -c %s "$W/k")
kernel_sha256=$(sha256sum "$W/k" | cut -d' ' -f1)
dtb_off=$D
dtb_len=$(stat -c %s "$W/d")
dtb_sha256=$(sha256sum "$W/d" | cut -d' ' -f1)
initrd_off=$I
initrd_len=$(stat -c %s "$W/i")
initrd_sha256=$(sha256sum "$W/i" | cut -d' ' -f1)
verity_data_blocks=$N
verity_hash_start=$N
verity_root=$RH
verity_salt=$SALT
cmdline=$BOARD_CMDLINE$MAXCPUS loglevel=6 panic=10 printk.devkmsg=on systemd.journald.forward_to_kmsg=1 root=/dev/dm-0 rootfstype=erofs ro rootwait init=/usr/lib/untrash/untrash-init dm-mod.waitfor=PARTLABEL=@SLOT@ dm-mod.create="untrash-root,,,ro,0 $SECTORS verity 1 PARTLABEL=@SLOT@ PARTLABEL=@SLOT@ 4096 4096 $N $N sha256 $RH $SALT"
cmdline_file=$BOARD_CMDLINE$MAXCPUS loglevel=6 panic=10 printk.devkmsg=on systemd.journald.forward_to_kmsg=1 init=/usr/lib/untrash/untrash-init untrash.verity=$N,$RH,$SALT
cmdline_part=$BOARD_CMDLINE$MAXCPUS loglevel=6 panic=10 printk.devkmsg=on systemd.journald.forward_to_kmsg=1 init=/usr/lib/untrash/untrash-init untrash.verity=$N,$RH,$SALT untrash.part=@SLOT@
M
gcc -O2 -I"$OS/third_party/tweetnacl" -o "$W/zt-sig" "$OS/slot/zt-sig.c" "$OS/third_party/tweetnacl/tweetnacl.c"
: >"$W/manifest.sig"
for k in "${SECS[@]}"; do
	"$W/zt-sig" sign "$k" "$W/manifest" "$W/one.sig"
	# every signature must verify against a public key the image ships
	ok=; for p in "$OS"/slot/keys/*.pub; do "$W/zt-sig" verify "$p" "$W/manifest" "$W/one.sig" >/dev/null && ok=1; done
	[[ -n $ok ]] || { echo "signature of $k matches no key in slot/keys" >&2; exit 1; }
	cat "$W/one.sig" >>"$W/manifest.sig"
done
head -c 64 "$W/manifest.sig" >"$W/first.sig"
"$W/zt-sig" verify "$OS/slot/keys/untrash-dev.pub" "$W/manifest" "$W/first.sig" >/dev/null ||
	{ echo "first signature is not the dev key the deployed loaders know" >&2; exit 1; }

# 3. assemble (sparse, full slot size)
rm -f "$OUT"; truncate -s "$SIZE" "$OUT"
dd if="$W/root.erofs" of="$OUT" conv=notrunc status=none
dd if="$W/root.hash" of="$OUT" bs=4096 seek=$(( H / 4096 )) conv=notrunc status=none
dd if="$W/k" of="$OUT" bs=4096 seek=$(( K / 4096 )) conv=notrunc status=none
dd if="$W/d" of="$OUT" bs=4096 seek=$(( D / 4096 )) conv=notrunc status=none
dd if="$W/i" of="$OUT" bs=4096 seek=$(( I / 4096 )) conv=notrunc status=none
dd if="$W/manifest" of="$OUT" bs=4096 seek=$(( SIZE / 4096 - 2 )) conv=notrunc status=none
dd if="$W/manifest.sig" of="$OUT" bs=4096 seek=$(( SIZE / 4096 - 1 )) conv=notrunc status=none

# 4. self-check: verity over the assembled image
/usr/sbin/veritysetup verify --no-superblock --data-block-size=4096 --hash-block-size=4096 \
	--data-blocks="$N" --hash-offset="$H" "$OUT" "$OUT" "$RH" --salt="$SALT" && echo "verity self-check OK"
echo "SLOT=$OUT  used=$(( END / 1048576 )) MiB of $(( SIZE / 1048576 )) MiB"
cat "$W/manifest"
