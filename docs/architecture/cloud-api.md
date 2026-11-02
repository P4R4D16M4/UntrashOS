# Nextcloud ↔ UntrashOS API, version 1

The contract between UntrashOS (the NAS side, this repository) and the
Nextcloud app `untrash`, which is developed separately. Concept and plan:
`nextcloud.md`.

A Nextcloud with the app is a **cloud member** of UntrashMesh. It has two
roles:

1. **Directory of the mesh.** Nextcloud has what the NAS and the phones lack:
   a stable public HTTPS address. Every member stores its signed address
   record there and fetches the others' records from there. If all members
   lose each other at once (new public IP, phone on mobile data), the
   directory still knows where everyone is.
2. **Client of `untrash-cloudlink`** on each NAS that linked it. It gets a
   change feed (so it never scans the shares, and the disks can sleep) and
   the NAS status. The files themselves stay on WebDAV, with the users' own
   rights.

Reference implementation on the NAS:
- `image/rootfs/usr/lib/untrash/untrash-mesh` (cloud member, directory sync)
- `image/rootfs/usr/lib/untrash/untrash-cloudlink`

Reference cloud for the tests: `image/tests/mesh-directory-ref`.
Tests:
- `image/tests/test-cloudlink-host.py`
- `image/tests/test_cloudlink_fanotify_root.py` (root, real ext4)
- `image/tests/test-webdav-host.py` (the Apache pass-through)

Canonical JSON, the Ed25519 node key, node ids, invitations and the roster
are those of the app (`app-api.md` §1–3). Only the differences are listed
here.

## 1. Joining (cloud invitation)

An admin chooses which shares the cloud may follow and creates the
invitation (`untrash-mesh invite-cloud HOURS '["Photos","Music"]'`). The
invitation has `"k": "cloud"`. The Nextcloud admin pastes it into the app's
admin settings.

**Join.** `POST http://<h>:<p>/v1/join` with:

```
{"i", "node", "pub", "wg": "", "name", "kind": "cloud", "ep": [], "dir", "mac"}
```

- `dir` is the app's directory base URL, for example
  `https://cloud.example.org/index.php/apps/untrash/mesh`. It must match
  `https?://host[/path]`, with at most 300 characters. Use HTTPS on the
  internet. The NAS checks the certificate against the system CAs.
- `mac` is the same as for the app.
- The NAS refuses with `403`:
  - a cloud on a non-cloud invitation;
  - anything other than a cloud on a cloud invitation;
  - a missing or malformed `dir`.

The answer, the `mac` check and the roster check are the same as in
`app-api.md` §2. In the roster, the cloud has `"kind": "cloud"`,
`"wg": ""` and its `"dir"`. Its record keeps `ep: []`.

Cloud members get **no WireGuard peer** and no `<name>.mesh` name. They are
reached only over `dir`.

Only the inviting NAS stores the share link (`clouds.json`). Another NAS
links the cloud with `untrash-mesh cloud-link NODE '[...]'`. When an admin
removes the cloud from the mesh, every link to it disappears.

## 2. Directory

**`POST <dir>/v1/sync`**. The body is the member sync body plus a signature:

```
{"items": [records, roster], "have": {node: seq}, "roster": seq,
 "from": <node id>, "ts": <unix seconds>, "nonce": <32 hex>, "sig": <128 hex>}
```

- `sig` is Ed25519 over the canonical JSON without `sig`, made with the key
  of `from`.

What the directory must do, in this order:

1. **Merge `items` with the mesh rules** (`app-api.md` §3):
   - A roster is taken only when its `seq` is higher and an admin of the
     roster the directory already has signed it.
   - A record is taken only when a current member signed it and its `seq` is
     higher.
   - Records of non-members are dropped.
   - The first roster comes only from the join answer.
2. **Then check the sender.** `from` must be a member of the (possibly just
   updated) roster, `|now − ts| ≤ 120 s`, the signature must be valid and the
   nonce unused in the last 5 minutes. Otherwise answer `403` with no body.
3. **Answer** `200` with `{"items", "you"}`:
   - `items` are the records with a higher `seq` than in `have`, plus the
     directory's roster if its `seq` is higher than the request's `roster`.
   - `you` is the client IP as the directory saw it (behind a proxy: the
     forwarded address Nextcloud trusts).

If the cloud's own node is no longer in its roster (it was removed), it
deletes the address book and answers `403`.

