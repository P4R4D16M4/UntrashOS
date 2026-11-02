<?php

declare(strict_types=1);

namespace OCA\Untrash\Controller;

use OCA\Untrash\Mesh\Mesh;
use OCP\AppFramework\Controller;
use OCP\AppFramework\Http\JSONResponse;
use OCP\IRequest;

/** The mesh directory: POST <dir>/v1/sync (cloud-api.md §2). */
class MeshController extends Controller {
    private Mesh $mesh;

    public function __construct(string $appName, IRequest $request, Mesh $mesh) {
        parent::__construct($appName, $request);
        $this->mesh = $mesh;
    }

    /**
     * Members authenticate by their node signature, not by a Nextcloud login.
     *
     * @PublicPage
     * @NoCSRFRequired
     */
    public function sync(): JSONResponse {
        // the raw body: Nextcloud's parsed parameters would turn {} into []
        [$code, $body] = $this->mesh->syncAnswer((string)file_get_contents('php://input'), $this->request->getRemoteAddress());
        return new JSONResponse($body ?? new \stdClass(), $code);
    }
}
