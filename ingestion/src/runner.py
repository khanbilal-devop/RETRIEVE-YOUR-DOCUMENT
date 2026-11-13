"""Run the ingestion layer: register every dataset file and print a short summary.

Run: ``python -m ingestion.src.runner`` (paths come from ``default.yaml``).
"""

from __future__ import annotations

from collections import Counter

from config.src.config import load_config, path_setting
from config.src.constants import DATASET_DIR, REGISTRY_DIR
from ingestion.src.ingest import ingest


def main() -> int:
    config = load_config()
    dataset_dir = path_setting(config, DATASET_DIR)
    registry_dir = path_setting(config, REGISTRY_DIR)
    result = ingest(dataset_dir, registry_dir)

    print(f"dataset:  {dataset_dir}")
    print(f"registry: {registry_dir}")
    print(f"registered {result.registered}, rejected {len(result.rejected)}")
    kinds = Counter(r["reason"].split(" of ", 1)[0].split(":", 1)[0] for r in result.rejected)
    for kind, count in sorted(kinds.items()):
        print(f"  {kind}: {count}")
    if result.format_mismatches:
        print(f"{len(result.format_mismatches)} files sit in a folder that differs from their detected format")
    return 0


# True only when the file is started directly (python -m ...), not when another file imports it.
if __name__ == "__main__":
    raise SystemExit(main())
