<?php

declare(strict_types=1);

namespace OCA\Untrash\Settings;

use OCP\IURLGenerator;
use OCP\Settings\IIconSection;

class Section implements IIconSection {
    private IURLGenerator $urls;

    public function __construct(IURLGenerator $urls) {
        $this->urls = $urls;
    }

    public function getID(): string {
        return 'untrash';
    }

    public function getName(): string {
        return 'UntrashOS';
    }

    public function getPriority(): int {
        return 90;
    }

    public function getIcon(): string {
        return $this->urls->imagePath('untrash', 'app-dark.svg');
    }
}
