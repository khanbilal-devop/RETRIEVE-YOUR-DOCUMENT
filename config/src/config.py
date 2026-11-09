"""Shared settings: load default.yaml and resolve the paths in it."""

from __future__ import annotations

from pathlib import Path

import yaml

from config.src.constants import PATHS

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG = REPO_ROOT / "default.yaml"


# Not tied to any layer: any layer can call this to read default.yaml into a dict.
def load_config() -> dict:
    """Read default.yaml."""
    with open(DEFAULT_CONFIG, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


# Not tied to any layer: turns any configured path into an absolute path.
def resolve_path(value: Path | str) -> Path:
    """Expand ``~``. A relative path is taken from the repo root, not the working directory."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


# Not tied to any layer: returns the path stored under `paths` for a key such as DATASET_DIR.
def path_setting(config: dict, name: str) -> Path:
    """Return ``paths.<name>`` from the config as a resolved path."""
    value = (config.get(PATHS) or {}).get(name)
    if value is None:
        raise KeyError(f"config is missing {PATHS}.{name}")
    return resolve_path(value)
