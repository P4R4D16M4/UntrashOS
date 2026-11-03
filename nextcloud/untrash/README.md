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

## Translations

German (`de`, `de_DE`) and French. The source is
`nextcloud/l10n/catalog.py` in the UntrashOS repository; `nextcloud/l10n/build.py`
writes `l10n/`. A new UI text needs an entry there (`build.py --check` runs in
`make test`).

## Tests

`nextcloud/tests/test_nextcloud_docker.py APACHEROOT [IMAGE]` tests this app
against a real Nextcloud (default image `nextcloud:25-apache`) and the NAS
side of this repository.
