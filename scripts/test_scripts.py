#!/usr/bin/env python3
"""Tests for the schemas and scripts. Run: python scripts/test_scripts.py"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_index  # noqa: E402
import check_pr  # noqa: E402
import issue_to_report  # noqa: E402
from common import ROOT, hardware_key, load_yaml, validator  # noqa: E402

BASE = load_yaml(ROOT / "recipes/example-dx11-game/d3dmetal.yaml")


def recipe_errors(data) -> list:
    return list(validator("recipe.schema.json").iter_errors(data))


def with_change(change):
    data = copy.deepcopy(BASE)
    change(data)
    return data


class RecipeSchemaTests(unittest.TestCase):
    def test_sample_is_valid(self):
        self.assertEqual(recipe_errors(BASE), [])

    def test_rejects_host_code_injection_through_env(self):
        for key in ["DYLD_INSERT_LIBRARIES", "PATH", "WINEDLLPATH", "WINEPREFIX", "WINELOADER", "WINEDLLOVERRIDES"]:
            with self.subTest(key=key):
                self.assertTrue(recipe_errors(with_change(lambda d: d["env"].update({key: "x"}))))

    def test_allows_tuning_env(self):
        for key in ["WINEMSYNC", "DXMT_CONFIG", "MTL_HUD_ENABLED", "D3DM_SUPPORT_DXR", "DXVK_HUD"]:
            with self.subTest(key=key):
                self.assertEqual(recipe_errors(with_change(lambda d: d["env"].update({key: "1"}))), [])

    def test_rejects_paths_outside_the_bottle(self):
        for path in ["/etc/hosts", "../escape.exe", "cache/../../x", "D:\\game.exe", "~/x", "drive_c/../x", "Z:/x"]:
            with self.subTest(path=path):
                self.assertTrue(recipe_errors(with_change(lambda d: d["launch"].update({"exe": path}))))

    def test_accepts_bottle_paths(self):
        for path in ["C:\\Games\\a.exe", "c:/Games/a.exe", "drive_c/Games/a.exe", "cache/setup.exe"]:
            with self.subTest(path=path):
                self.assertEqual(recipe_errors(with_change(lambda d: d["launch"].update({"exe": path}))), [])

    def test_downloads_need_https_and_checksum(self):
        http = {"download": {"url": "http://example.com/a.zip", "sha256": "0" * 64, "to": "cache/a.zip"}}
        no_sum = {"download": {"url": "https://example.com/a.zip", "to": "cache/a.zip"}}
        for step in [http, no_sum]:
            with self.subTest(step=step):
                self.assertTrue(recipe_errors(with_change(lambda d: d["install"].append(step))))

    def test_installers_that_update_are_checked_by_signature_in_schema_2(self):
        url = "https://downloads.example.com/getInstaller?os=win"
        signed = {"download": {"url": url, "signer": "Example Publisher, Inc.", "to": "cache/Setup.exe"}}

        def signed_recipe(schema, step=signed, updates=True):
            def change(d):
                d["schema"] = schema
                d["game"]["installer"] = {"url": url, **({"updates": True} if updates else {})}
                d["install"] = [step]
            return with_change(change)

        self.assertEqual(recipe_errors(signed_recipe(2)), [])
        self.assertTrue(recipe_errors(signed_recipe(1)), "Schema 1 can't use a signer")
        self.assertTrue(recipe_errors(signed_recipe(1, step={"download": {"url": url, "sha256": "0" * 64, "to": "cache/Setup.exe"}})),
                        "or an installer that updates")
        self.assertEqual(recipe_errors(signed_recipe(1, step={"download": {"url": url, "sha256": "0" * 64, "to": "cache/Setup.exe"}}, updates=False)), [])
        both = {"download": {"url": url, "sha256": "0" * 64, "signer": "Example Publisher, Inc.", "to": "cache/Setup.exe"}}
        for step in [both, {"download": {"url": url, "signer": " Padded", "to": "cache/Setup.exe"}}, {"download": {"url": url, "signer": "", "to": "cache/Setup.exe"}}]:
            with self.subTest(step=step):
                self.assertTrue(recipe_errors(signed_recipe(2, step=step)))
        self.assertTrue(recipe_errors(with_change(lambda d: d.update({"schema": 3}))))

    def test_rejects_shell_steps_and_unknown_verbs(self):
        self.assertTrue(recipe_errors(with_change(lambda d: d["install"].append({"shell": "rm -rf ~"}))))
        self.assertTrue(recipe_errors(with_change(lambda d: d["prefix"].update({"winetricks": ["sandbox"]}))))

    def test_step_must_have_one_key(self):
        two = {"copy": {"from": "cache/a", "to": "cache/b"}, "winetricks": ["xact"]}
        self.assertTrue(recipe_errors(with_change(lambda d: d["install"].append(two))))


class UserFolderTests(unittest.TestCase):
    def step(self, to):
        return {"user_folder": {"id": "game-folder", "prompt": "Choose the game folder", "to": to}}

    def test_accepts_folders_on_drive_c(self):
        for to in ["C:\\Games\\Example", "c:/Games/Example", "drive_c/Games/Example"]:
            with self.subTest(to=to):
                self.assertEqual(recipe_errors(with_change(lambda d: d["install"].append(self.step(to)))), [])

    def test_rejects_other_places(self):
        for to in ["C:\\", "C:\\windows\\system32", "drive_c/Windows", "cache/game", "D:\\Games", "C:\\Games\\..\\windows"]:
            with self.subTest(to=to):
                self.assertTrue(recipe_errors(with_change(lambda d: d["install"].append(self.step(to)))))


class ContributionScopeTests(unittest.TestCase):
    def test_allows_recipes_and_reports(self):
        errors, notices = check_pr.problems([
            ("A", "recipes/my-game/d3dmetal.yaml"),
            ("A", "reports/my-game/d3dmetal/octocat-20261106.yaml"),
        ])
        self.assertEqual((errors, notices), ([], []))

    def test_flags_edits_to_existing_recipes(self):
        errors, notices = check_pr.problems([("M", "recipes/my-game/d3dmetal.yaml")])
        self.assertEqual(errors, [])
        self.assertEqual(len(notices), 1)

    def test_rejects_everything_else(self):
        for change in [
            ("M", ".github/workflows/validate.yml"),
            ("M", "schema/recipe.schema.json"),
            ("A", "recipes/my-game/run.sh"),
            ("A", "recipes/../scripts/x.yaml"),
            ("D", "recipes/my-game/d3dmetal.yaml"),
        ]:
            with self.subTest(change=change):
                errors, _ = check_pr.problems([change])
                self.assertTrue(errors)


class IndexTests(unittest.TestCase):
    def test_hardware_key_matches_app_format(self):
        hardware = {"chip_family": "M3", "chip_tier": "Pro", "gpu_cores": 18, "memory_gb": 18, "macos": "27.1"}
        self.assertEqual(hardware_key(hardware), "M3-Pro-18gpu-18gb-macos27")
        del hardware["gpu_cores"]
        self.assertEqual(hardware_key(hardware), "M3-Pro-xgpu-18gb-macos27")

    def test_summary_rounds_half_up_like_the_app(self):
        reports = [{"tier": "gold"}, {"tier": "platinum"}]
        self.assertEqual(build_index.summarize(reports)["tier"], "platinum")
        self.assertIsNone(build_index.summarize([])["score"])

    def test_repository_is_valid(self):
        errors: list[str] = []
        build_index.collect(errors)
        self.assertEqual(errors, [])


class GameFileTests(unittest.TestCase):
    """games/<slug>.yaml: the catalogue entry every recipe needs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for folder in ["schema", "games", "recipes/real-game", "reports"]:
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        for name in ["recipe.schema.json", "report.schema.json", "game.schema.json"]:
            (self.root / "schema" / name).write_text((ROOT / "schema" / name).read_text())
        self.recipe = yaml.safe_load((ROOT / "recipes/example-legacy-dx9-game/wined3d.yaml").read_text())
        self.recipe["game"] = {"title": "Real Game", "slug": "real-game", "installer": {"url": "https://cdn.example.com/RealGameSetup.exe"}}
        self.recipe["id"] = "wined3d"
        self.recipe.pop("forked_from", None)
        self.game = {"schema": 1, "slug": "real-game", "title": "Real Game", "genres": ["rpg"],
                     "description": "  A game.\n", "installer": {"url": "https://cdn.example.com/RealGameSetup.exe"}}

    def tearDown(self):
        self.tmp.cleanup()

    def write(self):
        (self.root / "recipes/real-game/wined3d.yaml").write_text(yaml.safe_dump(self.recipe))
        if self.game is not None:
            (self.root / "games/real-game.yaml").write_text(yaml.safe_dump(self.game))

    def collect(self):
        self.write()
        errors: list[str] = []
        with mock.patch.object(build_index, "ROOT", self.root), mock.patch("common.ROOT", self.root):
            result = build_index.collect(errors)
        return errors, result

    def test_valid_game_builds_catalogue_and_detail(self):
        errors, (games, recipes, reports) = self.collect()
        self.assertEqual(errors, [])
        with mock.patch.object(build_index, "ROOT", self.root):
            index, details = build_index.build_index(games, recipes, reports, "https://github.com/nullfx/distiller-recipes")
        self.assertEqual(index["schema"], 2)
        entry = index["games"][0]
        self.assertEqual(entry["description"], "A game.")
        self.assertEqual(entry["genres"], ["rpg"])
        self.assertEqual(entry["detail"], "games/real-game.json")
        self.assertEqual(entry["graphics"], ["wined3d"])
        self.assertEqual(entry["summary"]["reports"], 0)
        self.assertIn("recipes", entry, "The app still reads recipes from index.json")
        detail = details["real-game"]
        self.assertEqual(detail["recipes"][0]["recipe"]["id"], "wined3d")
        self.assertEqual(detail["recipes"][0]["reports"], [])

    def test_installer_may_name_its_download_page(self):
        page = "https://www.example.com/download"
        self.recipe["game"]["installer"]["page"] = page
        self.game["installer"]["page"] = page
        errors, (games, recipes, reports) = self.collect()
        self.assertEqual(errors, [])
        with mock.patch.object(build_index, "ROOT", self.root):
            index, _ = build_index.build_index(games, recipes, reports, "https://github.com/nullfx/distiller-recipes")
        self.assertEqual(index["games"][0]["installer"]["page"], page, "The page reaches the catalogue")

        self.game["installer"]["page"] = "http://www.example.com/download"
        errors, _ = self.collect()
        self.assertTrue(errors, "Only https pages")

    def test_every_recipe_needs_a_game_file(self):
        self.game = None
        errors, _ = self.collect()
        self.assertTrue(any("there's no games/real-game.yaml" in e for e in errors), errors)

    def test_recipe_must_agree_with_game(self):
        self.recipe["game"]["title"] = "Other Title"
        self.recipe["game"]["installer"] = {"url": "https://mirror.example.com/RealGameSetup.exe"}
        errors, _ = self.collect()
        self.assertTrue(any("differs from games/real-game.yaml" in e for e in errors), errors)
        self.assertTrue(any("isn't the official installer" in e for e in errors), errors)

    def test_game_without_recipes_and_bad_fields_are_rejected(self):
        (self.root / "games/lonely-game.yaml").write_text(yaml.safe_dump({"schema": 1, "slug": "lonely-game", "title": "Lonely"}))
        self.game["genres"] = ["not-a-genre"]
        self.game["website"] = "http://insecure.example.com"
        errors, _ = self.collect()
        self.assertTrue(any("lonely-game.yaml: the game has no recipes" in e for e in errors), errors)
        self.assertTrue(any("genres" in e for e in errors), errors)
        self.assertTrue(any("website" in e for e in errors), errors)

    def test_forks_may_add_game_files(self):
        errors, notices = check_pr.problems([("A", "games/real-game.yaml"), ("M", "games/other-game.yaml")])
        self.assertEqual(errors, [])
        self.assertTrue(any("game's details" in n for n in notices))
        errors, _ = check_pr.problems([("A", "games/real-game.json")])
        self.assertTrue(errors)


