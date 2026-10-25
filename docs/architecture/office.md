# Office bridge (document server)

Decision 2026-10-22 (plan item 5): the NAS stores the documents, and an
office suite running elsewhere edits them. Collabora Online, Nextcloud
Office and ONLYOFFICE need several GiB of RAM, so they do not run on this
board.

## Way 1: Nextcloud uses the shares (no NAS-side code)

Nextcloud mounts NAS shares as **External storage**, and Nextcloud Office
then edits the files there.

- **WebDAV:** `http://<NAS>:5002/webdav/<share>` (HTTPS on 5003), with the
  same rights as the share. Switch it on under Settings → Services.
- **SMB:** `\\<NAS>\<share>`.

Over UntrashMesh the Nextcloud can be at a member's place: use
`<name>.mesh` as the host.

## Way 2: WOPI host on the NAS (`untrash-desk`)

`untrash-desk` implements a WOPI host. Any WOPI client can open documents
from the Desk's Files app; the office server only needs network access to
the NAS.

**Setup (Settings → Office, admin):**
- **Office server:** the address of the office server, e.g.
  `https://office.example.org:9980`.
- **Address of this NAS, as the office server reaches it:** the WOPISrc
  base, e.g. `http://untrash.local` or `http://untrash.mesh`.
- **Self-signed certificate:** optionally accept one on the office server.

The NAS fetches `<server>/hosting/discovery` (cached for an hour) and takes
the `edit` action per file extension, or `view` if there is no edit
action. URL placeholders such as `<ui=UI_LLCC&>` are removed. Files shows
**Open in Office** for these extensions.

**Opening a document:**
1. The browser calls `POST /api/office/open {share, path}`. The user needs
   read access to the file.
2. The NAS answers with the editor URL
   (`urlsrc` + `WOPISrc=<base>/wopi/files/<id>` + `lang`), an access token
   and its expiry.
3. The browser opens a new tab that frames the editor (an iframe) and posts
   `access_token` and `access_token_ttl` into it as a form. The token
   therefore never appears in the browser's address bar or history.
4. The tab answers the editor's postMessages (`PostMessageOrigin` in
   CheckFileInfo = the Desk's origin, kept in the token):
   - **Save As** and **Export As** (`UI_SaveAs`): a name field, then
     `Action_SaveAs`. The editor saves the copy next to the document
     (PutRelativeFile), e.g. a PDF.
   - **Close** (`UI_Close`) closes the tab.
   Collabora only allows the frame when the Desk's origin may frame it: when
   the Desk is opened under another address than the WOPISrc base (e.g.
   `untrash.local` vs. `untrash.mesh`), add that origin to Collabora's
   `net.frame_ancestors`.

**File id.** `sha256(share + "\0" + path)`, first 32 hex digits. It is
stable, so two people editing the same file share one editing session.

**Access token.** It holds user, share, path and expiry (10 h), signed
with HMAC-SHA256 under the key `/etc/untrash/wopi.key` (32 random bytes,
mode 0600, made on first use). Deleting the key invalidates all tokens. A
token is only valid for its own file id.

**Rights on every request.** Each WOPI request checks the user's share
rights again, at that moment. A user who lost access is refused, even
with an unexpired token.

**Endpoints** (no session; the token decides):

| Request | WOPI operation |
|---|---|
| `GET /wopi/files/<id>` | CheckFileInfo: `BaseFileName`, `Size`, `Version`, `UserId`, `UserCanWrite`, `SupportsLocks`, `SupportsGetLock`, `SupportsUpdate`, `LastModifiedTime`, … |
| `GET /wopi/files/<id>/contents` | GetFile, with header `X-WOPI-ItemVersion` |
| `POST /wopi/files/<id>/contents` | PutFile |
| `POST /wopi/files/<id>` + `X-WOPI-Override: LOCK / GET_LOCK / REFRESH_LOCK / UNLOCK` (LOCK + `X-WOPI-OldLock` = UnlockAndRelock) | locks |
| `POST /wopi/files/<id>` + `X-WOPI-Override: PUT_RELATIVE` | PutRelativeFile ("Save As", "Export as PDF"): `X-WOPI-SuggestedTarget` (a name or only an extension, never overwrites: "name (2).pdf") or `X-WOPI-RelativeTarget` (exact; `409` + `X-WOPI-ValidRelativeTarget` when it exists, unless `X-WOPI-OverwriteRelativeTarget: true`); names UTF-7 encoded; answer `{Name, Url, LastModifiedTime}` |
| other overrides (RENAME_FILE, …) | `501` |

**PutFile:**
- It writes to a temporary file in the same folder, `fsync`s it, then
  renames it over the original.
- The file keeps its owner and mode, so stock rights stay intact.
- The largest document is 512 MB.
- A save is refused (`409` with `X-WOPI-Lock`) only when another session
  holds a lock. Deviating from the WOPI rule "no PutFile without a lock",
  editors that never lock can still save.

**Locks.** They are kept in memory for 30 minutes and refreshed by the
editor. A restart of the Desk drops them.

**Proof keys.** When the discovery publishes a `<proof-key>`, every WOPI
request must carry `X-WOPI-TimeStamp` (within 20 minutes) and an
`X-WOPI-Proof` (or `-ProofOld`) signature: RSA PKCS#1 v1.5 / SHA-256 over
token, upper-case URL (WOPISrc base + path + query) and time stamp, checked
in pure Python. Without it only the token counts. Collabora publishes a key
only when it has one: `coolwsd-generate-proof-key`, or a PEM RSA key mounted
as `/etc/coolwsd/proof_key` in the container.

**Not done:** RenameFile (`501`): the file id is derived from the path, so
a rename would change the id under an open session.

### Office server notes

Collabora was tried as described above; ONLYOFFICE was not. Check the
suite's own documentation.

- **Collabora Online / CODE:** the NAS must be an allowed WOPI host. With
  the CODE container that is the `aliasgroup1=<WOPISrc base>` environment
  variable; otherwise `storage.wopi` / `alias_groups` in `coolwsd.xml`.
- **ONLYOFFICE Docs:** WOPI has to be switched on in its configuration.
- **Security:** the office server must reach the NAS on the WOPISrc address
  (port 80, or the HTTPS port). Between the office server and the NAS the
  file and the token travel unencrypted unless that address is HTTPS or a
  mesh address (WireGuard). On the LAN, prefer the mesh address or HTTPS.

## Tests

`image/tests/test-desk-host.py`, section "office bridge":
- a stand-in office server serves the discovery;
- the test plays the editor: CheckFileInfo, GetFile, all lock operations
  and PutFile;
- it checks rights (read-only, deny, rights at request time) and the token
  (wrong, expired, other file).

**Tried with a real office server (2026-10-25):** Collabora Online CODE
26.04 (container `collabora/code`, `aliasgroup1=<WOPISrc base>`, SSL off
on the PC). Opening a document from the Desk, editing it and saving it back
works; Collabora locks and unlocks through the WOPI host. With a proof key
mounted, its signed requests pass and a request with the token alone is
refused. In the framing tab, Export As → PDF and Save As (a name with
umlauts) put the copies next to the document. Faults found and fixed:
Collabora reads `LastModifiedTime` from the PutFile and PutRelativeFile
answers. ONLYOFFICE has not been tried.
