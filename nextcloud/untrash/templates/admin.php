<?php
/** Admin settings → UntrashOS; filled by js/admin.js from /apps/untrash/settings/state */
/** @var \OCP\IL10N $l */
?>
<div id="untrash-admin" class="section">
	<h2>UntrashMesh</h2>
	<p class="settings-hint"><?php p($l->t('This Nextcloud can join an UntrashMesh, the encrypted network of UntrashOS devices. It keeps the mesh\'s address book at its internet address, so members that lost each other find each other again, and it follows the changes in the shares of a linked NAS, so external storages on that NAS need no scanning.')); ?></p>
	<div id="untrash-body"><p>…</p></div>
	<p id="untrash-msg" class="untrash-msg" role="status"></p>
</div>
