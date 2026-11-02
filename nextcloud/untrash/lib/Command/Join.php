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

class Join extends Command {
    private Mesh $mesh;

    public function __construct(Mesh $mesh) {
        parent::__construct();
        $this->mesh = $mesh;
    }

    protected function configure(): void {
        $this->setName('untrash:join')->setDescription('Join an UntrashMesh with a cloud invitation (NAS: UntrashMesh → Connect a Nextcloud)')
            ->addArgument('invitation', InputArgument::REQUIRED)
            ->addOption('name', null, InputOption::VALUE_REQUIRED, 'name of this Nextcloud in the mesh', 'nextcloud');
    }

    protected function execute(InputInterface $in, OutputInterface $out): int {
        try {
            $out->writeln(json_encode($this->mesh->join((string)$in->getArgument('invitation'), (string)$in->getOption('name')),
                                      JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT));
            return 0;
        } catch (MeshException $e) {
            $out->writeln('<error>' . $e->getMessage() . '</error>');
            return 1;
        }
    }
}
