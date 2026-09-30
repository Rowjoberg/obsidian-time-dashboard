"""Single-row configuration store backed by the database.

The domain configuration (vault location, reporting defaults and the task layout)
used to live only in ``config.yaml``. It now lives in a single ``TaskLayoutConfig``
row so it can be edited from the web app. ``config.yaml`` is still read once, as
the seed for that row, so existing installs keep working after migrating.
"""

from __future__ import annotations

from django.conf import settings as django_settings


def seed_values() -> dict[str, object]:
    """Default values for a fresh configuration row, taken from config.yaml."""
    config = getattr(django_settings, "CONFIG", {}) or {}
    vault = config.get("vault", {}) or {}
    reporting = config.get("reporting", {}) or {}
    return {
        "include_invalid_durations_in_totals": bool(reporting.get("invalid_durations_in_totals", False)),
        "default_period": reporting.get("default_period", "month"),
        "default_group_by": reporting.get("default_group_by", "display_title"),
        "vault_path": str(vault.get("path", "")),
        "daily_notes_path": vault.get("daily_notes_path", ""),
    }


def get_config(model):
    """Return the configuration row, creating it from config.yaml on first use."""
    config = model.objects.order_by("pk").first()
    if config is None:
        config = model.objects.create(**seed_values())
    return config


def vault_settings(model):
    """Return ``(vault_path, daily_notes_path)`` as a ``(Path, str)`` pair."""
    from pathlib import Path

    config = get_config(model)
    return Path(config.vault_path), config.daily_notes_path
