# Nextcloud companion (concept)

Status: phase 1 (NAS side) implemented on the PC, 2026-11-02; contract in
`cloud-api.md`. Not run on hardware yet.

Decision 2026-11-02: UntrashOS gets a companion for **existing Nextcloud
installations**, as a release of its own. The reference installation is
Nextcloud 25. As with office
(`office.md`), Nextcloud itself does not run on the NAS (1 GiB RAM, 32-bit
Cortex-A9). The NAS stores and serves the data, and Nextcloud runs elsewhere.

## Goal

An existing Nextcloud uses the NAS as data and media storage, with the share
rights unchanged. It also gets the UntrashOS functions that a plain WebDAV/SMB
"External storage" does not give it:

| UntrashOS part | In Nextcloud |
|---|---|
| Stock takeover | Old Zyxel shares, users and rights work without migration |
| Change feed (new) | Nextcloud learns about changes without scanning, so the disks can sleep |
| UntrashMesh | Nextcloud becomes the mesh's directory: its stable HTTPS address finds members that lost each other |
| Recycle bin, backup, mirror | Restore from the NAS bin; backup/mirror state per folder |
| Transfers / downloads | "Load URL to NAS"; large copies run on the NAS |
| Notify / health | Disk, RAID, update events as Nextcloud notifications; dashboard widget |

## Parts

### 1. NAS: `untrash-cloudlink`

A new service on the NAS. Nextcloud does not pair separately: it joins
the mesh as a **cloud member** with a cloud invitation (§3), and its node
key signs the requests. Contract: `cloud-api.md`.

| Endpoint | Purpose | Phase |
|---|---|---|
| `GET /v1/info` | Name, version, shares linked for this cloud | 1, done |
| `GET /v1/changes?since=<cursor>&wait=<s>` | Change feed, long poll | 1, done |
| `GET /v1/health` | Disks (incl. sleep state), md arrays, volumes | 1, done |
| `GET /v1/events?since=` | Notify events for Nextcloud notifications | 3 |
| `GET /v1/trash`, `POST /v1/trash/restore` | NAS recycle bin (per user rights) | 3 |
| `GET /v1/backup?path=` | Backup/mirror state of a folder | 3 |
| `POST /v1/transfer` | Download a URL into a share (untrash-transfer) | 4 |

File content itself is **not** part of this API. It stays on the existing
WebDAV (`:5002/:5003/webdav/<share>`) with the share rights.

**Change feed.** fanotify with a filesystem mark and
`FAN_REPORT_DFID_NAME` (kernel 6.6 has it). Proven on the PC on a real ext4
(`test_cloudlink_fanotify_root.py`). Unlike inotify, it needs no watch
per directory, so the feed does not cost RAM per directory. It covers ext4 and
btrfs volumes; it does not cover CIFS partner mounts (those get `rescan`). The
journal is a RAM ring with a monotonic cursor. On overflow or service restart,
the affected share is reported in `rescan[]`. The feed answers from RAM and
never touches the disks.

Runs in `untrash-background.slice` (v1.2 memory tiers).

### 2. Nextcloud app `untrash`

A normal PHP app (`appinfo/info.xml`, `IBootstrap`).

- **Storage backend "UntrashOS NAS"** for `files_external`: based on the
  built-in WebDAV storage; takes NAS host, share and the pairing.
- **Feed instead of scanning:** the mount is set to "check for changes:
  never". A background job (or an `occ` command run as a service) reads
  `/v1/changes` and updates the file cache only for the reported paths.
- **Notifications** (`INotifier`) from `/v1/events`.
- **Dashboard widget** (`IWidget`): NAS health, disks asleep/awake, backups.
- **Admin settings:** pairing, NAS address (LAN or mesh).
- Later: restore from the NAS bin, backup state in the file sidebar,
  "load URL to NAS".

Credentials: per-user "username and password" (stored by Nextcloud) or
"login credentials" when Nextcloud and NAS users have the same names and
passwords. The rights check stays on the NAS (`untrash-authd`).

### 3. Mesh membership: Nextcloud as the directory

Nextcloud is a mesh member of the new kind `cloud` (user decision
2026-11-02: its stable public address makes it the mesh's address
directory).

- **Directory.** Members store their signed records there and fetch the
  others' records over HTTPS (`<dir>/v1/sync`, signed by the node key). When
  a WireGuard member has had no handshake for 3 minutes, the NAS asks the
  directory. The directory holds only signed data, so it cannot redirect
  anyone. Done in `untrash-mesh` (phase 1).
- **File access.**
  - LAN: direct WebDAV.
  - Over the internet: the NAS's WebDAV TLS port, or later a WireGuard link
    of the Nextcloud host. That needs root on the host, so it is a separate
    small agent and not part of the PHP app.

## Version range

- Nextcloud 25 is out of support as well. The app starts at
  `min-version="25"` because existing users run it (the reference
  installation moved from 24 to 25 on 2026-11-02). The manual recommends a
  current version.
- The server-side parts (storage backend, background job, notifications,
  dashboard, settings) use APIs present from 25 to current.
- The directory needs Ed25519 in PHP (`sodium_crypto_sign_verify_detached`,
  ext-sodium). Check that it is there on the reference installation.
- The Files UI changed with Nextcloud 28 (new Vue Files app). File-sidebar
  integration therefore needs two code paths (≤27, ≥28) and comes last.

## Phases

1. **Done on the PC (2026-11-02).**
   - NAS side: cloud member and directory sync in `untrash-mesh`;
     `untrash-cloudlink` with info, changes and health; Apache pass-through
     on the WebDAV ports.
   - Tests: `test-cloudlink-host.py` (in make test),
     `test_cloudlink_fanotify_root.py` (root), `test-webdav-host.py`
     (pass-through).
   - Open: the Desk UI (invite a Nextcloud, choose its shares), a hardware
     run (fanotify on the A9 and the stock ext4 volumes).
2. Nextcloud app, minimum: join (paste the invitation), directory
   (`/v1/sync`), storage backend, feed → cache update, admin settings.
   Tested with Docker `nextcloud:25` and the current stable image against the
   PC test mode of the NAS services. `image/tests/mesh-directory-ref` is the
   reference behaviour of the directory.
3. Dashboard widget, bin restore, backup state, mesh server member.
4. File sidebar (two UI paths), "load URL to NAS".
5. App store publication (needs a Nextcloud app signing certificate and the
   user's OK).

## To verify in the prototype

- Does the file-cache update for a single path work on an external storage
  with per-user credentials from a background job, which has no session?
  If not, the feed job needs a service credential (read-only) from the NAS.
- Does `files_trashbin` handle deletions on external storage? This decides
  whether the NAS bin needs its own restore UI in Nextcloud.
- The exact `files_external` backend registration API for third-party apps
  in 25 and in the current version.
- fanotify filesystem marks on the stock-takeover ext4 volumes (untested
  on hardware), and the CPU cost on the A9 during large copies.
- Thumbnails/previews: Nextcloud generates them on its own host from the
  WebDAV data; check how much disk wake-up that causes.
