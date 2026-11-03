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

A cloud joins **without a WireGuard key**: it gets no WireGuard peer and no
`<name>.mesh` name, and it is reached only over `dir`. It can become a
tunnel peer later through its own record (§4).

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
- At least every 10 minutes anyway (`ZT_MESH_DIR_PULL`), so a cloud's
  own new record (§4) reaches every NAS.
- The `you` IP becomes the NAS's last-resort endpoint `<ip>:51820`, if it is
  public. That endpoint only works when port 51820 is forwarded to the NAS.

The UntrashApp uses the same endpoint with its own node key (`app-api.md` §3, "Mesh directory").

## 3. untrash-cloudlink

**Base URL:**
- `https://<NAS>:5003/untrash-cloudlink`, on the WebDAV port with the WebDAV
  TLS certificate;
- or `http://<NAS>:5002/untrash-cloudlink` on the LAN or over the mesh.

**TLS key pin.** The NAS certificate is self-signed (`untrash-tls`). A NAS
puts the pin of its TLS public key into its signed node record:
`"tls": "sha256//<base64 of sha256(SubjectPublicKeyInfo DER)>"`, the form
curl's `CURLOPT_PINNEDPUBLICKEY` takes.
- The cloud trusts the record because it trusts the NAS's node key through
  the roster. It then connects to `https://` with the pin instead of
  certificate authorities.
- Another key at that address fails, so there is no trust on first use.
- A new certificate gives a new record (higher `seq`).
- Records without `tls` come from an older NAS: the cloud falls back to the
  normal certificate check.
- On joining, the cloud takes `https://<h>:5003` when the inviting NAS's
  record has a pin, and `http://<h>:5002` when it has none.

Apache passes it to `localhost:7342` (untrash-cloudlink listens on loopback only). WebDAV must be switched on: the cloud
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

## 4. The cloud as a tunnel peer

A Nextcloud on the internet cannot reach a NAS behind a home router. A port
forward for WebDAV would put the users' passwords on the internet, so
UntrashOS does not do that. Instead the Nextcloud server can also be a
**WireGuard peer** of the mesh. It has a fixed public address, so the NAS
members connect out to it, and no port is forwarded at home. Nextcloud then
reaches each NAS inside the tunnel:
- WebDAV: `http://[<NAS mesh address>]:5002/webdav/<share>`;
- the feed: `http://[<NAS mesh address>]:5002/untrash-cloudlink`.

Plain HTTP is enough there: WireGuard encrypts it, and only the NAS's key
can answer from its mesh address.

**Key in the cloud's own record** (user decision 2026-11-03). The cloud signs
a new own record (`seq` + 1) with:
- `wg`: its WireGuard public key (44 characters of base64, 32 bytes);
- `ep`: 1 to 4 public endpoints, `IPv4:port` or `[IPv6]:port`.

The roster keeps `"wg": ""` for the cloud. It needs no new invitation and no
admin action. The NAS members take the key from the record because the
cloud's node key, which the roster vouches for, signs it. They take it only
for kind `cloud`; NAS and app members keep the roster's key. A record
without `wg`, or with a malformed one, means no tunnel. The peer is the
cloud's own mesh address (`/128`), so the key opens nothing else.

**NAS side** (`untrash-mesh`):
- WireGuard peer with `allowed-ips <cloud address>/128`, the record's
  endpoints, `persistent-keepalive 25`. The keepalive keeps the home
  router's NAT open, so the server can always answer.
- `<name>.mesh` in `/etc/hosts`.
- `status` gives the cloud a `tunnel` field: the last handshake, `null`
  before the first one, `false` without a tunnel.
- A cloud cannot offer shares (`/v1/offer`) or mirrors (`/v1/mirror`): the
  NAS answers `403`.
- **Firewall (nftables, since 1.2-rc3).** On `ut-mesh` a cloud peer
  reaches only TCP 5002 (WebDAV and `/untrash-cloudlink`), ICMPv6, and
  answers to connections the NAS opened. SSH, SMB, the Desk, DNS and the
  mesh sync stay closed to it. NAS and app members are not filtered.
  - The table is `inet untrash_mesh` with the set `clouds`, replaced as a
    whole on every change.
  - **Fail closed:** when the filter cannot be loaded, the cloud gets no
    WireGuard peer at all.
  - The kernel needs `kernel/config/system.d/30-firewall.config` (nftables
    built in), and the image needs the `nftables` package.
  - Tests: `test-cloudlink-host.py` (ruleset, fail closed) and
    `test_mesh_firewall_root.py` (real kernel and nft in two network
    namespaces).
  - Why: on 2026-11-03 the first hardware run showed that the tunnel
    opened every NAS service to the server, including a guest share.

**Server side.** The PHP app runs as the web server user and cannot make
network interfaces. A small root helper next to it,
`nextcloud/server/untrash-cloud-wg` (Python 3.8, standard library only), runs
the interface `ut-mesh`:
- kernel WireGuard, or `wireguard-go` where the kernel has none (an OpenVZ
  container with `/dev/net/tun`);
- its own WireGuard key in `/var/lib/untrash-cloud-wg/wg.key`;
- the endpoint is the source address of its default route when that is
  public, or `--endpoint`.

Every 30 s it runs one round:

```
occ untrash:tunnel sync --key <wg public> --endpoint <ip:port> --handshakes '{<peer key>: <unix>}'
→ {"mesh", "address", "prefix", "peers": [{"node", "name", "wg", "address"}]}
```

- When the key or endpoint changed, the app signs a new own record.
- `peers` are the roster's NAS members (with their roster keys). Apps and
  other clouds are not peers.
- The helper runs as root on what the web server user's PHP printed. It
  checks every value before it reaches `wg`, `ip` or the UAPI socket:
  - the prefix must be a ULA `/48`;
  - every address must be inside it;
  - every key must be a WireGuard key.
  Anything else is dropped (`nextcloud/tests/test_cloud_wg_checks.py`).
- The helper sets the address (`/48`), one `/128` per NAS and no endpoints:
  the NAS connect out, and WireGuard roaming learns where they are.
- The app keeps the handshakes for its settings page. It writes them only
  when a peer came up or went down, or every 5 minutes.
- `"mesh": null` (the cloud left, or was removed): the helper takes the
  interface down.
- `ip6tables` on `ut-mesh`: only answers to connections the server opened,
  plus ICMPv6, come in. The NAS members do not reach the server's own
  services.
- `untrash-cloud-wg --down` (or `occ untrash:tunnel off`) signs a record
  without `wg`, and the NAS drop the peer.

The mesh address is computed the same way on both sides:
`fd` + 5 bytes of `sha256("untrash-mesh:" + mesh id)` + 2 zero bytes +
8 bytes of `sha256(node public key)`. `test_nextcloud_docker.py` checks that
PHP and the NAS agree.
