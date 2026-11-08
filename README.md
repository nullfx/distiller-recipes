# distiller-recipes

Community recipes and compatibility reports for [Distiller](https://github.com/nullfx/distiller), a Wine launcher for Windows games on Apple silicon Macs.

A **recipe** says how to install and run one game: which Wine build and graphics layer, which winetricks, registry settings and launch options, and how to adjust them for different Macs. A **report** says how a recipe ran on one Mac. The Distiller app downloads `index.json`, which this repository builds from both, and ranks recipes by how they ran on Macs like yours.

## Layout

| Path | Contents |
| --- | --- |
| `games/<game-slug>.yaml` | One file per game: title, publisher, release year, genres, description, links and its official installer. Every recipe needs one. |
| `recipes/<game-slug>/<recipe-id>.yaml` | One recipe per file. |
| `reports/<game-slug>/<recipe-id>/<report-id>.yaml` | One compatibility report per file. |
| `media/<game-slug>/icon.png` | The game's icon: a square PNG, 32–256 pixels, at most 256 KB. |
| `media/<game-slug>/<recipe-id>/<1-3>.jpg` | Up to three screenshots from the recipe's community check, numbered from 1 (the cover): JPEGs 320–1600 pixels wide, at most 600 KB each. |
| `schema/` | JSON Schemas for games, recipes and reports. |
| `scripts/build_index.py` | Validates everything and writes `dist/index.json` (the catalogue), `dist/games/<slug>.json` (each game in full), `dist/examples.json` (the example games) and `dist/media/` (the listed games' pictures). |
| `scripts/issue_to_report.py` | Turns a report issue into a report file. |
| `scripts/check_pr.py` | Checks that a pull request from a fork only touches games, recipes and reports. |

The `example-*` games show the format and are not real results. They stay in the repository as documentation and are always validated, but the published catalogue (`index.json`, what the app's Community view and the website list) leaves them out once there is a real game. They're published separately as `examples.json`. Until the first real game is merged, the catalogue lists the examples so there is something to show.

## Setting up the repository

1. Create the repository on GitHub and push this folder.
2. In **Settings → Pages**, set the source to **GitHub Actions**. The index is published at `https://nullfx.github.io/distiller-recipes/index.json`.
3. In **Settings → Actions → General**, allow GitHub Actions to create pull requests, so labelled report issues become pull requests.
4. Create a label named `report`.
5. In the Distiller app, set `CommunityRepository.default` to your owner and repository name.
6. So players can submit recipes from the app, create a GitHub OAuth app: **Settings → Developer settings → OAuth Apps → New OAuth App**. Any homepage and callback URL will do (the app doesn't use the callback). Tick **Enable Device Flow**, register it, and put its **Client ID** in `CommunityRepository.default.oauthClientID`. The client ID isn't secret; no client secret is needed or used.
7. Protect `main` with a ruleset (**Settings → Rules → Rulesets**), targeting `main`:
   - **Restrict deletions** and **Block force pushes**.
   - **Require a pull request before merging**: 1 required approval, **Require review from Code Owners** (`.github/CODEOWNERS` names the owner), and **Dismiss stale pull request approvals when new commits are pushed**. Leave "Require approval of the most recent reviewable push" off: with it, nobody can approve a pull request that the owner pushed to.
   - **Require status checks to pass**: `validate` (schema and script tests, `build_index.py --check --check-links`) and `scope` (fork pull requests only touch games, recipes, reports and pictures; it's skipped, which counts as passing, for branches in the repository itself).
   - **Bypass list**: *Repository admin*, set to **For pull requests only**. GitHub never lets you approve your own pull request, so this is how the owner merges their own (including recipes the app submits from a maintainer's account): the merge box offers "Merge without waiting for requirements to be met". Nobody can push to `main` directly.
   - Pull requests opened by the report workflow don't trigger the checks (see below), so they also need the owner's bypass to merge.

## How submissions from the app work

When a player chooses **Submit to Community** in Distiller, the app signs them in to GitHub with a one-time code (the OAuth device flow, `public_repo` scope). A contributor's branch goes in their fork of this repository; a maintainer's (anyone who can push here) goes in this repository directly. The app commits `recipes/<game>/<recipe>.yaml`, the game's `games/<game>.yaml` if it's new, and optionally a report from their Mac, to a new branch named `recipe/<game>/<recipe>` (or `…-update` when revising a published recipe, which only its authors and maintainers may do), and opens a pull request. Nothing is pushed to `main`. Submitting again while the pull request is open adds a commit to it. Only recipes that passed Distiller's community check can be submitted.

Two workflows check every such pull request: **Validate** runs the schema and index checks, and **Contribution scope** fails if a fork changes anything outside `recipes/` and `reports/`, or deletes files. GitHub asks a maintainer to approve workflow runs for first-time contributors (**Settings → Actions → General → Approval for running fork pull request workflows**). After review, merging publishes the recipe in the next index build, and it appears in the app's Community view.

Pull requests opened by the report workflow don't trigger other workflows (a GitHub rule for the built-in token), so that workflow validates the repository itself before opening one.

## Working locally

```sh
python3 -m pip install -r scripts/requirements.txt
python3 scripts/test_scripts.py                 # schema and script tests
python3 scripts/build_index.py --check          # validate every recipe and report
python3 scripts/build_index.py                  # also write dist/index.json
python3 scripts/build_index.py --include-examples   # list the examples even alongside real games
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to write a recipe.
