<?php
// docs/architecture/cloud-api.md: <dir>/v1/sync is the directory of the mesh
return [
    'routes' => [
        ['name' => 'mesh#sync', 'url' => '/mesh/v1/sync', 'verb' => 'POST'],
        ['name' => 'settings#state', 'url' => '/settings/state', 'verb' => 'GET'],
        ['name' => 'settings#join', 'url' => '/settings/join', 'verb' => 'POST'],
        ['name' => 'settings#nas', 'url' => '/settings/nas', 'verb' => 'POST'],
        ['name' => 'settings#test', 'url' => '/settings/test', 'verb' => 'POST'],
        ['name' => 'settings#leave', 'url' => '/settings/leave', 'verb' => 'POST'],
    ],
];
