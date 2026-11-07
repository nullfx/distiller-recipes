#!/usr/bin/env python3
"""Turn a report issue (from .github/ISSUE_TEMPLATE/report.yml) into a report file.

Reads the GitHub event JSON, validates the fields, and writes
reports/<game>/<recipe>/issue-<number>.yaml. Prints the path and, inside GitHub Actions,
sets the step output `path`. The issue body is untrusted: it is parsed as data and
validated against the schema before any of it is used in a file path.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys

import yaml

from common import ROOT, SLUG, schema_errors, validator

# Issue form labels → report fields. Keep in sync with .github/ISSUE_TEMPLATE/report.yml.
LABELS = {
    "Game slug": "game_slug",
    "Recipe ID": "recipe_id",
    "Playability": "tier",
    "Average FPS": "fps_avg",
    "Chip": "chip",
    "Chip family": "chip_family",
    "Chip tier": "chip_tier",
    "GPU cores": "gpu_cores",
    "Memory (GB)": "memory_gb",
    "macOS version": "macos",
    "Rosetta available": "rosetta",
    "Wine build": "wine_version",
    "Graphics layer": "graphics_version",
    "Notes": "notes",
}


def parse_form(body: str) -> dict[str, str]:
    """Issue forms render as '### Label' followed by the answer."""
    fields: dict[str, str] = {}
    for section in re.split(r"^### ", body or "", flags=re.MULTILINE)[1:]:
        label, _, value = section.partition("\n")
        key = LABELS.get(label.strip())
        value = value.strip()
        if key and value and value != "_No response_":
            fields[key] = value
    return fields


def to_int(value: str | None):
    try:
        return int(float(value)) if value is not None else None
    except ValueError:
        return value  # leave it for the schema to reject with a clear message


def build_report(fields: dict[str, str], number: int, created_at: str) -> dict:
    hardware = {
        "chip": fields.get("chip"),
        "chip_family": fields.get("chip_family"),
        "chip_tier": fields.get("chip_tier"),
        "memory_gb": to_int(fields.get("memory_gb")),
        "macos": fields.get("macos"),
        "rosetta": fields.get("rosetta") == "true",
    }
    if "gpu_cores" in fields:
        hardware["gpu_cores"] = to_int(fields["gpu_cores"])
    report = {
        "schema": 1,
        "game": fields.get("game_slug"),
        "recipe": fields.get("recipe_id"),
        "tier": fields.get("tier"),
        "hardware": hardware,
        "date": created_at[:10],
        "issue": number,
    }
    if "fps_avg" in fields:
        try:
            report["fps_avg"] = float(fields["fps_avg"])
        except ValueError:
            report["fps_avg"] = fields["fps_avg"]
    components = {k: fields[f"{k}_version"] for k in ("wine", "graphics") if f"{k}_version" in fields}
    if components:
        report["components"] = components
    if "notes" in fields:
        report["notes"] = fields["notes"][:2000]
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event", required=True, help="path to the GitHub event JSON")
    args = parser.parse_args()

    with open(args.event, encoding="utf-8") as handle:
        issue = json.load(handle)["issue"]
    created = issue.get("created_at") or dt.datetime.now(dt.timezone.utc).isoformat()
    report = build_report(parse_form(issue.get("body", "")), int(issue["number"]), created)

    errors = schema_errors(validator("report.schema.json"), report, f"issue #{issue['number']}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1

    game, recipe = report["game"], report["recipe"]
    assert SLUG.match(game) and SLUG.match(recipe)  # guaranteed by the schema; checked again before use in a path
    if not (ROOT / "recipes" / game / f"{recipe}.yaml").exists():
        print(f"issue #{issue['number']}: there's no recipe {game}/{recipe}", file=sys.stderr)
        return 1

    path = ROOT / "reports" / game / recipe / f"issue-{issue['number']}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(report, sort_keys=False, allow_unicode=True), encoding="utf-8")
    relative = str(path.relative_to(ROOT))
    print(relative)
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"path={relative}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