The directory **never** creates or changes records. Everything it holds was
signed by members, so it cannot redirect anyone. It does learn the members'
endpoints, so it should be the server of people who are in the mesh anyway.

**When the NAS uses the directory.**
- It pushes its record there whenever its endpoints change (gossip, like to
  any member).
- Every 60 s, when a WireGuard member has had no handshake for 180 s, it
  pushes its own record and pulls the others'.
- Anti-entropy picks the cloud like any other member.
- The `you` IP becomes the NAS's last-resort endpoint `<ip>:51820`, if it is
  public. That endpoint only works when port 51820 is forwarded to the NAS.

The UntrashApp can use the same endpoint with its own node key (planned).

## 3. untrash-cloudlink

**Base URL:**
- `https://<NAS>:5003/untrash-cloudlink`, on the WebDAV port with the WebDAV
  TLS certificate;
- or `http://<NAS>:5002/untrash-cloudlink` on the LAN or over the mesh.

Apache passes it to the service on the loopback interface (port 7342). WebDAV must be switched on: the cloud
needs it for the files anyway. The service runs only while a cloud is linked.

### Signed requests

```
Authorization: UntrashCloud node=<node id>, ts=<unix seconds>, nonce=<16-64 hex>, sig=<128 hex>
```

`sig` is Ed25519 over these six lines, joined with `\n` and with no trailing
newline:

```
UTCL1
<METHOD>
<path below the base URL, with query>   e.g. /v1/changes?since=1a2b3c4d-17&wait=60
<ts>
<nonce>
<sha256 hex of the body>                of the empty string for GET
```

The path is signed **without** `/untrash-cloudlink`, so a proxy prefix does
not matter. The NAS answers `401 {"error"}` when:
- the header is missing or malformed;
- `|now − ts| > 120 s`;
- the node is not a cloud member linked on this NAS;
- the signature is wrong;
- the nonce was used in the last 5 minutes.

The nonce is only recorded after the signature check.

### Endpoints

| Request | Answer |
|---|---|
| `GET /v1/info` | `{"api": 1, "nas", "mesh", "node", "version", "you", "shares": [{"name", "webdav", "feed"}], "cursor"}` |
| `GET /v1/changes?since=C&wait=S` | `{"cursor", "changes": [{"share", "path"}], "rescan": [share], "more"?}` |
| `GET /v1/health` | `{"disks": [{"name", "asleep", "temp"}], "raid": [...], "volumes": [{"shares", "size", "free"}], "load", "mem", "uptime", "time"}` |

`shares` lists only the shares linked for this cloud that exist and are
enabled. `webdav` is the path below the WebDAV port (`/webdav/<name>`).
`feed: false` means the share has no change feed (a CIFS partner volume, or
its filesystem is not marked yet). The cloud then checks that share for
changes itself.

### Change feed

- **Paths.** `path` is relative to the share, with `/` as separator. `""` is
  the share root. A path can be a file or a folder, and it can be gone
  already: the cloud stats it over WebDAV and updates or removes its cache
  entry.
- **Renames** report both names. Folders appear once per new folder, and
  their contents come as separate entries.
- **Recycle bin and system folders** never appear: `.untrash*`, `@*`,
  `.recycle`, `lost+found` at the top of the share.
- **`rescan`** names shares whose changes are unknown. The cloud then
  rescans them fully, ideally at night. This happens:
  - on the first call (`since` empty);
  - after the service restarted (the cursor belongs to an older run);
  - after a kernel queue overflow;
  - when changes fell out of the RAM ring (20 000 entries);
  - when a folder vanished before its event was read.
- **`wait`** (seconds, at most 120) holds the request until something
  changes. An empty answer after `wait` keeps the cursor. Recommended:
  `wait=60` in a loop, which makes about one request per minute when nothing
  happens.
- **`more: true`**: more than 5 000 changes are pending. Ask again at once
  with the new cursor.
- Writes the cloud makes itself over WebDAV also show up in the feed. They
  are harmless.

### Feed implementation (NAS)

- fanotify: one group per filesystem, marked with `FAN_MARK_FILESYSTEM` and
  `FAN_REPORT_DFID_NAME`. Events: CREATE, DELETE, MOVED_FROM/TO, CLOSE_WRITE,
  with ONDIR.
- It needs no watch per folder and no limit on the number of folders. Each
  event's folder is resolved with `open_by_handle_at`.
- The service runs as root.
- Partner volumes (CIFS) cannot be marked. Their shares have `feed: false`.
