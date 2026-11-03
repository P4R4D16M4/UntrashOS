<?php

declare(strict_types=1);

namespace OCA\Untrash\Mesh;

use OCP\Files\IAppData;
use OCP\Files\NotFoundException;
use OCP\Files\SimpleFS\ISimpleFolder;
use OCP\Http\Client\IClientService;
use OCP\IL10N;
use OCP\IURLGenerator;
use OCP\Lock\ILockingProvider;
use OCP\Lock\LockedException;
use OCP\Security\ICrypto;

/**
 * This Nextcloud as a cloud member of UntrashMesh (docs/architecture/
 * cloud-api.md): its Ed25519 node key, the roster and address book, the
 * join with a cloud invitation and the directory's merge rules.  The rules
 * are those of untrash-mesh (merge, roster_ok, record_ok): only what members
 * signed is ever stored.
 *
 * State lives in the app data folder "mesh" (node.json with the secret key
 * encrypted by Nextcloud, mesh.json, book.json, nas.json, nonces.json,
 * tunnel.json); every read-modify-write holds the lock "untrash/mesh".
 *
 * Tunnel (cloud-api.md §4): a root helper on this server (untrash-cloud-wg)
 * runs the WireGuard interface; this app only puts the helper's public key
 * and endpoint into its own signed record and tells the helper which NAS
 * members to accept as peers.
 */
class Mesh {
    public const PROTO = 1;
    public const WG_RE = '#^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$#';
    private const LOCK = 'untrash/mesh';

    private IAppData $appData;
    private ICrypto $crypto;
    private ILockingProvider $locking;
    private IClientService $clients;
    private IURLGenerator $urls;
    private IL10N $l;

    public function __construct(IAppData $appData, ICrypto $crypto, ILockingProvider $locking, IClientService $clients,
                                IURLGenerator $urls, IL10N $l) {
        $this->l = $l;
        $this->appData = $appData;
        $this->crypto = $crypto;
        $this->locking = $locking;
        $this->clients = $clients;
        $this->urls = $urls;
    }

    // ------------------------------------------------------------ storage

    private function folder(): ISimpleFolder {
        try {
            return $this->appData->getFolder('mesh');
        } catch (NotFoundException $e) {
            return $this->appData->newFolder('mesh');
        }
    }

    /** @return mixed decoded JSON (objects as stdClass), or $default */
    public function load(string $name, $default) {
        try {
            $v = json_decode($this->folder()->getFile($name)->getContent());
            return $v === null ? $default : $v;
        } catch (NotFoundException $e) {
            return $default;
        }
    }

    public function save(string $name, $value): void {
        $data = json_encode($value, JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT);
        $f = $this->folder();
        try {
            $f->getFile($name)->putContent($data);
        } catch (NotFoundException $e) {
            $f->newFile($name, $data);
        }
    }

    public function locked(callable $fn) {
        // the database locking provider does not wait: a directory sync or the tunnel helper may hold it a moment
        for ($i = 0; ; $i++) {
            try {
                $this->locking->acquireLock(self::LOCK, ILockingProvider::LOCK_EXCLUSIVE);
                break;
            } catch (LockedException $e) {
                if ($i >= 100) {
                    throw $e;
                }
                usleep(100000);
            }
        }
        try {
            return $fn();
        } finally {
            $this->locking->releaseLock(self::LOCK, ILockingProvider::LOCK_EXCLUSIVE);
        }
    }

    // ------------------------------------------------------------ identity and signatures

    /** [node id, public key hex, secret key (binary)]; made once. */
    public function identity(): array {
        $n = $this->load('node.json', null);
        if (!$n) {
            $kp = sodium_crypto_sign_keypair();
            $n = (object)['pub' => bin2hex(sodium_crypto_sign_publickey($kp)),
                          'sec' => $this->crypto->encrypt(bin2hex(sodium_crypto_sign_secretkey($kp)))];
            $this->save('node.json', $n);
        }
        return [self::nodeId($n->pub), $n->pub, hex2bin($this->crypto->decrypt($n->sec))];
    }

    public static function nodeId(string $pubHex): string {
        return substr(hash('sha256', hex2bin($pubHex)), 0, 16);
    }

    public function signBytes(string $msg): string {
        return bin2hex(sodium_crypto_sign_detached($msg, $this->identity()[2]));
    }

    public function sign(\stdClass $obj): \stdClass {
        unset($obj->sig);
        $obj->sig = $this->signBytes(Canon::encode($obj));
        return $obj;
    }

