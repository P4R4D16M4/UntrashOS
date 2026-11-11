# Board interface

UntrashOS is device-independent.  A **firmware repository** (for example
ZyxelUntrash for the Zyxel NAS540/NAS542) adds one device: kernel, loader,
installer and the board files below.  It has this repository as a git
submodule (`untrashos/`) pinned to an UntrashOS tag, so every device builds
on the same OS sources.

```
<firmware repo>/
  untrashos/            this repository (submodule)
  board/<name>/
    board.conf          build settings (below)
    rootfs/             files copied over image/rootfs into the slot
    slot-hook.sh        board steps of the slot build
    <initrd builder>    slot initrd (BOARD_INITRD)
    tests/              tests of the board files
  build/  inputs/       build output and external inputs (ZT_TOP)
```

## Build interface

`image/mkslot-erofs.sh` builds a signed slot from the mkosi tree
(`image/mkosi.conf`), the board's kernel build and the board directory:

```
ZT_BOARD=board/<name> ZT_TOP=<firmware repo> \
  untrashos/image/mkslot-erofs.sh ROOTFS KBUILD VERSION OUT.img [SIZE]
```

`board.conf` (shell, sourced):

| Variable | Meaning |
|---|---|
| `BOARD_NAME` | short board name |
| `BOARD_DTB` | device tree, relative to the kernel build |
| `BOARD_CMDLINE` | start of the kernel command line (console, clock options) |
| `BOARD_MANUAL` | user guide directory, relative to `ZT_TOP` (`manual.html`, PDF, `img/`) |
| `BOARD_INITRD` | slot initrd builder: `BUILDER MODDIR OUT.cpio.gz` |

`slot-hook.sh`:

| Call | When | Does |
|---|---|---|
| `slot-hook.sh check KBUILD` | before anything is built | refuse a kernel build the board cannot use (exit ≠ 0) |
| `slot-hook.sh root ROOT KBUILD` | after the OS tree is complete | add board binaries, enable board units |

Both run with `ZT_TOP` set.  The slot must be reproducible: same sources and
version give the same image, so hooks must not add time stamps or random data.

## Runtime interface

What UntrashOS calls on the device.  A board provides each item or leaves it
out; items marked *optional* are skipped when missing.

| Item | Used by | Contract |
|---|---|---|
| `/usr/lib/untrash/untrash-power boot\|shutdown\|tick\|next` | untrash-config, Desk power settings, `untrash-power*.service` | power-loss mode, Wake-on-LAN, scheduled power-on/off; `next` prints JSON `{"on": …, "off": …, "off_action": …}` |
| `/usr/lib/untrash/pylib/untrash_bays.py` → `bays()` | untrash-storage (disks, bay LEDs) | `{"disk1": "/dev/sdb", …}`: internal disks by bay |
| `untrash_bays.bay_count()` | untrash-storage (`BAY_NUM`: RAID limits, width of the stock md0/md1 mirrors) | number of bays of this device; *optional*, default 4 |
| `/usr/lib/untrash/untrash-model` | untrash-init, after the network firmware, before systemd | writes `/run/untrash/model.json` `{"id", "name", "title", "bays", "source"}` (e.g. `"NAS520"`, `"Zyxel NAS520"`, `2`); *optional* |
| `/run/untrash/model.json` | Desk (login, overview), installer page, MQTT device, via `pylib/untrash_device.py` | without it the board's `board.json` `title` is shown, without that a neutral "NAS"; a board must never guess a model it did not detect |
| `/run/untrash/device.env` | the board's model detection | written by untrash-init from the install record: `MODEL_ID`, `FWVERSION`, `ACTIVE_SLOT` (only these; the MAC addresses stay out of /run) |
| `/usr/lib/untrash/untrash-pfe-firmware CACHE` | untrash-init, before systemd | prepares network firmware; *optional* |
| `/run/untrash/fan.json` | Desk status (untrash_live) | JSON with `temp_c` and `time` (stale after 60 s), written by the board's fan control; *optional* |
| `/sys/bus/platform/devices/*buzzer*/play` | untrash-sound | write `"<hz> <ms>"`, one square-wave voice; *optional* |
| `/dev/watchdog` | untrash-init, untrash-wdt | a hardware watchdog |

| `/usr/share/untrash/board.json` | untrash-update, Desk | `{"name", "title", "releases", "asset"}`: `releases` = GitHub API URL of the firmware repo's releases, `asset` = file name pattern of the update file (`untrash-*-update.utslot`); without it there are no automatic updates |

Board services the OS knows by name: `untrash-power.service`,
`untrash-power-tick.timer` (enabled by untrash-config when a power schedule
is active).
