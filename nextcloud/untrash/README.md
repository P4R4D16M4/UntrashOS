# UntrashOS app for Nextcloud

This Nextcloud joins an **UntrashMesh**, the encrypted network of UntrashOS
devices. The contract is `docs/architecture/cloud-api.md` in this repository.

- **Directory.** Mesh members keep their signed address records at
  `<this Nextcloud>/index.php/apps/untrash/mesh/v1/sync`. When they lose each
  other (a new internet address, a phone on mobile data), they find each other
  again through it. It stores only what members signed.
- **Change feed.** A linked NAS reports which files changed in its shares.
  External storages on that NAS are then updated path by path instead of being
  scanned, so the NAS disks can sleep.

Requirements: Nextcloud 25 or newer, PHP with sodium, the app *External
storage support* for the feed.

## Setup

1. On the NAS: **UntrashMesh → Connect a Nextcloud**. Choose the shares, then
   copy the invitation.
2. Here: **Administration settings → UntrashOS**. Paste the invitation and
   choose **Join**. This server must reach the NAS while it joins. The same
   works with `occ untrash:join <invitation> --name <name>`.
3. **Change feed.** Joining fills in the address of the NAS WebDAV port,
   for example `https://nas.local:5003/untrash-cloudlink`. Change it if this
   server reaches the NAS under another name. **Test** shows the shares the NAS
   lets this Nextcloud follow.
   - Over HTTPS the NAS's self-signed certificate is checked against the key
     pin in its signed mesh record ("HTTPS key pinned through the mesh").
   - Another key at that address is refused.
4. **External storage**, one per share:
   - Backend **WebDAV**.
   - URL: the NAS (for example `nas.local:5002`).
   - Remote subfolder: `webdav/<share>`.
   - **Check for changes: Never.**
   - Credentials that work without a user session (global, stored in the
     database, or log-in credentials saved in the database). Mounts with
     credentials that exist only in the session are skipped by the feed.

## NAS behind a router: the tunnel

A Nextcloud on the internet cannot reach a NAS at home by its LAN address.
Do not forward the WebDAV port: that would put the users' passwords on the
internet. Instead, make this server a WireGuard peer of the mesh. The NAS
connect out to it, so nothing is forwarded at home. Contract:
`cloud-api.md` §4.

What the server needs:
- root;
- `wireguard-tools`;
- kernel WireGuard, or `wireguard-go` in `/usr/local/sbin` (for example an
  OpenVZ container with `/dev/net/tun`);
- UDP 51820 open in the server's firewall, and in the hoster's firewall
  if it has one;
- Python 3.8 or newer.

Setup:

```
install -m 755 nextcloud/server/untrash-cloud-wg /usr/local/sbin/
install -m 644 nextcloud/server/untrash-cloud-wg.service /etc/systemd/system/
untrash-cloud-wg --once          # one round: prints the peers, or the error
systemctl enable --now untrash-cloud-wg
```

- The helper finds the public address from the default route. Behind NAT,
  give it with `--endpoint IP:51820` (edit `ExecStart`).
- Nextcloud in another path: `--occ "runuser -u www-data -- php /path/occ"`.
- Within about 10 minutes every NAS has the new record and connects. The
  settings page then shows **Tunnel connected** per NAS. **Use the mesh
  address** sets the feed address to `http://[<mesh address>]:5002/untrash-cloudlink`.
- External storage through the tunnel, one per share:

  ```
  occ files_external:create /Photos dav password::password \
      -c host='[<NAS mesh address>]:5002' -c root=webdav/Photos -c secure=false
  occ files_external:option <id> filesystem_check_changes 0
  ```

  Add the credentials in the settings, or with `-c user=… -c password=…`
  for a global mount. `occ untrash:status` lists each NAS's `address`.
  Plain HTTP is right here: WireGuard encrypts it.
- `untrash-cloud-wg --down` ends the tunnel: the NAS drop the peer.

## Feed timing

The background jobs apply the changes every 5 minutes. For changes within
seconds, run the feed as a service under the web server user:

```
[Unit]
Description=UntrashOS change feed for Nextcloud
After=network-online.target

[Service]
User=www-data
ExecStart=/usr/bin/php /var/www/nextcloud/occ untrash:feed
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

## Commands

| Command | Purpose |
|---|---|
| `occ untrash:join INVITATION [--name N]` | join the mesh |
| `occ untrash:status` | membership, members, feed state (JSON) |
| `occ untrash:nas NODE URL [--insecure]` | feed address of a NAS |
| `occ untrash:feed [--once] [--wait S]` | apply the change feed (loop, or one round) |
| `occ untrash:tunnel sync\|off` | the tunnel helper's interface (cloud-api.md §4) |

## Translations

German (`de`, `de_DE`) and French. The source is
`nextcloud/l10n/catalog.py` in the UntrashOS repository; `nextcloud/l10n/build.py`
writes `l10n/`. A new UI text needs an entry there (`build.py --check` runs in
`make test`).

## Tests

`nextcloud/tests/test_nextcloud_docker.py APACHEROOT [IMAGE]` tests this app
against a real Nextcloud (default image `nextcloud:25-apache`) and the NAS
side of this repository.
