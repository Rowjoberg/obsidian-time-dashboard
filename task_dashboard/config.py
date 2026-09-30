from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml

DEFAULT_CONFIG = {
    "app": {
        "debug": True,
        "secret_key": "change-me-for-production",
        "allowed_hosts": ["127.0.0.1", "localhost"],
        "time_zone": "Australia/Sydney",
    },
    "vault": {
        "path": r"C:\path\to\Obsidian",
        "daily_notes_path": "Automated Notes/Daily Notes",
    },
    "reporting": {
        "default_period": "month",
        "default_group_by": "display_title",
        "invalid_durations_in_totals": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_project_config(base_dir: Path) -> dict:
    config_path = base_dir / "config.yaml"
    if not config_path.exists():
        return deepcopy(DEFAULT_CONFIG)

    with config_path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    if not isinstance(loaded, dict):
        return deepcopy(DEFAULT_CONFIG)

    return _deep_merge(DEFAULT_CONFIG, loaded)