    public static function verifyBytes(string $msg, string $sigHex, string $pubHex): bool {
        if (!preg_match('/^[0-9a-f]{128}$/', $sigHex) || !preg_match('/^[0-9a-f]{64}$/', $pubHex)) {
            return false;
        }
        return sodium_crypto_sign_verify_detached(hex2bin($sigHex), $msg, hex2bin($pubHex));
    }

    public static function verify($obj, string $pubHex): bool {
        return $obj instanceof \stdClass && is_string($obj->sig ?? null) && self::verifyBytes(Canon::encode($obj), $obj->sig, $pubHex);
    }

    // ------------------------------------------------------------ roster and records

    public static function members($roster): array {
        return ($roster instanceof \stdClass && ($roster->members ?? null) instanceof \stdClass) ? get_object_vars($roster->members) : [];
    }

    /** The mesh address of a member: the mesh's ULA /48 and 64 bits of its key (untrash-mesh address()). */
    public static function address(string $meshId, string $pubHex): string {
        $p = hash('sha256', 'untrash-mesh:' . $meshId, true);
        return (string)inet_ntop("\xfd" . substr($p, 0, 5) . "\0\0" . substr(hash('sha256', (string)hex2bin($pubHex), true), 0, 8));
    }

    public static function prefix(string $meshId): string {
        $p = hash('sha256', 'untrash-mesh:' . $meshId, true);
        return inet_ntop("\xfd" . substr($p, 0, 5) . str_repeat("\0", 10)) . '/48';
    }

    private static function admins($roster): array {
        // keys as strings: PHP turns an all-digit node id into an int key
        return array_map('strval', array_keys(array_filter(self::members($roster), function ($m) {
            return ($m->role ?? '') === 'admin';
        })));
    }

    private static function rosterOk($new, $old): bool {
        if (!($new instanceof \stdClass) || ($new->type ?? '') !== 'roster' || !$old) {
            return false;
        }
        $by = $new->by ?? '';
        if (!in_array($by, self::admins($old), true) || ($new->mesh ?? '') !== $old->mesh
            || !is_int($new->seq ?? null) || $new->seq <= $old->seq || !(($new->members ?? null) instanceof \stdClass)) {
            return false;
        }
        return self::verify($new, self::members($old)[$by]->pub);
    }

    private static function recordOk($rec, $roster): bool {
        if (!($rec instanceof \stdClass) || ($rec->type ?? '') !== 'node' || !is_string($rec->node ?? null)) {
            return false;
        }
        $m = self::members($roster)[$rec->node] ?? null;
        return $m && ($rec->pub ?? '') === $m->pub && self::verify($rec, $m->pub);
    }

    /** New rosters and records in (the caller holds the lock). */
    private function mergeLocked($items): void {
        if (!is_array($items)) {
            return;
        }
        $st = $this->load('mesh.json', null);
        if (!$st || !isset($st->roster)) {
            return;
        }
        $book = $this->load('book.json', new \stdClass());
        foreach ($items as $x) {
            if ($x instanceof \stdClass && ($x->type ?? '') === 'roster' && self::rosterOk($x, $st->roster)) {
                $st->roster = $x;
                $this->save('mesh.json', $st);
            }
        }
        foreach ($items as $x) {
            if (self::recordOk($x, $st->roster)) {
                $cur = $book->{$x->node} ?? null;
                if (!$cur || ($x->seq ?? 0) > ($cur->seq ?? 0)) {
                    $book->{$x->node} = $x;
                }
            }
        }
        foreach (array_keys(get_object_vars($book)) as $k) {        // records of members that left
            if (!isset(self::members($st->roster)[$k])) {
                unset($book->$k);
            }
        }
        $this->save('book.json', $book);
    }

    // ------------------------------------------------------------ directory

    /** The base URL of this directory (POST <dir>/v1/sync). */
    public function dirUrl(): string {
        return preg_replace('#/v1/sync$#', '', $this->urls->linkToRouteAbsolute('untrash.mesh.sync'));
    }

