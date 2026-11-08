#!/usr/bin/env python3
"""Validate every game, recipe and report, then write what the app and the website read.

    python scripts/build_index.py --check                  # validate only (CI on pull requests)
    python scripts/build_index.py --check --check-links    # also check official installer and website links
    python scripts/build_index.py --out dist/index.json --repository https://github.com/nullfx/distiller-recipes
    python scripts/build_index.py --include-examples --out <tmp>/index.json   # the app's test fixture

Output, next to --out:
    index.json            the catalogue: every game with its details, recipes and rating summaries
    games/<slug>.json     everything for one game: its recipes in full and every report, newest first
    examples.json         the example games (slugs starting "example-"), for the documentation
    media/<slug>/…        each listed game's icon and its recipes' screenshots, copied as they are

The example games are always validated, but the catalogue (the hub) lists only real games. Until
the repository has one, it lists the examples so the app and the website have something to show.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import statistics
import struct
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

from common import ROOT, SLUG, TIER_SCORE, hardware_key, load_yaml, schema_errors, validator

SCORE_TIER = {score: tier for tier, score in TIER_SCORE.items()}
INDEX_SCHEMA = 2
# Catalogue fields copied from games/<slug>.yaml into index.json.
GAME_FIELDS = ["publisher", "developer", "release_year", "genres", "description", "website", "stores", "installer"]


# Pictures: media/<slug>/icon.png (the game's icon) and media/<slug>/<recipe-id>/<n>.jpg (up
# to three screenshots from the recipe's community check, numbered from 1 without gaps; 1 is
# the cover). The Distiller app makes them within these limits (CommunityMedia.swift); keep
# the two in sync.
ICON_MIN, ICON_MAX, ICON_MAX_BYTES = 32, 256, 256 * 1024
SCREENSHOT_MIN_WIDTH, SCREENSHOT_MAX_WIDTH, SCREENSHOT_MAX_BYTES = 320, 1600, 600 * 1024
MAX_SCREENSHOTS = 3
MEDIA_LAYOUT = "pictures go in media/<game-slug>/icon.png or media/<game-slug>/<recipe-id>/<1-3>.jpg"


def image_size(data: bytes) -> tuple[str, int, int] | None:
    """("png" | "jpeg", width, height) read from the file's header, or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                return None
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            # Start-of-frame markers carry the size; C4, C8 and CC are other tables.
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return "jpeg", width, height
            i += 2 + length
    return None


def collect_media(games: dict[str, dict], recipes, errors: list[str]) -> dict[str, dict]:
    """Returns {slug: {"icon": path or None, "screenshots": {recipe_id: [paths, cover first]}}}
    for valid pictures."""
    media: dict[str, dict] = {}
    numbered: dict[tuple[str, str], dict[int, str]] = defaultdict(dict)
    for path in sorted(ROOT.glob("media/**/*")):
        if path.is_dir() or path.name.startswith("."):
            continue
        rel = path.relative_to(ROOT)
        label = str(rel).replace("\\", "/")
        parts = rel.parts
        is_icon = len(parts) == 3 and parts[2] == "icon.png"
        is_screenshot = len(parts) == 4 and SLUG.match(parts[2]) and parts[3] in {f"{n}.jpg" for n in range(1, MAX_SCREENSHOTS + 1)}
        if not SLUG.match(parts[1] if len(parts) > 1 else "") or not (is_icon or is_screenshot):
            errors.append(f"{label}: {MEDIA_LAYOUT}")
            continue
        slug = parts[1]
        if slug not in games:
            errors.append(f"{label}: there's no games/{slug}.yaml")
            continue
        data = path.read_bytes()
        found = image_size(data)
        entry = media.setdefault(slug, {"icon": None, "screenshots": {}})
        if is_icon:
            if found is None or found[0] != "png":
                errors.append(f"{label}: the icon must be a PNG file")
            elif found[1] != found[2] or not ICON_MIN <= found[1] <= ICON_MAX:
                errors.append(f"{label}: the icon must be square, {ICON_MIN} to {ICON_MAX} pixels a side (it's {found[1]}x{found[2]})")
            elif len(data) > ICON_MAX_BYTES:
                errors.append(f"{label}: the icon must be at most {ICON_MAX_BYTES // 1024} KB")
            else:
                entry["icon"] = label
        else:
            recipe_id, number = parts[2], int(parts[3][:-4])
            if (slug, recipe_id) not in recipes:
                errors.append(f"{label}: there's no recipe {slug}/{recipe_id} for this screenshot")
            elif found is None or found[0] != "jpeg":
                errors.append(f"{label}: the screenshot must be a JPEG file")
            elif not SCREENSHOT_MIN_WIDTH <= found[1] <= SCREENSHOT_MAX_WIDTH or not 0 < found[2] <= found[1] * 2:
                errors.append(f"{label}: the screenshot must be {SCREENSHOT_MIN_WIDTH} to {SCREENSHOT_MAX_WIDTH} pixels wide (it's {found[1]}x{found[2]})")
            elif len(data) > SCREENSHOT_MAX_BYTES:
                errors.append(f"{label}: the screenshot must be at most {SCREENSHOT_MAX_BYTES // 1024} KB")
            else:
                numbered[(slug, recipe_id)][number] = label
    for (slug, recipe_id), shots in sorted(numbered.items()):
        if sorted(shots) != list(range(1, len(shots) + 1)):
            errors.append(f"media/{slug}/{recipe_id}/: screenshots must be numbered from 1.jpg without gaps (found {', '.join(f'{n}.jpg' for n in sorted(shots))})")
            continue
        media[slug]["screenshots"][recipe_id] = [shots[n] for n in sorted(shots)]
    return media


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