class ExampleGameTests(unittest.TestCase):
    def triple(self, slugs):
        games = {slug: {"slug": slug, "title": slug} for slug in slugs}
        recipes = {(slug, "dxvk"): (None, {}) for slug in slugs}
        reports = {(slug, "dxvk"): [{"date": "2026-11-07"}] for slug in slugs}
        return games, recipes, reports

    def test_examples_are_listed_until_there_is_a_real_game(self):
        catalogue, examples = build_index.split_examples(*self.triple(["example-dx11-game", "example-legacy-dx9-game"]))
        self.assertEqual(sorted(catalogue[0]), ["example-dx11-game", "example-legacy-dx9-game"])
        self.assertEqual(sorted(examples[0]), ["example-dx11-game", "example-legacy-dx9-game"])

    def test_real_games_push_the_examples_out_of_the_catalogue(self):
        catalogue, examples = build_index.split_examples(*self.triple(["example-dx11-game", "guild-wars-2"]))
        self.assertEqual(list(catalogue[0]), ["guild-wars-2"])
        self.assertEqual(list(catalogue[1]), [("guild-wars-2", "dxvk")])
        self.assertEqual(list(catalogue[2]), [("guild-wars-2", "dxvk")])
        self.assertEqual(list(examples[0]), ["example-dx11-game"])

    def test_include_examples_keeps_them(self):
        catalogue, _ = build_index.split_examples(*self.triple(["example-dx11-game", "guild-wars-2"]), include_examples=True)
        self.assertEqual(sorted(catalogue[0]), ["example-dx11-game", "guild-wars-2"])


