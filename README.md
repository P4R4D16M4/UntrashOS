# UntrashOS

UntrashOS is the operating system of the *Untrash* firmware projects: a
Debian-based NAS system with its own web desktop (Untrash Desk), the
services of a home NAS (shares, users, RAID, backup, media, cloud sync,
DNS ad filter) and A/B system slots with signed, verified updates.

## Features

- **Untrash Desk**: files, shares, users and groups, storage and RAID, iSCSI,
  network, backup, cloud sync, downloads, media server and broadcast channels,
  terminal, updates, logs; English, German, French; dark, light, high-contrast
  and colour-vision themes per user
- **NAS services**: SMB, FTP, NFS, WebDAV, DLNA, Time Machine, printers, DynDNS
- **Ad filter**: DNS for the home network that blocks ads and trackers, with
  block lists (StevenBlack, Hagezi), own allow/block rules, a query log and
  statistics
- **UntrashMesh**: an encrypted network (WireGuard) between UntrashOS devices,
  at home and over the internet, without a cloud provider or a fixed IP
  address; shares offered to members as partner volumes (read-only or
  read/write) and an off-site mirror of a data volume on another member (DRBD)
- **UntrashApp**: the phone app joins the mesh and can be a second factor for
  signing in ([app API](docs/architecture/app-api.md))
- **Office**: documents on the NAS are edited in the browser through an
  external office server (WOPI host; [office](docs/architecture/office.md))
- **Nextcloud** as a mesh member: keeps the mesh's address book, follows file
  changes on the shares and reaches them through an encrypted tunnel
  ([nextcloud](https://github.com/P4R4D16M4/UntrashOS/blob/v1.2/docs/architecture/nextcloud.md))
- **Smart home**: the NAS reports to Home Assistant or any other MQTT smart home
- **RAM boost**: an SSD becomes a memory extension for devices with little RAM
- **Updates**: signed slot images, found on the release page of the firmware
  repository or uploaded by hand; two slots with automatic fallback
- **Sounds**: a melody editor for the buzzer

Nextcloud, smart home and RAM boost come with 1.2 and are on the
[`v1.2`](https://github.com/P4R4D16M4/UntrashOS/tree/v1.2) branch.

This repository holds the device-independent part.  A firmware repository
builds the images for one device family and adds kernel, loader, installer
and board support:

| Firmware | Devices |
|---|---|
| [ZyxelUntrash](https://github.com/P4R4D16M4/ZyxelUntrash) | Zyxel NAS540, NAS542 |

## Contents

| Path | |
|---|---|
| `design/` | design system (`untrash.css`), assets, UI translations |
| `image/` | root filesystem (mkosi), UntrashOS files (`image/rootfs/`), slot builder, tests |
| `slot/` | slot signatures (Ed25519) and the trusted public keys |
| `tools/i18n/` | translation catalogs |
| `docs/` | [board interface](docs/board-interface.md), architecture notes |

## Tests

```
make test
```

runs the PC tests.  Parts that need board tools run when a firmware
repository passes `BOARD_ROOTFS=<board>/rootfs`.

## License

GPL-3.0, see `LICENSE`.  Third-party code under `third_party/` and
`image/rootfs/usr/share/untrash/desk/vendor/` keeps its own license.
