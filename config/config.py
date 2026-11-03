"""Shared settings: load a YAML config file and resolve the paths in it."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "configs" / "default.yaml"


def load_config(path: Path | str | None = None) -> dict:
    """Read a YAML config file (the default one when ``path`` is None)."""
    with open(Path(path) if path is not None else DEFAULT_CONFIG, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def resolve_path(value: Path | str) -> Path:
    """Expand ``~``. A relative path is taken from the repo root, not the working directory."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


def path_setting(config: dict, name: str) -> Path:
    """Return ``paths.<name>`` from the config as a resolved path."""
    value = (config.get("paths") or {}).get(name)
    if value is None:
        raise KeyError(f"config is missing paths.{name}")
    return resolve_path(value)