class MediaTests(unittest.TestCase):
    """media/<slug>/icon.png and media/<slug>/<recipe>.jpg."""

    @staticmethod
    def png(width, height, padding=0):
        import struct
        return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x06\x00\x00\x00" + b"\x00" * padding

    @staticmethod
    def jpeg(width, height, padding=0):
        import struct
        app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
        sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 3) + b"\x00" * 3
        return b"\xff\xd8" + app0 + sof + b"\x00" * padding

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "media/real-game").mkdir(parents=True)
        self.games = {"real-game": {"slug": "real-game", "title": "Real Game"}}
        self.recipes = {("real-game", "dxvk"): (None, {})}

    def tearDown(self):
        self.tmp.cleanup()

    def collect(self, files):
        for name, data in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        errors: list[str] = []
        with mock.patch.object(build_index, "ROOT", self.root):
            media = build_index.collect_media(self.games, self.recipes, errors)
        return errors, media

    def test_reads_sizes(self):
        self.assertEqual(build_index.image_size(self.png(64, 64)), ("png", 64, 64))
        self.assertEqual(build_index.image_size(self.jpeg(1280, 720)), ("jpeg", 1280, 720))
        self.assertIsNone(build_index.image_size(b"GIF89a"))

    def test_valid_pictures_reach_the_index(self):
        errors, media = self.collect({
            "media/real-game/icon.png": self.png(256, 256),
            "media/real-game/dxvk/1.jpg": self.jpeg(1280, 720),
            "media/real-game/dxvk/2.jpg": self.jpeg(800, 600),
        })
        self.assertEqual(errors, [])
        self.assertEqual(media["real-game"], {"icon": "media/real-game/icon.png", "screenshots": {"dxvk": ["media/real-game/dxvk/1.jpg", "media/real-game/dxvk/2.jpg"]}})
        recipes = {("real-game", "dxvk"): (ROOT / "recipes/example-dx11-game/d3dmetal.yaml", BASE)}
        with mock.patch.object(build_index, "ROOT", ROOT):
            index, _ = build_index.build_index(self.games, recipes, {}, "https://github.com/x/y", media)
        self.assertEqual(index["games"][0]["icon"], "media/real-game/icon.png")
        self.assertEqual(index["games"][0]["recipes"][0]["screenshots"], ["media/real-game/dxvk/1.jpg", "media/real-game/dxvk/2.jpg"])

    def test_rejects_bad_pictures(self):
        for files in [
            {"media/real-game/icon.png": self.jpeg(256, 256)},                 # not a PNG
            {"media/real-game/icon.png": self.png(300, 200)},                  # not square
            {"media/real-game/icon.png": self.png(512, 512)},                  # too big
            {"media/real-game/icon.png": self.png(64, 64, padding=300_000)},  # too many bytes
            {"media/real-game/dxvk/1.jpg": self.png(1280, 720)},               # not a JPEG
            {"media/real-game/dxvk/1.jpg": self.jpeg(2560, 1440)},             # too wide
            {"media/real-game/other/1.jpg": self.jpeg(1280, 720)},             # no such recipe
            {"media/real-game/dxvk/2.jpg": self.jpeg(1280, 720)},              # gap: no 1.jpg
            {"media/real-game/dxvk/4.jpg": self.jpeg(1280, 720)},              # at most three
            {"media/real-game/dxvk.jpg": self.jpeg(1280, 720)},                # old flat layout
            {"media/other-game/icon.png": self.png(64, 64)},                   # no such game
            {"media/real-game/notes.txt": b"hello"},
            {"media/real-game/deeper/icon.png": self.png(64, 64)},
        ]:
            with self.subTest(files=list(files)):
                for old in sorted(self.root.glob("media/**/*"), reverse=True):
                    old.rmdir() if old.is_dir() else old.unlink()
                errors, _ = self.collect(files)
                self.assertTrue(errors)

    def test_forks_may_add_pictures(self):
        errors, notices = check_pr.problems([("A", "media/real-game/icon.png"), ("A", "media/real-game/dxvk/1.jpg"), ("D", "media/real-game/dxvk/3.jpg")])
        self.assertEqual(errors, [])
        self.assertEqual(len(notices), 2, "Screenshots get a reminder to look at them; removals are noted")
        for change in [("A", "media/real-game/icon.gif"), ("A", "media/real-game/banner.png"), ("D", "media/real-game/icon.png"),
                       ("A", "media/real-game/dxvk.jpg"), ("A", "media/real-game/dxvk/4.jpg")]:
            with self.subTest(change=change):
                self.assertTrue(check_pr.problems([change])[0])


