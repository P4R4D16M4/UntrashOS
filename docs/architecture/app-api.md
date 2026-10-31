# UntrashApp ↔ UntrashOS API, version 1

The contract between UntrashOS (the NAS side, this repository) and the
UntrashApp, the phone companion that is developed separately. An app that
implements this document can pair with a NAS, keep its address book current,
use the Desk JSON API and confirm sign-ins and actions.

Reference implementation on the NAS: `image/rootfs/usr/lib/untrash/untrash-mesh`
(mesh, pairing) and `image/rootfs/usr/lib/untrash/untrash-desk` (API, sign-in).
Tests: `image/tests/test-mesh-host.py`, `image/tests/test-desk-host.py`
(section "UntrashApp"). `GET /api/app/info` returns the version as `api`.
Additions that old apps can ignore keep version 1. Anything else raises it.

## 1. Identity and transport

- The app has an **Ed25519 key pair**. Keep the secret key in the phone's
  key store. Its **node id** is the first 16 hex digits of
  `sha256(public key)`.
- It has a **WireGuard key pair** too. All traffic between the app and a NAS
  goes through the mesh tunnel (`ut-mesh`, UDP 51820 on the NAS side).
- **Addresses.** For a mesh id `M`, the mesh prefix is
  `fd` + `sha256("untrash-mesh:" + M)[0:5]` + `0000` (a /48 ULA). A member's
  address is that prefix's first 8 bytes plus `sha256(public key)[0:8]`.
  The app derives every member's address itself. Members are also reachable
  as `<name>.mesh` on NAS nodes (their `/etc/hosts`). The app resolves names
  from the roster and the address book.
- **Desk API.** It lives at `http://[<NAS mesh address>]/api/...` (port 80).
  The Desk listens there as soon as the NAS is in a mesh, with plain HTTP
  even when the NAS forces HTTPS: the WireGuard tunnel already encrypts it.
  Signed requests (§4) are only accepted from the app's own mesh address.

## 2. Pairing

An admin chooses **UntrashMesh → Pair the UntrashApp** in the Desk and picks
the Desk user the app will act as. The Desk shows a QR code with an
invitation. The invitation works once and is valid for 1 hour. The same text
can also be pasted.

The invitation is base64url (no padding) of compact JSON:

| key | meaning |
|---|---|
| `v` | protocol, `1` |
| `i` | invitation id |
| `s` | one-time secret (32 hex digits) |
| `m`, `n` | mesh id, mesh name |
| `h` | hosts of the inviting NAS (LAN and public addresses) |
| `p` | its join port (TCP, normally 7341) |
| `e` | expiry (Unix time) |
| `k` | `"app"` on invitations for the app (absent on NAS invitations) |

**Join.** `POST http://<h>:<p>/v1/join` with the JSON
`{"i", "node", "pub", "wg", "name", "kind": "app", "ep": [...], "mac"}`.
`pub` is the Ed25519 public key in hex. `wg` is the WireGuard public key in
base64. `name` is shown to the users; it is lower case, `[a-z0-9-]`, and up
to 32 characters. `ep` is the list of endpoints `host:port` where the app's
WireGuard listens; it may be empty.

The `mac` is HMAC-SHA256 with the secret (hex-decoded) as key, over the
canonical JSON of the request without `mac`. Canonical JSON means keys
sorted, separators `,` and `:` without spaces, and ASCII only: as Python's
`json.dumps(sort_keys=True, separators=(",", ":"))` writes it, every
character outside space…`~` is a `\uXXXX` escape (lower-case hex, UTF-16
surrogate pairs), so `ü` is `ü`. A top-level `sig` is never part of
it. The same form is signed for records and rosters.

- **Accepted:** `200`, answer `{"roster", "items", "mac"}`. The `mac` covers
  the answer the same way. Check it before trusting anything.
- **Refused:** `403` (wrong or used invitation). Do not retry.

`roster` is the member list signed by an admin node:
`{"type": "roster", "mesh", "seq", "by", "members": {node: {"pub", "wg", "name",
"role", "kind"}}, "sig"}`. The `sig` is Ed25519 over the canonical JSON
without `sig`, made with the key of `members[by]`. `items` are the node
records of the address book (§3).

On an app invitation, the inviting NAS also **links** the app to the Desk
user the admin chose. That link exists only on that NAS. On any other NAS,
an admin links the app under UntrashMesh → **Link…**. Without a link, the
app is a mesh member there but cannot use the Desk API.

## 3. Address book (sync)

Each member, the app included, publishes a signed **node record**:
`{"type": "node", "proto": 1, "node", "pub", "wg", "name", "ep": [...],
"seq", "time", "sig"}`.

- `seq` grows with every change; a higher `seq` replaces a lower one.
- `ep` lists the endpoints the app can be reached at, if any.
- `sig` is Ed25519 over the canonical JSON without `sig`, made with the
  node's key.

