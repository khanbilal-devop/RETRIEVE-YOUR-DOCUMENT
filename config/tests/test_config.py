import os
from pathlib import Path

import pytest

from config.src.config import REPO_ROOT, load_config, path_setting, resolve_path
from config.src.constants import DATASET_DIR, REGISTRY_DIR


def test_default_config_has_both_paths():
    config = load_config()
    assert path_setting(config, DATASET_DIR) == REPO_ROOT / "reference repo" / "datasets"
    assert path_setting(config, REGISTRY_DIR) == REPO_ROOT / "registry"


def test_relative_path_starts_at_repo_root_not_working_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert resolve_path("registry") == REPO_ROOT / "registry"


def test_absolute_path_is_kept_and_tilde_is_expanded(tmp_path):
    assert resolve_path(tmp_path) == tmp_path
    assert resolve_path("~/data") == Path(os.path.expanduser("~/data"))


def test_missing_key_names_the_key():
    with pytest.raises(KeyError, match="paths.dataset_dir"):
        path_setting({}, DATASET_DIR)
