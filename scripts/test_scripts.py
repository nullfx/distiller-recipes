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
