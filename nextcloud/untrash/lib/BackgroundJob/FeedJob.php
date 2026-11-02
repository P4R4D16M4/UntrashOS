<?php

declare(strict_types=1);

namespace OCA\Untrash\BackgroundJob;

use OCA\Untrash\Cloudlink\Feed;
use OCP\AppFramework\Utility\ITimeFactory;
use OCP\BackgroundJob\TimedJob;

/**
 * Every 5 minutes: the changes the NAS collected since the last run.  For
 * changes within seconds run "occ untrash:feed" as a service instead (it
 * long-polls; this job then finds the NAS busy and skips it).
 */
class FeedJob extends TimedJob {
    private Feed $feed;

    public function __construct(ITimeFactory $time, Feed $feed) {
        parent::__construct($time);
        $this->feed = $feed;
        $this->setInterval(300);
    }

    protected function run($argument): void {
        $this->feed->run(0);
    }
}
