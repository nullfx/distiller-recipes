"""Helpers shared by the repository scripts."""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
TIER_SCORE = {"borked": 0, "bronze": 1, "silver": 2, "gold": 3, "platinum": 4}


class _Loader(yaml.SafeLoader):
    """SafeLoader that keeps dates as strings, so they validate as JSON strings."""


_Loader.yaml_implicit_resolvers = {
    first: [(tag, regex) for tag, regex in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(path: Path):
    with path.open(encoding="utf-8") as handle:
        return yaml.load(handle, Loader=_Loader)


def validator(name: str) -> Draft202012Validator:
    schema = json.loads((ROOT / "schema" / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(validator_: Draft202012Validator, data, label: str) -> list[str]:
    errors = []
    for error in sorted(validator_.iter_errors(data), key=lambda e: list(e.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "(top level)"
        errors.append(f"{label}: {location}: {error.message}")
    return errors


def hardware_key(hardware: dict) -> str:
    """Must match HardwareProfile.hardwareKey in the Distiller app."""
    gpu = hardware.get("gpu_cores")
    major = str(hardware["macos"]).split(".")[0]
    return (
        f"{hardware['chip_family']}-{hardware['chip_tier']}-"
        f"{gpu if gpu is not None else 'x'}gpu-{hardware['memory_gb']}gb-macos{major}"
    )
