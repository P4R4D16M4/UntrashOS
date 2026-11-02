# Nextcloud companion (concept)

Status (2026-11-03):
- Phase 1 (NAS side) and the Desk UI are done on the PC.
- Phase 2 (the Nextcloud app `nextcloud/untrash`) is tested against a real
  Nextcloud 25 in Docker.
- The contract is in `cloud-api.md`.
- Nothing has run on NAS hardware yet.

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
  ext-sodium). info.xml declares it; the official Docker image of Nextcloud 25
  has it. Not checked yet on the reference installation.
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
2. **Done (2026-11-03): the Nextcloud app `nextcloud/untrash`**, PHP 7.4+,
   Nextcloud 25 to 31.
   - Join: admin settings page or `occ untrash:join`.
   - Directory `POST <dir>/v1/sync`, with the merge rules of untrash-mesh.
   - Canonical JSON (`Canon.php`) is checked against Python.
   - Change feed: `occ untrash:feed` as a long-poll service, plus a
     background job every 5 minutes. Each path is updated with
     `getUpdater()->update/remove` on every WebDAV external storage whose URL
     is the NAS and whose folder is `webdav/<share>`. A rescan does one
     recursive scan.
   - Test: `make test-nextcloud APACHEROOT=…` with Docker
     `nextcloud:25-apache` and the real NAS services (untrash-mesh,
     untrash-cloudlink, Apache WebDAV), 20 checks.
   - Decided instead of an own storage backend: the built-in WebDAV backend
     is used, and the app only finds its mounts. That is less code, and an
     existing mount keeps working without the app.
   - Open:
     - the background job itself (only `occ untrash:feed` is tested);
     - newer Nextcloud versions (28+);
     - user-created external storages (only admin mounts are followed);
     - UI texts are English only;
     - a self-signed NAS certificate can only be accepted with "check the
       HTTPS certificate" off, there is no pinning yet.
3. Dashboard widget, bin restore, backup state, mesh server member.
4. File sidebar (two UI paths), "load URL to NAS".
5. App store publication (needs a Nextcloud app signing certificate and the
   user's OK).

## To verify in the prototype

- **Answered 2026-11-03.** A file-cache update for a single path works
  without a session for mounts whose credentials are stored: global, user
  entered, or log-in credentials saved in the database. Mounts with "log-in
  credentials, save in session" are skipped. Each storage id (one per
  credential) is updated once, through a user who has it mounted
  (`oc_mounts.mount_id` = external storage id).
- Does `files_trashbin` handle deletions on external storage? This decides
  whether the NAS bin needs its own restore UI in Nextcloud.
- ~~The `files_external` backend registration API~~: not needed, the
  built-in WebDAV backend is used.
- fanotify filesystem marks on the stock-takeover ext4 volumes (untested
  on hardware), and the CPU cost on the A9 during large copies.
- Thumbnails/previews: Nextcloud generates them on its own host from the
  WebDAV data; check how much disk wake-up that causes.