    /**
     * Answer a POST <dir>/v1/sync: [HTTP status, body or null].
     * Merge first (a roster may name the sender for the first time), then
     * check sender, time, signature and nonce; then the records it lacks.
     */
    public function syncAnswer(string $raw, string $remote): array {
        $req = json_decode($raw);
        if (!($req instanceof \stdClass) || strlen($raw) > (1 << 20)) {
            return [400, null];
        }
        return $this->locked(function () use ($req, $remote) {
            $st = $this->load('mesh.json', null);
            if (!$st || !isset($st->roster)) {
                return [404, null];
            }
            $this->mergeLocked($req->items ?? null);
            $st = $this->load('mesh.json', null);
            [$nid] = $this->identity();
            $ms = self::members($st->roster);
            if (!isset($ms[$nid])) {                       // this cloud was removed from the mesh
                $this->save('book.json', new \stdClass());
                return [403, null];
            }
            $m = $ms[$req->from ?? ''] ?? null;
            $now = time();
            if (!$m || !is_int($req->ts ?? null) || abs($now - $req->ts) > 120 || !is_string($req->nonce ?? null)
                || !self::verify($req, $m->pub)) {
                return [403, null];
            }
            $nonces = (array)$this->load('nonces.json', new \stdClass());
            $nonces = array_filter($nonces, function ($t) use ($now) {
                return $t > $now;
            });
            if (isset($nonces[$req->nonce])) {
                return [403, null];
            }
            $nonces[$req->nonce] = $now + 300;
            $this->save('nonces.json', (object)$nonces);
            $have = ($req->have ?? null) instanceof \stdClass ? $req->have : new \stdClass();
            $out = [];
            foreach (get_object_vars($this->load('book.json', new \stdClass())) as $n => $r) {
                if (($r->seq ?? 0) > ($have->$n ?? 0)) {
                    $out[] = $r;
                }
            }
            if ($st->roster->seq > (is_int($req->roster ?? null) ? $req->roster : 0)) {
                array_unshift($out, $st->roster);
            }
            return [200, ['items' => $out, 'you' => $remote]];
        });
    }

    // ------------------------------------------------------------ joining

    public static function safeName(string $n): string {
        $n = trim(preg_replace('/[^a-z0-9-]/', '-', strtolower($n)), '-');
        $n = substr($n, 0, 32);
        return preg_match('/^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$/', $n) ? $n : 'nextcloud';
    }

    /**
     * Join the mesh of a cloud invitation (made on an UntrashOS NAS with
     * "Connect a Nextcloud").  Returns the status.
     */
    public function join(string $text, string $name): array {
        $inv = Canon::b64urlDecode($text);
        if (!($inv instanceof \stdClass) || ($inv->v ?? 0) !== self::PROTO || !is_array($inv->h ?? null) || !$inv->h
            || !is_string($inv->s ?? null) || !preg_match('/^[0-9a-f]{32}$/', $inv->s)) {
            throw new MeshException($this->l->t('This is not an UntrashMesh invitation.'));
        }
        if (($inv->k ?? '') !== 'cloud') {
            throw new MeshException($this->l->t('This invitation is not for a Nextcloud. On the NAS choose UntrashMesh → Connect a Nextcloud.'));
        }
        if (time() > (int)($inv->e ?? 0)) {
            throw new MeshException($this->l->t('The invitation has expired.'));
        }
        $st = $this->load('mesh.json', null);
        if ($st && isset($st->mesh)) {
            throw new MeshException($this->l->t('This Nextcloud is in a mesh already. Leave it first.'));
        }
        [$nid, $pub] = $this->identity();
        $name = self::safeName($name);
        $req = (object)['i' => (string)($inv->i ?? ''), 'node' => $nid, 'pub' => $pub, 'wg' => '', 'name' => $name,
                        'kind' => 'cloud', 'ep' => [], 'dir' => $this->dirUrl()];
        $req->mac = hash_hmac('sha256', Canon::encode($req), hex2bin($inv->s));
        $client = $this->clients->newClient();
        $ans = null;
        $last = '';
        $until = time() + 30;          // the NAS opens its join port a moment after it made the invitation
        while ($ans === null) {
            foreach ($inv->h as $h) {
                $host = strpos((string)$h, ':') !== false ? '[' . $h . ']' : (string)$h;
                try {
                    $r = $client->post('http://' . $host . ':' . (int)($inv->p ?? 7341) . '/v1/join', [
                        'body' => json_encode($req, JSON_UNESCAPED_SLASHES), 'headers' => ['Content-Type' => 'application/json'],
                        'timeout' => 15, 'http_errors' => false, 'nextcloud' => ['allow_local_address' => true]]);
                } catch (\Exception $e) {
                    $last = $e->getMessage();
                    continue;
                }
                if ($r->getStatusCode() === 403) {
                    throw new MeshException($this->l->t('The NAS refused the invitation: it was used already, or it is not for a Nextcloud.'));
                }
                if ($r->getStatusCode() === 200) {
                    $ans = json_decode((string)$r->getBody());
                    break;
                }
                $last = 'HTTP ' . $r->getStatusCode();
            }
            if ($ans === null) {
                if (time() > $until) {
                    break;
                }
                sleep(1);
            }
        }
        if (!($ans instanceof \stdClass)) {
            throw new MeshException($this->l->t('The NAS is not reachable (%s). It must be reachable from this server while the Nextcloud joins.', [$last]));
        }
        $mac = (string)($ans->mac ?? '');
        unset($ans->mac);
        if (!hash_equals(hash_hmac('sha256', Canon::encode($ans), hex2bin($inv->s)), $mac)) {
            throw new MeshException($this->l->t('The answer is not from the inviting NAS.'));
        }
        $roster = $ans->roster ?? null;
        $ms = self::members($roster);
        if (($roster->mesh ?? '') !== $inv->m || !isset($ms[$nid]) || !isset($ms[$roster->by ?? ''])
            || !self::verify($roster, $ms[$roster->by]->pub)) {
            throw new MeshException($this->l->t('The NAS did not take this Nextcloud in.'));
        }
        $this->locked(function () use ($inv, $roster, $ans, $name, $nid, $pub) {
            $this->save('mesh.json', (object)['mesh' => (object)['id' => $inv->m, 'name' => (string)($inv->n ?? ''), 'joined' => time()],
                                              'name' => $name, 'roster' => $roster]);
            $this->save('book.json', new \stdClass());
            $this->mergeLocked(is_array($ans->items ?? null) ? $ans->items : []);
            $this->ownRecordLocked();
            // the inviting NAS: its change feed on the WebDAV port of the address the invitation named;
            // HTTPS (5003) when its record pins its TLS key, plain HTTP (5002) for an older NAS
            $nas = new \stdClass();
            $h = (string)$inv->h[0];
            $host = strpos($h, ':') !== false ? '[' . $h . ']' : $h;
            $nas->{$roster->by} = (object)['base' => $this->tlsPin((string)$roster->by) ? 'https://' . $host . ':5003/untrash-cloudlink'
                                                     : 'http://' . $host . ':5002/untrash-cloudlink',
                                           'verify' => true, 'cursor' => ''];
            $this->save('nas.json', $nas);
        });
        return $this->status();
    }

