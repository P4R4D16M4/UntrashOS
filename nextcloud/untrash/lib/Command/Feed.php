<?php

declare(strict_types=1);

namespace OCA\Untrash\Command;

use OCA\Untrash\Cloudlink\Feed as FeedService;
use Symfony\Component\Console\Command\Command;
use Symfony\Component\Console\Input\InputInterface;
use Symfony\Component\Console\Input\InputOption;
use Symfony\Component\Console\Output\OutputInterface;

/**
 * The change feed of the linked NAS.  With --once one round (no waiting);
 * without, a loop that long-polls the NAS: run it as a service (systemd) as
 * the web server user for changes within seconds.
 */
class Feed extends Command {
    private FeedService $feed;

    public function __construct(FeedService $feed) {
        parent::__construct();
        $this->feed = $feed;
    }

    protected function configure(): void {
        $this->setName('untrash:feed')->setDescription('Apply the change feed of the linked UntrashOS NAS to the file cache')
            ->addOption('once', null, InputOption::VALUE_NONE, 'one round, then end')
            ->addOption('wait', null, InputOption::VALUE_REQUIRED, 'long poll seconds per round', '60');
    }

    protected function execute(InputInterface $in, OutputInterface $out): int {
        $say = function (string $s) use ($out) {
            $out->writeln($s);
        };
        do {
            $r = $this->feed->run($in->getOption('once') ? 0 : max(1, min(120, (int)$in->getOption('wait'))), $say);
            if ($in->getOption('once')) {
                $out->writeln(json_encode($r, JSON_UNESCAPED_SLASHES));
            }
            if (!$in->getOption('once') && (!$r || array_filter($r, function ($x) {
                return !$x['ok'];
            }))) {
                sleep(30);                    // no NAS with a feed address yet, or one not reachable
            }
        } while (!$in->getOption('once'));
        return 0;
    }
}
