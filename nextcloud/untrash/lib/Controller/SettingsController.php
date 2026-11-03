<?php

declare(strict_types=1);

namespace OCA\Untrash\Controller;

use OCA\Untrash\Cloudlink\Client;
use OCA\Untrash\Mesh\Mesh;
use OCA\Untrash\Mesh\MeshException;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http\JSONResponse;
use OCP\IL10N;
use OCP\IRequest;
use OCP\IURLGenerator;

/** Admin settings → UntrashOS (admins only: no @NoAdminRequired). */
class SettingsController extends Controller {
    private Mesh $mesh;
    private Client $client;
    private IURLGenerator $urls;
    private IL10N $l;

    public function __construct(string $appName, IRequest $request, Mesh $mesh, Client $client, IURLGenerator $urls,
                                IL10N $l) {
        $this->l = $l;
        parent::__construct($appName, $request);
        $this->mesh = $mesh;
        $this->client = $client;
        $this->urls = $urls;
    }

    private function wrap(callable $fn): JSONResponse {
        try {
            return new JSONResponse($fn());
        } catch (MeshException $e) {
            return new JSONResponse(['error' => $e->getMessage()], 400);
        }
    }

    public function state(): JSONResponse {
        return $this->wrap(function () {
            return $this->mesh->status();
        });
    }

    public function join(string $invitation = '', string $name = ''): JSONResponse {
        return $this->wrap(function () use ($invitation, $name) {
            return $this->mesh->join($invitation, $name !== '' ? $name : (string)parse_url($this->urls->getAbsoluteURL('/'), PHP_URL_HOST));
        });
    }

    /** The address of a NAS's change feed (its WebDAV port). */
    public function nas(string $node = '', string $base = '', bool $verify = true): JSONResponse {
        return $this->wrap(function () use ($node, $base, $verify) {
            if (!preg_match('#^https?://[^\s/?\#]+(/[^\s?\#]*)?$#', $base)) {
                throw new MeshException($this->l->t('Enter the address as http://NAS:5002/untrash-cloudlink or https://NAS:5003/untrash-cloudlink.'));
            }
            $this->mesh->locked(function () use ($node, $base, $verify) {
                $st = $this->mesh->load('mesh.json', null);
                if (!isset(Mesh::members($st->roster ?? null)[$node])) {
                    throw new MeshException($this->l->t('Unknown member.'));
                }
                $all = $this->mesh->load('nas.json', new \stdClass());
                $old = $all->$node ?? null;
                $all->$node = (object)['base' => rtrim($base, '/'), 'verify' => $verify,
                                       'cursor' => ($old && $old->base === rtrim($base, '/')) ? $old->cursor : ''];
                $this->mesh->save('nas.json', $all);
            });
            return $this->mesh->status();
        });
    }

    public function test(string $node = ''): JSONResponse {
        return $this->wrap(function () use ($node) {
            $nas = $this->mesh->load('nas.json', new \stdClass())->$node ?? null;
            if (!$nas) {
                throw new MeshException($this->l->t('No address for this NAS yet.'));
            }
            return $this->client->get($nas, '/v1/info', 15, $this->mesh->tlsPin($node));
        });
    }

    public function leave(): JSONResponse {
        return $this->wrap(function () {
            $this->mesh->leave();
            return $this->mesh->status();
        });
    }
}