class IssueConversionTests(unittest.TestCase):
    BODY = "\n\n".join([
        "### Game slug\n\nexample-dx11-game",
        "### Recipe ID\n\nd3dmetal",
        "### Playability\n\ngold",
        "### Average FPS\n\n55",
        "### Chip\n\nApple M4",
        "### Chip family\n\nM4",
        "### Chip tier\n\nBase",
        "### GPU cores\n\n10",
        "### Memory (GB)\n\n16",
        "### macOS version\n\n27.1",
        "### Rosetta available\n\ntrue",
        "### Wine build\n\n_No response_",
        "### Graphics layer\n\nd3dmetal@4.0",
        "### Notes\n\nRuns well.",
    ])

    def test_form_round_trip(self):
        fields = issue_to_report.parse_form(self.BODY)
        report = issue_to_report.build_report(fields, 42, "2026-11-05T10:00:00Z")
        self.assertEqual(list(validator("report.schema.json").iter_errors(report)), [])
        self.assertEqual(report["hardware"]["gpu_cores"], 10)
        self.assertEqual(report["components"], {"graphics": "d3dmetal@4.0"})
        self.assertEqual(report["date"], "2026-11-05")

    def test_rejects_path_traversal_in_slug(self):
        body = self.BODY.replace("example-dx11-game", "../../.github")
        report = issue_to_report.build_report(issue_to_report.parse_form(body), 7, "2026-11-05")
        self.assertTrue(list(validator("report.schema.json").iter_errors(report)))

    def test_main_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            event = Path(tmp) / "event.json"
            event.write_text(json.dumps({"issue": {"number": 9999, "body": self.BODY, "created_at": "2026-11-05T00:00:00Z"}}))
            sys.argv = ["issue_to_report.py", "--event", str(event)]
            os.environ.pop("GITHUB_OUTPUT", None)
            target = ROOT / "reports/example-dx11-game/d3dmetal/issue-9999.yaml"
            try:
                self.assertEqual(issue_to_report.main(), 0)
                self.assertTrue(target.exists())
                errors: list[str] = []
                build_index.collect(errors)
                self.assertEqual(errors, [])
            finally:
                target.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main(verbosity=1)
