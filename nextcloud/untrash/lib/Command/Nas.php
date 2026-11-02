<?php

declare(strict_types=1);

namespace OCA\Untrash\Command;

use OCA\Untrash\Controller\SettingsController;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputArgument;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Input\InputOption;
use Symfony\Component\Console\Output\OutputInterface;

class Nas extends Command {
    private SettingsController $settings;

    public function __construct(SettingsController $settings) {
        parent::__construct();
        $this->settings = $settings;
    }

    protected function configure(): void {
        $this->setName('untrash:nas')->setDescription('Address of a NAS change feed (http://NAS:5002/untrash-cloudlink)')
            ->addArgument('node', InputArgument::REQUIRED)->addArgument('base', InputArgument::REQUIRED)
            ->addOption('insecure', null, InputOption::VALUE_NONE, 'accept a self-signed HTTPS certificate');
    }

    protected function execute(InputInterface $in, OutputInterface $out): int {
        $r = $this->settings->nas((string)$in->getArgument('node'), (string)$in->getArgument('base'), !$in->getOption('insecure'));
        $out->writeln(json_encode($r->getData(), JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT));
        return $r->getStatus() === 200 ? 0 : 1;
    }
}
