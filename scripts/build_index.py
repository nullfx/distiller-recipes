#!/usr/bin/env python3
"""Validate every game, recipe and report, then write what the app and the website read.

    python scripts/build_index.py --check                  # validate only (CI on pull requests)
    python scripts/build_index.py --check --check-links    # also check official installer and website links
    python scripts/build_index.py --out dist/index.json --repository https://github.com/nullfx/distiller-recipes

Output, next to --out:
    index.json            the catalogue: every game with its details, recipes and rating summaries
    games/<slug>.json     everything for one game: its recipes in full and every report, newest first
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

from common import ROOT, SLUG, TIER_SCORE, hardware_key, load_yaml, schema_errors, validator

SCORE_TIER = {score: tier for tier, score in TIER_SCORE.items()}
INDEX_SCHEMA = 2
# Catalogue fields copied from games/<slug>.yaml into index.json.
GAME_FIELDS = ["publisher", "developer", "release_year", "genres", "description", "website", "stores", "installer"]


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


def collect_games(errors: list[str]) -> dict[str, dict]:
    game_validator = validator("game.schema.json")
    games: dict[str, dict] = {}
    for path in sorted(ROOT.glob("games/*")):
        label = str(path.relative_to(ROOT))
        if path.suffix != ".yaml" or not SLUG.match(path.stem):
            errors.append(f"{label}: game files must be named games/<lowercase-slug>.yaml")
            continue
        data = load_yaml(path)
        found = schema_errors(game_validator, data, label)
        errors.extend(found)
        if found:
            continue
        if data["slug"] != path.stem:
            errors.append(f"{label}: slug is {data['slug']!r} but the file name is {path.stem!r}")
            continue
        games[path.stem] = data
    return games


def collect(errors: list[str]):
    recipe_validator = validator("recipe.schema.json")
    report_validator = validator("report.schema.json")
    games = collect_games(errors)

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
        game = games.get(slug)
        if game is None:
            errors.append(f"{label}: there's no games/{slug}.yaml; add the game with its first recipe")
        else:
            if data["game"]["title"] != game["title"]:
                errors.append(f"{label}: game.title {data['game']['title']!r} differs from games/{slug}.yaml ({game['title']!r})")
            recipe_installer = data["game"].get("installer", {}).get("url")
            game_installer = game.get("installer", {}).get("url")
            if recipe_installer and recipe_installer != game_installer:
                errors.append(f"{label}: game.installer.url isn't the official installer in games/{slug}.yaml")
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

    for slug in sorted(set(games) - {slug for slug, _ in recipes}):
        errors.append(f"games/{slug}.yaml: the game has no recipes yet; add it together with its first recipe")

    return games, recipes, reports


def check_links(games: dict[str, dict], errors: list[str]) -> None:
    """Checks that each game's official installer and website still answer (HEAD, then a 1-byte GET)."""
    for slug, game in sorted(games.items()):
        for what, url in [("installer.url", game.get("installer", {}).get("url")), ("website", game.get("website"))]:
            if not url:
                continue
            status = None
            for method, headers in [("HEAD", {}), ("GET", {"Range": "bytes=0-0"})]:
                request = urllib.request.Request(url, method=method, headers={"User-Agent": "distiller-recipes-ci", **headers})
                try:
                    with urllib.request.urlopen(request, timeout=20) as response:
                        status = response.status
                except Exception as error:  # noqa: BLE001 - any failure means the link doesn't work
                    status = getattr(error, "code", None) or str(error)
                if isinstance(status, int) and status < 400:
                    break
            if not (isinstance(status, int) and status < 400):
                errors.append(f"games/{slug}.yaml: {what} {url} doesn't answer ({status})")


def build_index(games_info: dict[str, dict], recipes, reports, repository: str) -> tuple[dict, dict[str, dict]]:
    """Returns index.json and the per-game detail files."""
    games: dict[str, dict] = {}
    details: dict[str, dict] = {}
    for (slug, recipe_id), (path, data) in sorted(recipes.items()):
        info = games_info[slug]
        game = games.get(slug)
        if game is None:
            game = {"slug": slug, "title": info["title"]}
            game.update({key: info[key].strip() if isinstance(info[key], str) else info[key] for key in GAME_FIELDS if key in info})
            game["detail"] = f"games/{slug}.json"
            game["recipes"] = []
            games[slug] = game
            details[slug] = {"schema": INDEX_SCHEMA, "repository": repository, **{k: v for k, v in game.items() if k != "recipes"}, "recipes": []}
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
        newest_first = sorted(recipe_reports, key=lambda r: r["date"], reverse=True)
        details[slug]["recipes"].append({
            **entry,
            "recipe": data,
            "reports": [{**report, "hardware_key": hardware_key(report["hardware"])} for report in newest_first],
        })

    for slug, game in games.items():
        all_reports = [r for (s, _), items in reports.items() if s == slug for r in items]
        game["summary"] = summarize(all_reports)
        game["graphics"] = sorted({recipe["graphics"] for recipe in game["recipes"]})
        game["updated"] = max((r["date"] for r in all_reports), default=None)
        details[slug]["summary"] = game["summary"]

    generated = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for detail in details.values():
        detail["generated_at"] = generated
    index = {
        "schema": INDEX_SCHEMA,
        "generated_at": generated,
        "repository": repository,
        "games": sorted(games.values(), key=lambda g: g["title"].lower()),
    }
    return index, details


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate only; write nothing")
    parser.add_argument("--out", default="dist/index.json", help="where to write the index")
    parser.add_argument("--repository", default="https://github.com/nullfx/distiller-recipes")
    parser.add_argument("--check-links", action="store_true", help="also check that official installer and website links answer")
    args = parser.parse_args()

    errors: list[str] = []
    games, recipes, reports = collect(errors)
    if args.check_links and not errors:
        check_links(games, errors)
    if errors:
        print(f"{len(errors)} problem(s) found:", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    report_count = sum(len(items) for items in reports.values())
    if args.check:
        print(f"OK: {len(games)} games, {len(recipes)} recipes and {report_count} reports are valid.")
        return 0

    index, details = build_index(games, recipes, reports, args.repository)
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out.parent / "games").mkdir(exist_ok=True)
    for slug, detail in details.items():
        (out.parent / "games" / f"{slug}.json").write_text(json.dumps(detail, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {out} and {len(details)} game files: {len(index['games'])} games, {len(recipes)} recipes, {report_count} reports.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
