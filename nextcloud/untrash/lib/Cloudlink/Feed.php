<?php

declare(strict_types=1);

namespace OCA\Untrash\Cloudlink;

use OCA\Untrash\Mesh\Mesh;
use OCA\Untrash\Mesh\MeshException;
use OCP\Files\IRootFolder;
use OCP\DB\QueryBuilder\IQueryBuilder;
use OCP\IDBConnection;
use OCP\Lock\ILockingProvider;
use OCP\Lock\LockedException;
use Psr\Log\LoggerInterface;

/**
 * The change feed of the linked NAS applied to Nextcloud's file cache.
 *
 * External storages (WebDAV backend, admin mounts) whose URL is the NAS and
 * whose remote folder is webdav/<share> get each reported path stat'ed and
 * updated (or removed), with etags propagated to the parents, instead of a
 * scan.  Their "Check for changes" can then be "Never".  A share the NAS
 * reports for a rescan is scanned once.  Mounts with credentials that only
 * live in a user's session cannot be reached from here; they are skipped.
 */
class Feed {
    private Mesh $mesh;
    private Client $client;
    private IRootFolder $root;
    private IDBConnection $db;
    private ILockingProvider $locking;
    private LoggerInterface $log;

    public function __construct(Mesh $mesh, Client $client, IRootFolder $root, IDBConnection $db, ILockingProvider $locking,
                                LoggerInterface $log) {
        $this->mesh = $mesh;
        $this->client = $client;
        $this->root = $root;
        $this->db = $db;
        $this->locking = $locking;
        $this->log = $log;
    }

    /** One round for every NAS with a feed address; wait = long poll seconds. */
    public function run(int $wait, ?callable $say = null): array {
        $out = [];
        foreach (get_object_vars($this->mesh->load('nas.json', new \stdClass())) as $node => $nas) {
            $node = (string)$node;
            $lock = 'untrash/feed/' . $node;
            try {
                $this->locking->acquireLock($lock, ILockingProvider::LOCK_EXCLUSIVE);
            } catch (LockedException $e) {
                continue;                               // another run (cron or occ) has this NAS
            }
            try {
                $out[$node] = $this->one($node, $nas, $wait, $say);
            } finally {
                $this->locking->releaseLock($lock, ILockingProvider::LOCK_EXCLUSIVE);
            }
        }
        return $out;
    }

    private function one(string $node, \stdClass $nas, int $wait, ?callable $say): array {
        $res = ['t' => time(), 'ok' => false];
        try {
            $q = '/v1/changes?' . http_build_query(['since' => (string)($nas->cursor ?? ''), 'wait' => $wait]);
            $ch = $this->client->get($nas, $q, $wait + 30, $this->mesh->tlsPin($node));
            $host = parse_url($nas->base, PHP_URL_HOST) ?: '';
            $n = 0;
            foreach ($ch['rescan'] ?? [] as $share) {
                foreach ($this->storages(trim($host, '[]'), (string)$share) as $st) {
                    $st->getScanner()->scan('', \OC\Files\Cache\Scanner::SCAN_RECURSIVE,
                                            \OC\Files\Cache\Scanner::REUSE_ETAG | \OC\Files\Cache\Scanner::REUSE_SIZE);
                }
                $say && $say("rescan $share");
            }
            $byShare = [];
            foreach ($ch['changes'] ?? [] as $c) {
                $byShare[(string)$c['share']][] = (string)$c['path'];
            }
            foreach ($byShare as $share => $paths) {
                foreach ($this->storages(trim($host, '[]'), $share) as $st) {
                    $up = $st->getUpdater();
                    foreach ($paths as $p) {
                        if ($p !== '' && $st->file_exists($p)) {
                            $up->update($p);
                        } elseif ($p !== '') {
                            $up->remove($p);
                        }
                        $n++;
                    }
                }
                $say && $say("$share: " . count($paths) . ' changed');
            }
            $res = ['t' => time(), 'ok' => true, 'changes' => count($ch['changes'] ?? []), 'rescan' => $ch['rescan'] ?? [],
                    'applied' => $n];
            $this->setCursor($node, (string)($ch['cursor'] ?? ''), $res);
        } catch (MeshException $e) {
            $res['error'] = $e->getMessage();
            $this->setCursor($node, null, $res);
            $this->log->warning('untrash feed ' . $node . ': ' . $e->getMessage());
        }
        return $res;
    }

    private function setCursor(string $node, ?string $cursor, array $last): void {
        $this->mesh->locked(function () use ($node, $cursor, $last) {
            $all = $this->mesh->load('nas.json', new \stdClass());
            if (!isset($all->$node)) {
                return;
            }
            if ($cursor !== null) {
                $all->$node->cursor = $cursor;
            }
            $all->$node->last = $last;
            $this->mesh->save('nas.json', $all);
        });
    }

    /** Host names case-insensitively, IP addresses by value (fd00::1 = fd00:0::1, the mesh addresses). */
    private static function sameHost(string $a, string $b): bool {
        $pa = @inet_pton($a);
        $pb = @inet_pton($b);
        return ($pa !== false && $pb !== false) ? $pa === $pb : strcasecmp($a, $b) === 0;
    }

    /**
     * Storages of the external mounts on this NAS share: WebDAV backend, host
     * = the NAS, remote folder webdav/<share>.  One storage per distinct
     * storage id (per credentials), taken through a user who has it mounted.
     *
     * @return \OCP\Files\Storage\IStorage[]
     */
    private function storages(string $host, string $share): array {
        $ids = [];
        try {
            $svc = \OCP\Server::get(\OCA\Files_External\Service\GlobalStoragesService::class);
            $configs = $svc->getAllStorages();
        } catch (\Throwable $e) {
            return [];                                  // files_external is off
        }
        foreach ($configs as $c) {
            if ($c->getBackend()->getIdentifier() !== 'dav') {
                continue;
            }
            $o = $c->getBackendOptions();
            $h = (string)($o['host'] ?? '');
            $h = parse_url(strpos($h, '://') === false ? 'http://' . $h : $h, PHP_URL_HOST) ?: '';
            $rootPath = trim(rawurldecode((string)($o['root'] ?? '')), '/');
            if (self::sameHost(trim($h, '[]'), $host) && $rootPath === 'webdav/' . $share) {
                $ids[] = $c->getId();
            }
        }
        if (!$ids) {
            return [];
        }
        $qb = $this->db->getQueryBuilder();
        $qb->select('storage_id', 'user_id', 'mount_point')->from('mounts')
            ->where($qb->expr()->in('mount_id', $qb->createNamedParameter($ids, IQueryBuilder::PARAM_INT_ARRAY)));
        $res = $qb->executeQuery();
        $seen = [];
        $out = [];
        while ($row = $res->fetch()) {
            if (isset($seen[$row['storage_id']])) {
                continue;
            }
            $seen[$row['storage_id']] = true;
            try {
                $this->root->getUserFolder($row['user_id']);           // sets up that user's mounts
                $out[] = $this->root->get(rtrim($row['mount_point'], '/'))->getStorage();
            } catch (\Throwable $e) {
                $this->log->info('untrash feed: mount ' . $row['mount_point'] . ' not usable here: ' . $e->getMessage());
            }
        }
        $res->closeCursor();
        return $out;
    }
}
