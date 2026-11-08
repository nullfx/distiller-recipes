## What this changes

<!-- New recipe, fork, fix to an existing recipe, or a compatibility report. -->

## Checklist

- [ ] `python scripts/build_index.py --check` passes locally.
- [ ] Every `download` step points at an official source (the publisher or a runtime vendor) and has the correct `sha256`.
- [ ] `game.installer.url` is the publisher's official installer (never a mirror or re-hosted copy), and the recipe installs from it.
- [ ] Distiller's community check passed: it installed the game from that installer in a fresh bottle and the game reached its login or menu.
- [ ] Any screenshot in `media/` is my own capture of the game, with nothing personal on screen.
- [ ] I agree to license my contribution under this repository's MIT license. (Pictures in `media/` stay the publisher's; see CONTRIBUTING.)
