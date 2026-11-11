# UntrashKey

The UntrashOS stick as a hardware key: chosen areas of the system work only
while a stick paired with this NAS is plugged in.  Off by default ("vanilla"
UntrashOS behaves as before).  Code: `image/rootfs/usr/lib/untrash/pylib/untrash_key.py`, `untrash_stick.py`,
`untrash-key`, `untrash-key-watch`, `untrash-key.service`, the `KEY_GUARD` table
in `untrash-desk`.  Tests: `image/tests/test_untrash_key_host.py`, `test_untrash_stick_host.py`, the
UntrashKey part of `image/tests/test-desk-host.py`.

## Why

An admin password is the whole defence of the Desk: whoever has it (phished,
guessed, read off a sticky note, a session taken over on a shared PC, a Desk
reached over a forgotten port forward) gets a root shell through the web
terminal and can make the access last (new admin, app or mesh link, SSH, a
port forward, a backup job to their own cloud).  UntrashKey adds something
the attacker does not have: physical access to the NAS and the stick.

## The key

- The stick is the UntrashOS stick (FAT label `UNTRASHPK`).  The system never
  mounts it as a USB volume (`60-untrash.rules`), so the Desk's file manager
  cannot read the key on it.
- Pairing writes `UNTRASH/untrashkey/<nas>.key`:
  `UNTRASHKEY1 <nas id> <64 hex digits>` (256 random bits).  The NAS stores only
  the SHA-256 in `/etc/untrash/untrashkey.json` (mode 0600).  One stick can be
  a key for several NAS (one file each).
- **Pairing needs someone at the NAS:** after the admin starts it in the Desk,
  the stick has to be attached *after* that moment (pulled and plugged in
  again, two minutes).  "After" is the kernel's `diskseq`, a number every
  disk attach gets anew and that only grows.  The same rule is the way back
  after a lost key: admin plus physical presence.
- **Presence** = the verified attach is still there: the by-label link points
  to the same device and its disk has the same `diskseq`.  This is checked live
  on every protected request (two small sysfs reads); the key file itself is
  read once per attach.  Only a USB device counts (no loop or iSCSI disk with
  the same label).

## Keys belong to administrators, the log names them

Every key belongs to one Desk administrator (chosen when pairing or
creating; keys paired before had none and open for every administrator).
A key opens the Desk areas and changes to UntrashKey only for its owner; SSH
(the system, not a Desk user) runs while any paired key is in.  Every
protected Desk action a key opens is logged with the key's id:

```
untrashkey: key 6767a6e6 (Anna's key) opened system for anna: /api/update/install
untrashkey: key 6767a6e6 (Anna's key, user anna) plugged in
untrashkey: key 6767a6e6 (Anna's key) pulled
```

(journal of `untrash-desk` and `untrash-key`; Desk → Logs.)

## Stick archive and new key sticks

The installer stores a copy of the stick in the state of the installed
system (`/var/lib/untrash/stick/`, `pylib/untrash_stick.py`): the release
files its `SHA256SUMS` lists (checked, without `UNTRASH/INSTALL`) and the
completed PartnerKey install run of this NAS (flash backup, `device.env`,
`etc-zyxel.tar`), about the size of the stick's content (~0.7 GB).  Systems
installed before store it from the plugged original stick in the Desk; its
stock run only if its `ETH0_MAC` is this NAS's eth0.  An installed update
replaces the system in the archive (`refresh_system`), so new sticks start
the current release.

**Create a key stick** (Desk, admin, typed `FORMAT`): the first USB disk
attached after the request (diskseq again: someone is at the NAS) is erased
and written like `install/mk-stick-image.sh` does it: MBR with the blackbox
header, FAT32 `UNTRASHPK` from 32 MiB, the release files, the stock run,
then its own key for the chosen administrator; everything is read back
against the checksums.  The new stick is a full UntrashOS stick: rescue
system (it has no `UNTRASH/INSTALL`, so a NAS that boots normally ignores
it), way back to stock, and UntrashKey.  It needs `dosfstools` and `parted`
in the image.

## Areas

| Area | Default | Protects |
|---|---|---|
| `ssh` | on | `ssh.service` `ExecCondition=untrash-key allow ssh`; `untrash-key-watch` stops sshd and kills every `sshd` process when the stick is pulled and starts it again (if SSH is enabled or the stick carries SSH keys) when it is plugged in |
| `terminal` | on | `/api/term`; an open session checks every 2 s and closes when the stick is pulled |
| `access` | on | users and groups (create, delete, members = admin rights), another user's password, sign-in reset, mesh create/invite/join/remove/leave, app pairing and links, cloud invitations |
| `exposure` | on | `/api/settings` with `services`, `network` or `smarthome`; UPnP port forwarding, certificate, iSCSI |
| `system` | on | update install/upload/settings, way back to stock, ending processes |
| `data` | off | RAID jobs, shares, backup and cloud jobs, mesh shares and mirrors |

A protected Desk call without the key answers **423** with `{"untrashkey": area}`;
the Desk shows "Plug in your UntrashKey", polls `/api/untrashkey` and repeats
the call when the key is in (like the 428 of the UntrashApp confirmation).
UntrashApp requests go through the same check.

## Rules

- Switching on needs at least one paired key, plugged in now (no lock-out).
- While on, every change (areas, off, removing a key, the stick's SSH keys)
  needs the key.  Pairing does not (it needs physical presence instead).
- The last key can only be removed after switching off.
- **SSH keys on the stick** (`UNTRASH/ssh/authorized_keys`, plain public key
  lines only, no options): while UntrashKey is on they are used only from the
  paired stick and only while it is plugged in (`/run/untrash/servicekey/`,
  RAM).  The boot-time service key (`untrash-servicekey`, dev sticks) steps
  aside while UntrashKey is on.

## Limits

- While the stick is plugged in, the protected areas are open to anyone with
  the admin password.  The stick belongs in a drawer, not in the NAS.
- The key file can be copied by anyone who has the stick in hand; it is a
  physical key, not a smart card.
- Root on the NAS can do anything, including editing the configuration.
  UntrashKey keeps an attacker from *getting* root over the Desk or SSH.
- Not protected: the RESET button window (physical already), normal file
  access of users, and the non-admin parts of the Desk.
- One UntrashOS stick at a time: with two plugged in, the kernel's
  `/dev/disk/by-label/UNTRASHPK` names only one of them.
