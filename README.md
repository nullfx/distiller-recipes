# distiller-recipes

Community recipes and compatibility reports for [Distiller](https://github.com/YOUR-GITHUB-USER/distiller), a Wine launcher for Windows games on Apple silicon Macs.

A **recipe** says how to install and run one game: which Wine build and graphics layer, which winetricks, registry settings and launch options, and how to adjust them for different Macs. A **report** says how a recipe ran on one Mac. The Distiller app downloads `index.json`, which this repository builds from both, and ranks recipes by how they ran on Macs like yours.

## Layout

| Path | Contents |
| --- | --- |
| `recipes/<game-slug>/<recipe-id>.yaml` | One recipe per file. |
| `reports/<game-slug>/<recipe-id>/<report-id>.yaml` | One compatibility report per file. |
| `schema/` | JSON Schemas for recipes and reports. |
| `scripts/build_index.py` | Validates everything and writes `dist/index.json`. |
| `scripts/issue_to_report.py` | Turns a report issue into a report file. |
| `scripts/check_pr.py` | Checks that a pull request from a fork only touches recipes and reports. |

The `example-*` folders show the format and are not real results. Delete them before you publish.

## Setting up the repository

1. Create the repository on GitHub and push this folder.
2. In **Settings → Pages**, set the source to **GitHub Actions**. The index is published at `https://nullfx.github.io/distiller-recipes/index.json`.
3. In **Settings → Actions → General**, allow GitHub Actions to create pull requests, so labelled report issues become pull requests.
4. Create a label named `report`.
5. In the Distiller app, set `CommunityRepository.default` to your owner and repository name.
6. So players can submit recipes from the app, create a GitHub OAuth app: **Settings → Developer settings → OAuth Apps → New OAuth App**. Any homepage and callback URL will do (the app doesn't use the callback). Tick **Enable Device Flow**, register it, and put its **Client ID** in `CommunityRepository.default.oauthClientID`. The client ID isn't secret; no client secret is needed or used.
7. Protect `main` (**Settings → Branches**): require pull requests, and require the **Validate** and **Contribution scope** checks to pass.

## How submissions from the app work

When a player chooses **Submit to Community** in Distiller, the app signs them in to GitHub with a one-time code (the OAuth device flow, `public_repo` scope), forks this repository to their account, commits `recipes/<game>/<recipe>.yaml` (and, if they choose, a report from their Mac) to a new branch of the fork, and opens a pull request here. Submitting again while the pull request is open adds a commit to the same pull request.

Two workflows check every such pull request: **Validate** runs the schema and index checks, and **Contribution scope** fails if a fork changes anything outside `recipes/` and `reports/`, or deletes files. GitHub asks a maintainer to approve workflow runs for first-time contributors (**Settings → Actions → General → Approval for running fork pull request workflows**). After review, merging publishes the recipe in the next index build, and it appears in the app's Community view.

Pull requests opened by the report workflow don't trigger other workflows (a GitHub rule for the built-in token), so that workflow validates the repository itself before opening one.

## Working locally

```sh
python3 -m pip install -r scripts/requirements.txt
python3 scripts/test_scripts.py                 # schema and script tests
python3 scripts/build_index.py --check          # validate every recipe and report
python3 scripts/build_index.py                  # also write dist/index.json
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to write a recipe.