    /**
     * The TLS key pin of a member ("sha256//<base64>", curl's
     * CURLOPT_PINNEDPUBLICKEY form) from its signed record, or null.  The
     * record is signed by the member's node key, which the roster vouches
     * for: its self-signed HTTPS needs no certificate authority.
     */
    public function tlsPin(string $node): ?string {
        $rec = $this->load('book.json', new \stdClass())->$node ?? null;
        $pin = $rec->tls ?? null;
        return is_string($pin) && preg_match('#^sha256//[A-Za-z0-9+/]{43}=$#', $pin) ? $pin : null;
    }

    // ------------------------------------------------------------ tunnel (cloud-api.md §4)

    /** This cloud's record, signed again with seq + 1: name, tunnel key and endpoints (caller holds the lock). */
    private function ownRecordLocked(): void {
        $st = $this->load('mesh.json', null);
        if (!$st || !isset($st->mesh)) {
            return;
        }
        [$nid, $pub] = $this->identity();
        $t = $this->load('tunnel.json', new \stdClass());
        $cur = $this->load('book.json', new \stdClass())->$nid ?? null;
        $this->mergeLocked([$this->sign((object)['type' => 'node', 'proto' => self::PROTO, 'node' => $nid, 'pub' => $pub,
                                                 'wg' => (string)($t->wg ?? ''), 'name' => (string)$st->name,
                                                 'ep' => array_values((array)($t->ep ?? [])),
                                                 'seq' => (int)($cur->seq ?? 0) + 1, 'time' => time()])]);
    }