**Sync.** `POST http://[<member mesh address>]:7340/v1/sync` with
`{"items": [records, roster], "have": {node: seq}, "roster": seq}`.

- The answer is `{"items": [...], "you": "ip:port"}`.
- `items` are the records the other side has in newer versions, plus its
  roster if that one is newer.
- `you` is the endpoint the NAS saw the request come from. Put it into your
  own record when it changes; that is how NAS members find a phone that
  moves between networks.
- Records and rosters are only taken with a valid signature from a current
  member (roster: from an admin of the roster you have, with a higher
  `seq`).

**Push.** Send your new record to every reachable member as soon as your
address changes. Members pass it on to the others. Apps may also sync every
few minutes while in the foreground.

**Notify (optional).** A NAS sends `POST http://[<app address>]:7340/v1/app-notify`
(body `{}`) when a request for the app's user waits. An app that cannot
listen in the background simply polls `/api/app/requests` (§5).

## 4. Signed requests

Every Desk API request of the app carries:

```
Authorization: UntrashApp node=<node id>, ts=<unix seconds>, nonce=<16-64 hex>, sig=<128 hex>
```

`sig` is Ed25519 over the UTF-8 bytes of these six lines, joined with `\n`
and with no trailing newline:

```
UTAPP1
<METHOD>                 GET or POST
<path with query>        exactly as sent, e.g. /api/files?share=Photos&path=
<ts>
<nonce>
<sha256 hex of the body> of the empty string for GET
```

The NAS refuses (`401`) the request when:
- the signature is wrong;
- `ts` is more than 120 s away from its clock;
- the nonce was used in the last 5 minutes;
- the node is not an app member linked to a user here;
- the request did not come from the app's mesh address.

A signed request acts as the linked user, with that user's rights; for a
user in the administrators group, that includes the admin endpoints.
Neither the session cookie nor the `X-UT` header is needed. Bodies are JSON
up to 1 MiB. In version 1 the app cannot use the streamed uploads
(`/api/files/upload`, `/api/update/upload`, `/api/downloads/torrent`).

## 5. Endpoints for the app

| Request | Answer |
|---|---|
| `GET /api/app/info` | `{"api": 1, "user", "admin", "node", "nas", "version", "mesh", "signin"}` |
| `GET /api/app/requests` | `{"requests": [{"id", "kind", "action", "detail", "ip", "agent", "choices": [n, n, n], "created", "expires"}]}` |
| `POST /api/app/answer` `{"id", "approve": true/false, "code": n}` | `{"state": "approved" or "denied"}`; `404` if the request is gone |

These answer only signed requests (`403` for a browser session).

**Number matching.** The browser shows a two-digit number; the app shows
the three `choices`. Approving with the wrong number denies the request: the
person at the phone is not the person at that browser.

`kind`:
- `login`: a sign-in without password (user's sign-in is "password or app")
- `login2`: the second factor after a correct password (sign-in "password and app")
- `confirm`: an action of a user with sign-in "password and app". `action`
  names it, `detail` the object (user name, node) if any. The actions:
  installing an update, deleting a user, resetting a user's sign-in, removing
  a mesh member, leaving the mesh, going back to the stock firmware.

A request waits 120 s. Requests for a user are only shown to that user's
apps.

The rest of the API is the Desk's own (`/api/shares`, `/api/files`,
`/api/overview`, `/api/update`, …). It has no separate reference yet: the
Desk (`desk.js`) is its only client besides the app, and
`image/tests/test-desk-host.py` exercises it.

## 6. Sign-in modes (per Desk user)

| Mode | Desk sign-in |
|---|---|
| `password` (default) | password only |
| `app` | password, or a confirmation in the app without password |
| `both` | password and then a confirmation in the app; listed actions also need the app |

- **Changing the mode:** the user changes it under Account, entering the
  password. `app` and `both` need a linked app.
- **App removed or unlinked:** the mode falls back to `password`.
- **Lost phone:** an admin resets a user under Users → **Reset to
  password**. For admin itself, the RESET button on the NAS does it (the
  admin password reset also resets the sign-in).
- **Requests the app signs itself** need no extra confirmation: the app is
  the second factor.

## 7. Browser side (for reference)

- `POST /api/login {"user", "password"}` returns either a session, or
  `{"second": id, "code": n}` for mode `both`.
- `POST /api/login/app {"user"}` returns `{"id", "code", "expires"}`. It
  answers the same for unknown users, so the answer does not reveal whether
  a user exists or has an app.
- `GET /api/login/app?id=` returns `{"state": "pending", "approved",
  "denied", "expired" or "used"}`. On `approved` it also sets the session
  cookie, once.
- An action that needs the app answers `428 {"confirm": id, "code": n,
  "action"}`. `GET /api/confirm?id=` polls the state; the browser then
  repeats the call with `"confirm": id` in the body. A confirmation is valid
  once, for the same user, action and object.
