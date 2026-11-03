.PHONY: help test i18n docs-check test-nextcloud

# UntrashOS: the device-independent part.  Images are built by a firmware
# repository (e.g. ZyxelUntrash) that has this repository as a submodule and
# provides the board (docs/board-interface.md).
# BOARD_ROOTFS = <firmware>/board/<name>/rootfs: tests that need board tools.

help:
	@echo "UntrashOS (device-independent part)"
	@echo "  make test         PC tests (no root) [BOARD_ROOTFS=<board>/rootfs]"
	@echo "  make i18n         write design/i18n/*.json from tools/i18n"
	@echo "  make docs-check   privacy check of the docs"
	@echo "  make test-nextcloud APACHEROOT=<dir> [NC_IMAGE=nextcloud:25-apache]"
	@echo "                    the Nextcloud app against a real Nextcloud (Docker, sudo -n)"

i18n:
	python3 tools/i18n/build.py

NC_IMAGE ?= nextcloud:25-apache
test-nextcloud:
	@test -n "$(APACHEROOT)" || { echo "APACHEROOT=<unpacked apache2-bin libapr1 libaprutil1 debs> needed"; exit 1; }
	python3 nextcloud/tests/test_nextcloud_docker.py $(APACHEROOT) $(NC_IMAGE)

docs-check:
	@python3 tools/check_public_docs.py

test:
	ZT_BOARD_ROOTFS=$(BOARD_ROOTFS) $(MAKE) --no-print-directory test-run

test-run:
	python3 image/tests/test_exec_bits.py
	python3 design/tests/test_themes.py
	python3 image/tests/test_live_host.py
	python3 image/tests/test_bootstate.py
	python3 image/tests/test_export_host.py
	python3 image/tests/test_tv_host.py
	python3 image/tests/test_wdt_host.py
	PATH=$$PATH:/usr/sbin python3 image/tests/test_adblock_host.py
	python3 tools/i18n/build.py --check
	python3 image/tests/test_import_zyxel.py
	python3 image/tests/test_untrash_config.py
	python3 image/tests/test-desk-host.py
	python3 image/tests/test-desk-mesh-host.py
	python3 image/tests/test-backup-host.py
	python3 image/tests/test-sound-host.py
	@if command -v node >/dev/null; then node image/tests/test_sound_render.js; else echo "skip sound editor renderer (needs node)"; fi
	@if command -v node >/dev/null; then node image/tests/test_qr.js; else echo "skip QR encoder (needs node)"; fi
	python3 image/tests/test_data_mount.py
	python3 image/tests/test-update-host.py
	python3 image/tests/test-mesh-host.py
	python3 image/tests/test_mesh_endpoints.py
	python3 image/tests/test-cloudlink-host.py
	python3 nextcloud/l10n/build.py --check
