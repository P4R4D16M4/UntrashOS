<?php

declare(strict_types=1);

namespace OCA\Untrash\Settings;

use OCP\AppFramework\Http\TemplateResponse;
use OCP\Settings\ISettings;
use OCP\Util;

class Admin implements ISettings {
    public function getForm(): TemplateResponse {
        Util::addScript('untrash', 'admin');
        Util::addStyle('untrash', 'admin');
        return new TemplateResponse('untrash', 'admin');
    }

    public function getSection(): string {
        return 'untrash';
    }

    public function getPriority(): int {
        return 10;
    }
}
