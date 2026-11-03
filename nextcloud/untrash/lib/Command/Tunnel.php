<?php

declare(strict_types=1);

namespace OCA\Untrash\Command;

use OCA\Untrash\Mesh\Mesh;
use OCA\Untrash\Mesh\MeshException;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputArgument;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Input\InputOption;
use Symfony\Component\Console\Output\OutputInterface;

/**
 * The interface between this app and the root helper untrash-cloud-wg
 * (cloud-api.md §4), which runs the WireGuard interface of this server.
 *
 *   untrash:tunnel sync --key K --endpoint IP:51820 [--handshakes JSON]
 *       one round of the helper: key and endpoints into this cloud's record,
 *       the peers back (JSON)
 *   untrash:tunnel off    no tunnel any more (record without key)
 */
class Tunnel extends Command {
    private Mesh $mesh;

    public function __construct(Mesh $mesh) {
        parent::__construct();
        $this->mesh = $mesh;
    }

    protected function configure(): void {
        $this->setName('untrash:tunnel')->setDescription('WireGuard tunnel of this server into the mesh (for untrash-cloud-wg)')
            ->addArgument('action', InputArgument::REQUIRED, 'sync | off')
            ->addOption('key', null, InputOption::VALUE_REQUIRED, 'WireGuard public key of this server', '')
            ->addOption('endpoint', null, InputOption::VALUE_REQUIRED | InputOption::VALUE_IS_ARRAY, 'public IP:port', [])
            ->addOption('handshakes', null, InputOption::VALUE_REQUIRED, 'JSON {peer key: last handshake}', '{}');
    }

    protected function execute(InputInterface $in, OutputInterface $out): int {
        $action = (string)$in->getArgument('action');
        try {
            if ($action === 'off') {
                $r = $this->mesh->tunnelSync('', [], []);
            } elseif ($action === 'sync') {
                $hs = json_decode((string)$in->getOption('handshakes'), true);
                $r = $this->mesh->tunnelSync((string)$in->getOption('key'), (array)$in->getOption('endpoint'), is_array($hs) ? $hs : []);
            } else {
                $out->writeln('<error>action: sync or off</error>');
                return 2;
            }
        } catch (MeshException $e) {
            $out->writeln(json_encode(['error' => $e->getMessage()]));
            return 1;
        }
        $out->writeln(json_encode($r, JSON_UNESCAPED_SLASHES));
        return 0;
    }
}
