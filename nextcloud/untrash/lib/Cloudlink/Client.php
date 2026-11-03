<?php

declare(strict_types=1);

namespace OCA\Untrash\Cloudlink;

use OCA\Untrash\Mesh\Mesh;
use OCA\Untrash\Mesh\MeshException;
use OCP\Http\Client\IClientService;
use OCP\IL10N;

/**
 * Requests to untrash-cloudlink on a NAS, signed with this cloud's node key
 * (cloud-api.md, "Signed requests"): UTCL1, method, path below the base URL,
 * time, nonce, sha256 of the body.
 */
class Client {
    private Mesh $mesh;
    private IClientService $clients;
    private IL10N $l;

    public function __construct(Mesh $mesh, IClientService $clients, IL10N $l) {
        $this->l = $l;
        $this->mesh = $mesh;
        $this->clients = $clients;
    }

    /**
     * $pin: the NAS's TLS key pin from its signed mesh record.  With an
     * https address and a pin, the certificate is checked against the pin
     * instead of the certificate authorities (the NAS certificate is
     * self-signed); a different key fails the request.
     */
    public function get(\stdClass $nas, string $path, int $timeout = 30, ?string $pin = null): array {
        [$nid] = $this->mesh->identity();
        $ts = (string)time();
        $nonce = bin2hex(random_bytes(16));
        $sig = $this->mesh->signBytes(implode("\n", ['UTCL1', 'GET', $path, $ts, $nonce, hash('sha256', '')]));
        try {
            $opt = ['headers' => ['Authorization' => "UntrashCloud node=$nid, ts=$ts, nonce=$nonce, sig=$sig"],
                    'timeout' => $timeout, 'verify' => (bool)($nas->verify ?? true), 'http_errors' => false,
                    'nextcloud' => ['allow_local_address' => true]];
            if ($pin !== null && stripos($nas->base, 'https://') === 0) {
                $opt['verify'] = false;
                $opt['curl'] = [CURLOPT_PINNEDPUBLICKEY => $pin];
            }
            $r = $this->clients->newClient()->get(rtrim($nas->base, '/') . $path, $opt);
        } catch (\Exception $e) {
            if (isset($opt['curl']) && strpos($e->getMessage(), 'cURL error 90') !== false) {   // CURLE_SSL_PINNEDPUBKEYNOTMATCH
                throw new MeshException($this->l->t('The HTTPS key at this address is not the one the NAS signed in the mesh. Check the address; if the NAS made a new certificate, wait until its new mesh record has arrived.'));
            }
            throw new MeshException($this->l->t('The NAS is not reachable: %s', [$e->getMessage()]));
        }
        $body = json_decode((string)$r->getBody(), true);
        if ($r->getStatusCode() === 401) {
            throw new MeshException($this->l->t('The NAS refused this Nextcloud: %s', [$body['error'] ?? $this->l->t('not linked there')]));
        }
        if ($r->getStatusCode() !== 200 || !is_array($body)) {
            throw new MeshException($this->l->t('The NAS answered HTTP %s. Is WebDAV on, and is this the address of its WebDAV port?', [$r->getStatusCode()]));
        }
        return $body;
    }
}