EXAMPLE_PREFIX = "example-"


def is_example(slug: str) -> bool:
    return slug.startswith(EXAMPLE_PREFIX)


def split_examples(games_info: dict[str, dict], recipes, reports, include_examples: bool = False):
    """Returns (catalogue, examples), each a (games, recipes, reports) triple. The catalogue
    leaves the examples out once there is a real game, unless include_examples is set."""
    def only(keep):
        return (
            {slug: info for slug, info in games_info.items() if keep(slug)},
            {key: value for key, value in recipes.items() if keep(key[0])},
            {key: value for key, value in reports.items() if keep(key[0])},
        )
    has_real_game = any(not is_example(slug) for slug in games_info)
    examples = only(is_example)
    if include_examples or not has_real_game:
        return (games_info, recipes, reports), examples
    return only(lambda slug: not is_example(slug)), examples


def build_index(games_info: dict[str, dict], recipes, reports, repository: str, media: dict[str, dict] | None = None) -> tuple[dict, dict[str, dict]]:
    """Returns index.json and the per-game detail files. Picture paths are relative to the
    index, where main() copies them."""
    media = media or {}
    games: dict[str, dict] = {}
    details: dict[str, dict] = {}
    for (slug, recipe_id), (path, data) in sorted(recipes.items()):
        info = games_info[slug]
        game = games.get(slug)
        if game is None:
            game = {"slug": slug, "title": info["title"]}
            game.update({key: info[key].strip() if isinstance(info[key], str) else info[key] for key in GAME_FIELDS if key in info})
            game["detail"] = f"games/{slug}.json"
            if media.get(slug, {}).get("icon"):
                game["icon"] = media[slug]["icon"]
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
        screenshots = media.get(slug, {}).get("screenshots", {}).get(recipe_id)
        if screenshots:
            entry["screenshots"] = screenshots
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
    parser.add_argument("--include-examples", action="store_true", help="list the example games in index.json even when there are real ones")
    args = parser.parse_args()

    errors: list[str] = []
    games, recipes, reports = collect(errors)
    media = collect_media(games, recipes, errors)
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

    catalogue, examples = split_examples(games, recipes, reports, args.include_examples)
    index, details = build_index(*catalogue, args.repository, media)
    example_index, _ = build_index(*examples, args.repository, media)
    out = Path(args.out)
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out.parent / "examples.json").write_text(json.dumps(example_index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out.parent / "games").mkdir(exist_ok=True)
    for slug, detail in details.items():
        (out.parent / "games" / f"{slug}.json").write_text(json.dumps(detail, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pictures = {
        path
        for listing in (index, example_index)
        for game in listing["games"]
        for path in [game.get("icon")] + [shot for recipe in game["recipes"] for shot in recipe.get("screenshots", [])]
        if path
    }
    for path in sorted(pictures):
        (out.parent / path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, out.parent / path)
    left_out = len(games) - len(catalogue[0])
    note = f" ({left_out} example game(s) left out; see examples.json)" if left_out else ""
    print(f"Wrote {out} and {len(details)} game files: {len(index['games'])} games, {len(catalogue[1])} recipes, "
          f"{sum(len(items) for items in catalogue[2].values())} reports, {len(pictures)} pictures{note}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