    /**
     * The helper's round (occ untrash:tunnel sync): its WireGuard public key
     * and public endpoints ("" and [] = no tunnel), the last handshake per
     * peer key.  A changed key or endpoint goes into a new own record, which
     * the NAS members fetch from this directory.  Returns what the helper
     * applies: this node's mesh address, the mesh prefix and the NAS members
     * as peers (their roster keys: the cloud needs no apps or other clouds).
     */
    public function tunnelSync(string $wg, array $eps, array $handshakes): array {
        if ($wg !== '' && !preg_match(self::WG_RE, $wg)) {
            throw new MeshException('not a WireGuard public key');
        }
        $eps = array_values(array_unique(array_filter($eps, function ($e) {
            return is_string($e) && strlen($e) <= 80 && preg_match('#^(\d{1,3}(\.\d{1,3}){3}|\[[0-9a-fA-F:.]+\]):\d{1,5}$#', $e);
        })));
        if (count($eps) > 4 || ($wg === '') !== !$eps) {
            throw new MeshException('a key needs 1 to 4 endpoints (host:port, [v6]:port), and endpoints a key');
        }
        return $this->locked(function () use ($wg, $eps, $handshakes) {
            $t = $this->load('tunnel.json', new \stdClass());
            $now = time();
            if (($t->wg ?? '') !== $wg || array_values((array)($t->ep ?? [])) !== $eps) {
                $t->wg = $wg;
                $t->ep = $eps;
                $t->hs = new \stdClass();
                $this->save('tunnel.json', $t);
                $this->ownRecordLocked();
            }
            $st = $this->load('mesh.json', null);
            $out = ['mesh' => null, 'address' => null, 'prefix' => null, 'peers' => []];
            if (!$st || !isset($st->mesh) || !isset(self::members($st->roster ?? null)[$this->identity()[0]])) {
                return $out;                          // not (or no longer) in a mesh: no peers
            }
            $book = $this->load('book.json', new \stdClass());
            $hs = new \stdClass();
            $out = ['mesh' => $st->mesh->id, 'address' => self::address($st->mesh->id, $this->identity()[1]),
                    'prefix' => self::prefix($st->mesh->id), 'peers' => []];
            foreach (self::members($st->roster) as $k => $m) {
                $k = (string)$k;
                if (($m->kind ?? 'nas') !== 'nas' || !preg_match(self::WG_RE, (string)($m->wg ?? ''))) {
                    continue;
                }
                $out['peers'][] = ['node' => $k, 'name' => $book->$k->name ?? $m->name ?? $k, 'wg' => $m->wg,
                                   'address' => self::address($st->mesh->id, $m->pub)];
                if (is_int($handshakes[$m->wg] ?? null) && $handshakes[$m->wg] > 0) {
                    $hs->$k = $handshakes[$m->wg];
                }
            }
            // the handshakes are only for the settings page: saved when a peer came up or went down, or every 5 minutes
            $up = function ($h) use ($now) {
                return array_keys(array_filter((array)$h, function ($x) use ($now) {
                    return $now - $x < 180;
                }));
            };
            if ($wg !== '' && ($up($hs) != $up($t->hs ?? []) || $now - (int)($t->t ?? 0) > 300)) {
                $t->hs = $hs;
                $t->t = $now;
                $this->save('tunnel.json', $t);
            }
            return $out;
        });
    }

    public function leave(): void {
        $this->locked(function () {
            foreach (['mesh.json', 'book.json', 'nas.json', 'nonces.json'] as $f) {
                try {
                    $this->folder()->getFile($f)->delete();
                } catch (NotFoundException $e) {
                }
            }
        });
    }

    public function status(): array {
        [$nid] = $this->identity();
        $st = $this->load('mesh.json', null);
        $book = $this->load('book.json', new \stdClass());
        $nas = $this->load('nas.json', new \stdClass());
        $t = $this->load('tunnel.json', new \stdClass());
        $out = ['node' => $nid, 'dir' => $this->dirUrl(), 'mesh' => $st->mesh ?? null, 'name' => $st->name ?? null, 'members' => [],
                'tunnel' => ($t->wg ?? '') !== '' ? ['wg' => $t->wg, 'endpoints' => $t->ep, 'reported' => $t->t ?? null] : null,
                // an admin removed this cloud on a NAS: it no longer serves the directory
                'removed' => $st && isset($st->mesh) && !isset(self::members($st->roster ?? null)[$nid])];
        foreach (self::members($st->roster ?? null) as $k => $m) {
            $k = (string)$k;
            $rec = $book->$k ?? null;
            $n = $nas->$k ?? null;
            $out['members'][] = ['node' => $k, 'name' => $rec->name ?? $m->name ?? $k, 'kind' => $m->kind ?? 'nas',
                                 'role' => $m->role ?? 'member', 'self' => $k === $nid, 'endpoints' => $rec->ep ?? [],
                                 'seen' => $rec->time ?? null,
                                 'pinned' => isset($rec->tls),
                                 'address' => isset($st->mesh->id) ? self::address($st->mesh->id, $m->pub) : null,
                                 'tunnel' => $t->hs->$k ?? null,
                                 'feed' => $n ? ['base' => $n->base, 'verify' => $n->verify, 'last' => $n->last ?? null] : null];
        }
        return $out;
    }
}
