# UntrashOS design system

One look for the installer, Untrash Desk and the sign-in page.  It is derived
from three source images in `design/source/`: `untrash-logo.png`,
`untrash-icons.png` and `untrash-wallpaper.png`.  Everything they do not show
(bars, windows, popups, dialogs, forms, sign-in, installer) is built from them.

## Files

| File | Purpose |
|---|---|
| `design/untrash.css` | **single source** of tokens and components (prefix `ut-`) |
| `design/mk-assets.py` | cuts the source images into web assets: app icons (256/128/64 px, round mask), logo, mark, word mark, favicon (colour-to-alpha against `#0d1015`) and wallpaper (full, 960 px, blurred) |
| `design/assets/icons/*.svg` | additional app icons in the style of the set |
| `design/desk.html` | clickable preview of the Desk: top bar, desktop icons, dock, draggable windows, launcher, context menu, notifications, dialogs |
| `design/login.html` | sign-in page |
| `design/styleguide.html` | overview of all components |

Preview on a PC: `python3 -m http.server 8765 --directory design`, then
`http://localhost:8765/desk.html`.

In the image, `image/mkslot-erofs.sh` copies the CSS and a subset of the
assets (about 680 KB) to `/usr/share/untrash/design/`.  The installer serves
them under `/ut/…`: only from that directory, only `.css`, `.png`, `.svg`,
`.jpg` and `.ico`, with a `realpath` check against path traversal.  Without
the directory the page stays usable with a small inline fallback style.

## Principles

1. **Dark only.** The brand has no light variant; `color-scheme: dark`.
2. **Offline and light.** No web fonts, no external requests, no framework.
   System font (`system-ui`), monospace for devices, paths and logs.  The NAS
   is often offline and the Cortex-A9 should parse little.
3. **Sparing accent.** The green → turquoise → cyan gradient marks only the
   primary action, progress, the active selection and the focused window.
   Everything else stays neutral blue-grey.
4. **Foreign data is visibly protected.** Foreign and stock volumes show
   `read only` (warning colour) until the takeover is confirmed.  Destructive
   ways (way A, delete) are red, and their confirm button is
   `ut-btn--danger` instead of primary.
5. **States carry text, not only colour** (pill with dot and word).

## Tokens (excerpt, complete in `untrash.css`)

| Group | Values |
|---|---|
| Surfaces | `--ut-bg-0` `#080b0e` (desktop) · `-1` `#0d1115` (window) · `-2` `#12171c` (cards, sidebars) · `-3` `#181e24` (tiles, fields) · `-4` `#202830` (hover) · `-5` `#2a333c` (pressed) |
| Glass | `--ut-glass` `rgba(13,17,21,.72)` + `backdrop-filter: blur` for top bar, dock, menus, toasts |
| Lines | white at 7 / 12 / 20 % opacity |
| Text | `#e9eef2` · `#aab4bd` · `#6f7b86` |
| Brand (measured in the logo) | lime `#98f56c` · green `#5def6b` · turquoise `#05c7af` (the "OS") · cyan `#00c8c9` · deep cyan `#00a9bc` |
| Gradient | `--ut-grad` `120deg, #6ff06b → #19d6a6 → #00bfd0`; text on it `#04170f` |
| States | ok `#5def6b` · info `#00c8c9` · warn `#f4b54a` · danger `#ff5f6d` (each with a 12–13 % background) |
| Radii | 4 / 7 / 10 / 14 / 20 px; app tiles 19 % of their edge as in the icon set |
| Shadows | deep and soft (`--ut-sh-3` for windows and popups) plus a 1 px top highlight `--ut-hl` as on the tiles |
| Type | 14 px base size in the Desk; 12 / 13 / 16 / 20 / 28 px |

## Components

| Component | Classes | Notes |
|---|---|---|
| Top bar | `ut-topbar`, `__item`, `__title`, `__badge` | 34 px, glass; left the mark + launcher, centre the active app's title, right the tray (RAID state, network, bell, user, clock); a brand hairline below that fades to the right |
| Dock | `ut-dock`, `__item`, `__sep` | bottom centre, glass, 48 px tiles from the icon set; bar under the icon: short = running, long with glow = active.  Power off is always on the right after the separator |
| Desktop icons | `ut-desktop-icons`, `ut-desk-icon` | column grid on the left, selection outlined in turquoise, double-click opens |
| Window | `ut-window`, `__bar`, `__title`, `__ctl`, `__body`, `__main`, `__foot` | 40 px title bar with app icon; the focused window has a 2 px gradient line on top and a turquoise border; close turns red on hover |
| App navigation | `ut-sidebar`, `ut-nav[aria-current]`, `ut-tabs`/`ut-tab` | active page: soft gradient background + gradient bar on the left |
| Launcher | `ut-menu ut-launcher` | app grid with search, opened from the mark |
| Menu / context menu | `ut-menu`, `__item`, `__item--danger`, `__sep`, `__label` | |
| Notification | `ut-toasts` > `ut-toast(--warn/--danger)` | top right under the top bar, app icon left, coloured bar left, optional actions |
| Dialog | `ut-scrim` > `ut-dialog(--danger/--warn)` | dimmed, blurred background; icon badge left; footer with cancel + action |
| Forms | `ut-field`, `ut-input`, `ut-select`, `ut-switch`, `ut-choice` | `ut-choice` is the large choice card with a letter badge (installer ways, RAID levels) |
| Data | `ut-table(-wrap)`, `ut-pill--ok/info/warn/danger/live`, `ut-progress(--warn/--indeterminate)`, `ut-stat`, `ut-steps`, `ut-log`, `ut-callout--*` | |
| Pages without the Desk | `ut-page`, `__head`, `__main` | installer and recovery: header with the brand, 880 px content |
| Sign-in | `ut-login`, `__card`, `__logo`, `__word` | blurred wallpaper, glass card, mark + word mark, host name |

New icons follow the SVG pattern: dark tile with `rx=48` on 256, grey body
with the gradient `#6a737d → #3a4249`, accent in the brand gradient, soft
drop shadow.
