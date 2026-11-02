<?php

declare(strict_types=1);

namespace OCA\Untrash\Cloudlink;

use OCA\Untrash\Mesh\Mesh;
use OCA\Untrash\Mesh\MeshException;
use OCP\Http\Client\IClientService;

/**
 * Requests to untrash-cloudlink on a NAS, signed with this cloud's node key
 * (cloud-api.md, "Signed requests"): UTCL1, method, path below the base URL,
 * time, nonce, sha256 of the body.
 */
class Client {
    private Mesh $mesh;
    private IClientService $clients;

    public function __construct(Mesh $mesh, IClientService $clients) {
        $this->mesh = $mesh;
        $this->clients = $clients;
    }

    public function get(\stdClass $nas, string $path, int $timeout = 30): array {
        [$nid] = $this->mesh->identity();
        $ts = (string)time();
        $nonce = bin2hex(random_bytes(16));
        $sig = $this->mesh->signBytes(implode("\n", ['UTCL1', 'GET', $path, $ts, $nonce, hash('sha256', '')]));
        try {
            $r = $this->clients->newClient()->get(rtrim($nas->base, '/') . $path, [
                'headers' => ['Authorization' => "UntrashCloud node=$nid, ts=$ts, nonce=$nonce, sig=$sig"],
                'timeout' => $timeout, 'verify' => (bool)($nas->verify ?? true), 'http_errors' => false,
                'nextcloud' => ['allow_local_address' => true]]);
        } catch (\Exception $e) {
            throw new MeshException('The NAS is not reachable: ' . $e->getMessage());
        }
        $body = json_decode((string)$r->getBody(), true);
        if ($r->getStatusCode() === 401) {
            throw new MeshException('The NAS refused this Nextcloud: ' . ($body['error'] ?? 'not linked there'));
        }
        if ($r->getStatusCode() !== 200 || !is_array($body)) {
            throw new MeshException('The NAS answered HTTP ' . $r->getStatusCode()
                . ' (is WebDAV on, and is this the address of its WebDAV port?)');
        }
        return $body;
    }
}
