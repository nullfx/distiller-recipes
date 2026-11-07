#!/usr/bin/env python3
"""Validate every recipe and report, then write the index the Distiller app downloads.

    python scripts/build_index.py --check          # validate only (CI on pull requests)
    python scripts/build_index.py --out dist/index.json --repository https://github.com/nullfx/distiller-recipes
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from common import ROOT, SLUG, TIER_SCORE, hardware_key, load_yaml, schema_errors, validator

SCORE_TIER = {score: tier for tier, score in TIER_SCORE.items()}


def summarize(reports: list[dict]) -> dict:
    if not reports:
        return {"reports": 0, "score": None, "tier": None, "median_fps": None}
    score = statistics.mean(TIER_SCORE[r["tier"]] for r in reports)
    fps = [r["fps_avg"] for r in reports if "fps_avg" in r]
    return {
        "reports": len(reports),
        "score": round(score, 2),
        "tier": SCORE_TIER[int(score + 0.5)],
        "median_fps": statistics.median(fps) if fps else None,
    }


def collect(errors: list[str]):
    recipe_validator = validator("recipe.schema.json")
    report_validator = validator("report.schema.json")

    recipes: dict[tuple[str, str], tuple[Path, dict]] = {}
    for path in sorted(ROOT.glob("recipes/*/*")):
        label = str(path.relative_to(ROOT))
        if path.suffix != ".yaml":
            errors.append(f"{label}: recipe files must end in .yaml")
            continue
        data = load_yaml(path)
        found = schema_errors(recipe_validator, data, label)
        errors.extend(found)
        if found:
            continue
        slug, recipe_id = path.parent.name, path.stem
        if data["game"]["slug"] != slug:
            errors.append(f"{label}: game.slug is {data['game']['slug']!r} but the folder is {slug!r}")
        if data["id"] != recipe_id:
            errors.append(f"{label}: id is {data['id']!r} but the file name is {recipe_id!r}")
        recipes[(slug, recipe_id)] = (path, data)

    for (slug, recipe_id), (path, data) in recipes.items():
        parent = data.get("forked_from")
        if parent and tuple(parent.split("/")) not in recipes:
            errors.append(f"{path.relative_to(ROOT)}: forked_from {parent!r} doesn't exist")

    reports: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for path in sorted(ROOT.glob("reports/*/*/*")):
        label = str(path.relative_to(ROOT))
        if path.suffix != ".yaml" or not SLUG.match(path.stem):
            errors.append(f"{label}: report files must be named <lowercase-id>.yaml")
            continue
        data = load_yaml(path)
        found = schema_errors(report_validator, data, label)
        errors.extend(found)
        if found:
            continue
        slug, recipe_id = path.parent.parent.name, path.parent.name
        if (data["game"], data["recipe"]) != (slug, recipe_id):
            errors.append(f"{label}: game/recipe say {data['game']}/{data['recipe']} but the folders say {slug}/{recipe_id}")
            continue
        if (slug, recipe_id) not in recipes:
            errors.append(f"{label}: there's no recipe {slug}/{recipe_id}")
            continue
        reports[(slug, recipe_id)].append(data)

    return recipes, reports


def build_index(recipes, reports, repository: str) -> dict:
    games: dict[str, dict] = {}
    for (slug, recipe_id), (path, data) in sorted(recipes.items()):
        game = games.setdefault(slug, {"slug": slug, "title": data["game"]["title"], "recipes": []})
        recipe_reports = reports.get((slug, recipe_id), [])
        by_hardware: dict[str, list[dict]] = defaultdict(list)
        for report in recipe_reports:
            by_hardware[hardware_key(report["hardware"])].append(report)
        entry = {
            "id": recipe_id,
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "graphics": data["stack"]["graphics"],
            "runner_family": data["stack"]["runner"]["family"],
            "summary": summarize(recipe_reports),
            "by_hardware": {key: summarize(items) for key, items in sorted(by_hardware.items())},
        }
        if "name" in data:
            entry["name"] = data["name"]
        if "forked_from" in data:
            entry["forked_from"] = data["forked_from"]
        game["recipes"].append(entry)

    return {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "repository": repository,
        "games": sorted(games.values(), key=lambda g: g["title"].lower()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate only; write nothing")
    parser.add_argument("--out", default="dist/index.json", help="where to write the index")
    parser.add_argument("--repository", default="https://github.com/nullfx/distiller-recipes")
    args = parser.parse_args()

    errors: list[str] = []
    recipes, reports = collect(errors)
    if errors:
        print(f"{len(errors)} problem(s) found:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    report_count = sum(len(items) for items in reports.values())
    if args.check:
        print(f"OK: {len(recipes)} recipes and {report_count} reports are valid.")
        return 0

    index = build_index(recipes, reports, args.repository)
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out}: {len(index['games'])} games, {len(recipes)} recipes, {report_count} reports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
