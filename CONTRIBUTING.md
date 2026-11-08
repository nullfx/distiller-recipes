# Contributing recipes and reports

## Reporting how a game ran

Use **Report How It Ran** in the Distiller app. It opens a pre-filled issue here; submit it. A maintainer labels it and a workflow turns it into a pull request. You can also fill in the **Compatibility report** issue form by hand.

## Submitting a recipe from Distiller

The easiest way: in Distiller choose **Create Recipe…**, test the game, then **Submit to Community…**. The app forks this repository to your GitHub account and opens a pull request for you. You need a GitHub account; the app asks for access to public repositories only.

## Writing a recipe by hand

1. If the game is new, add `games/<game-slug>.yaml` (see `schema/game.schema.json` and the examples in `games/`): its title, publisher, a one-paragraph description in your own words, and the official installer link. Recipes' `game.title` and `game.installer.url` must match it.
2. Copy an example from `recipes/` into `recipes/<game-slug>/<recipe-id>.yaml`. The folder name must equal `game.slug`, and the file name must equal `id`.
3. Test it on your own Mac: `distiller recipe validate <file>`, then `distiller install <file>` and `distiller launch <game-id>`.
4. Run `python3 scripts/build_index.py --check`.
5. Open a pull request.

## Pictures

Each game can have an icon, `media/<game-slug>/icon.png` (a square PNG, 32–256 pixels, at most 256 KB), and each recipe up to three screenshots, `media/<game-slug>/<recipe-id>/1.jpg` to `3.jpg` (JPEGs 320–1600 pixels wide, at most 600 KB each; numbered from 1 without gaps; 1 is the cover). The catalogue and the app's Community tab show them. Distiller makes them during the community check: it reads the icon from the installed game's program, and while the game runs a small panel (or ⌃⌥⌘S from inside the game) captures its window whenever it shows something worth sharing (macOS asks once for Screen Recording permission). In the Submit window you pick up to three captures and the cover, and can leave the icon out. A game's icon is added with its first recipe and kept after that; a recipe's screenshots are replaced when the recipe is revised.

Pictures show the publisher's artwork. They're here only to identify the game, they stay the publisher's property, and they aren't covered by this repository's MIT license. Only submit screenshots you captured yourself, of the game itself, with nothing personal on screen (account names, chat). No artwork copied from websites or stores.

To improve someone else's recipe without replacing it, make a fork: a new file with a new `id` and `forked_from: <game-slug>/<recipe-id>`.

## Rules

Recipes are data. They can download files, change the prefix and run Windows programs inside Wine, but they cannot run commands on the Mac. The schema enforces this:

- Paths must start with `cache/`, `drive_c/` or `C:\` and may not contain `..`.
- Downloads must use HTTPS and include a SHA-256 checksum.
- Winetricks verbs must be on the allowlist in `schema/recipe.schema.json`.
- Environment variables are limited to Wine and graphics-layer tuning (`WINE*`, `DXVK_*`, `DXMT_*`, `MTL_*`, `D3DM_*`, `MVK_*`, `VKD3D_*`), excluding the ones that redirect Wine.

Beyond what the schema can check:

- **Official installers only.** A shared recipe installs the game from its publisher's official, publicly available installer, recorded in `game.installer.url`, and downloads nothing else of the game: never a mirror, a re-hosted copy or the game's files. Downloads otherwise are for official patches and runtimes from their publishers. (Players can still use their own copy locally with `user_file` or `user_folder`; Distiller swaps that for the official installer when they share.)
- **Proven before it's shared.** Distiller's community check installs the game from that installer in a fresh bottle, starts it, and asks the contributor whether it reached its login or menu. Distiller only submits recipes that passed, and records the installer's SHA-256. If the publisher replaces the installer, the recipe needs a new check and an updated checksum.
- **Wine is not a sandbox.** Windows programs run with the player's permissions. Only reference installers and patches from sources you trust.
- **Hardware overlays should come from evidence.** Note which Mac you tested an overlay on.

Contributions are licensed under this repository's MIT license, except pictures in `media/` (see above).
