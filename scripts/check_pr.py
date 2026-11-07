#!/usr/bin/env python3
"""Check that a pull request from a fork only adds or changes games, recipes and reports.

    python scripts/check_pr.py --base origin/main

Pull requests opened from the Distiller app come from the player's fork and should touch
nothing but games/<game>.yaml, recipes/<game>/<recipe>.yaml and reports/<game>/<recipe>/<report>.yaml. Anything
else (scripts, workflows, the schema) needs a maintainer. The content itself is validated
by build_index.py in the Validate workflow.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

GAME = re.compile(r"^games/[a-z0-9][a-z0-9-]{1,63}\.yaml$")
RECIPE = re.compile(r"^recipes/[a-z0-9][a-z0-9-]{1,63}/[a-z0-9][a-z0-9-]{1,63}\.yaml$")
REPORT = re.compile(r"^reports/[a-z0-9][a-z0-9-]{1,63}/[a-z0-9][a-z0-9-]{1,63}/[a-z0-9][a-z0-9-]{1,63}\.yaml$")


def problems(changes: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """Returns (errors, notices) for (status, path) pairs from `git diff --name-status`."""
    errors: list[str] = []
    notices: list[str] = []
    for status, path in changes:
        kind = status[:1]
        if not (GAME.match(path) or RECIPE.match(path) or REPORT.match(path)):
            errors.append(f"{path}: contributions from forks may only change games/, recipes/ and reports/ YAML files.")
        elif kind == "D":
            errors.append(f"{path}: contributions from forks can't delete files. Ask a maintainer.")
        elif kind not in ("A", "M"):
            errors.append(f"{path}: unexpected change type {status}.")
        elif kind == "M" and RECIPE.match(path):
            notices.append(f"{path}: changes an existing recipe. Check that its authors agree, or ask for a fork with forked_from.")
        elif kind == "M" and GAME.match(path):
            notices.append(f"{path}: changes an existing game's details. Check the official installer link especially.")
    return errors, notices


def changed_files(base: str) -> list[tuple[str, str]]:
    output = subprocess.run(
        ["git", "diff", "--name-status", "--no-renames", f"{base}...HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout
    changes = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            changes.append((parts[0], parts[-1]))
    return changes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="the branch the pull request targets, such as origin/main")
    args = parser.parse_args()

    changes = changed_files(args.base)
    errors, notices = problems(changes)
    for notice in notices:
        print(f"::warning::{notice}")
    for error in errors:
        print(f"::error::{error}")
    if errors:
        return 1
    print(f"OK: {len(changes)} changed file(s), all games, recipes or reports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
