# UntrashOS

UntrashOS is the operating system of the *Untrash* firmware projects: a
Debian-based NAS system with its own web desktop (Untrash Desk), the
services of a home NAS (shares, users, RAID, backup, media, cloud sync,
DNS ad filter) and A/B system slots with signed, verified updates.

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
