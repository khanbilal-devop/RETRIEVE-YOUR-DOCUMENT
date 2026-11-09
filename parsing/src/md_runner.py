"""Parse the Markdown files in the registry and save each one as a JSON file.

For each company it reads ``<registry>/<company>/md.jsonl``, parses every listed
file with ``parse_md_file``, and writes ``<parsed>/<company>/md/<doc_id>.json``.
A saved document is ``{"doc_id", "doc_key", "path", "company", "format", "blocks"}``.
The file is named after ``doc_id`` so it links straight back to its registry record.

Run: ``python -m parsing.src.md_runner`` (paths come from ``default.yaml``).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from config.src.config import DEFAULT_CONFIG, load_config, path_setting
from config.src.constants import DATASET_DIR, PARSED_DIR, REGISTRY_DIR
from ingest.src.ingest import matches
from parsing.src.md_parser import parse_md_file

FORMAT = "md"

# TEMPORARY: while we test, only these files are parsed. Add more companies and
# files as needed. Set it to None to parse every Markdown file in the registry,
# then delete it.
SAMPLE_FILES: dict[str, list[str]] | None = {
    "Aventro Motors": ["Pre-Owned Certified Cars.md"],
}


def read_records(registry_dir: Path, company: str) -> list[dict]:
    """Registry records of one company's Markdown files."""
    file = registry_dir / company / f"{FORMAT}.jsonl"
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


def select_records(company: str, records: list[dict]) -> list[dict]:
    """Keep only the sample files, unless SAMPLE_FILES is None."""
    if SAMPLE_FILES is None:
        return records
    wanted = SAMPLE_FILES.get(company, [])
    return [r for r in records if any(matches(name, r["doc_key"]) for name in wanted)]


def save_document(parsed_dir: Path, document: dict) -> Path:
    """Write one parsed document as JSON and return where it went."""
    out = parsed_dir / document["company"] / FORMAT / f"{document['doc_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(out.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(out)
    return out


def run(dataset_dir: Path, registry_dir: Path, parsed_dir: Path) -> tuple[list[tuple[Path, int]], list[str]]:
    """Parse the chosen Markdown files. Returns what was saved and what failed."""
    if not registry_dir.is_dir():
        raise NotADirectoryError(f"registry folder not found: {registry_dir}")

    saved: list[tuple[Path, int]] = []
    failed: list[str] = []
    companies = sorted(p.name for p in registry_dir.iterdir() if (p / f"{FORMAT}.jsonl").is_file())

    for company in SAMPLE_FILES or {}:
        if company not in companies:
            failed.append(f"{company}: not in the registry")

    for company in companies:
        chosen = select_records(company, read_records(registry_dir, company))
        for name in (SAMPLE_FILES or {}).get(company, []):
            if not any(matches(name, r["doc_key"]) for r in chosen):
                failed.append(f"{company}/{name}: not in the registry")
        for record in chosen:
            try:
                blocks = parse_md_file(dataset_dir / record["path"])
                if not blocks:
                    raise ValueError("no content found")
            except Exception as error:  # one bad file must not stop the run
                failed.append(f"{record['path']}: {error}")
                continue
            document = {
                "doc_id": record["doc_id"],
                "doc_key": record["doc_key"],
                "path": record["path"],
                "company": company,
                "format": FORMAT,
                "blocks": blocks,
            }
            saved.append((save_document(parsed_dir, document), len(blocks)))
    return saved, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m parsing.src.md_runner", description="Parse Markdown files from the registry (layer 2)."
    )
    parser.add_argument(
        "--config",
        type=Path,
        help=f"config file with the folder paths (default: {DEFAULT_CONFIG.name})",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
    dataset_dir = path_setting(config, DATASET_DIR)
    registry_dir = path_setting(config, REGISTRY_DIR)
    parsed_dir = path_setting(config, PARSED_DIR)
    saved, failed = run(dataset_dir, registry_dir, parsed_dir)

    for out, count in saved:
        print(f"saved {out} ({count} blocks)")
    print(f"parsed {len(saved)}, failed {len(failed)}")
    for message in failed:
        print(f"  failed: {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
