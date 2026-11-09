"""Parse the Markdown files in the registry and save each one as a JSON file.

For each company it reads ``<registry>/<company>/md.jsonl``, parses every listed
file with ``parse_md_file``, and writes ``<parsed>/<company>/md/<doc_key>.json``.
A saved document is ``{"doc_id", "doc_key", "path", "company", "format", "content"}``,
where ``content`` is the file nested into sections (see ``md_parser``).
The file is named after the first ``doc_key``, so it is easy to find by document name.

Run: ``python -m parsing.src.md_runner`` (paths come from ``default.yaml``).
"""

from __future__ import annotations

import json
from pathlib import Path

from config.src.config import load_config, path_setting
from config.src.constants import DATASET_DIR, PARSED_DIR, REGISTRY_DIR
from ingest.src.ingest import matches
from parsing.src.md_parser import parse_md_file

# The format this runner handles. Used in file names and folder names.
FORMAT = "md"

# TEMPORARY: while we test, only these files are parsed. Add more companies and
# files as needed. Set it to None to parse every Markdown file in the registry,
# then delete it.
SAMPLE_FILES: dict[str, list[str]] | None = {
    "Aventro Motors": ["Pre-Owned Certified Cars.md"],
    "Cendara University": ["dept_of_Curriclumn_Catalog.md"],
}


def count_blocks(section: dict) -> int:
    """Blocks in a section and in every section below it."""
    return len(section["blocks"]) + sum(count_blocks(child) for child in section["sections"])


def read_records(registry_dir: Path, company: str) -> list[dict]:
    """Registry records of one company's Markdown files."""
    # The registry file for this company, for example registry/Aventro Motors/md.jsonl.
    file = registry_dir / company / f"{FORMAT}.jsonl"
    # Each line of the file is one JSON record. Turn every non-empty line into a dict.
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


def select_records(company: str, records: list[dict]) -> list[dict]:
    """Keep only the sample files, unless SAMPLE_FILES is None."""
    # None means "no test list", so keep every record.
    if SAMPLE_FILES is None:
        return records
    # The file names we want for this company (an empty list if the company is not in the test list).
    wanted = SAMPLE_FILES.get(company, [])
    # Keep a record if any wanted name matches one of its doc_key names.
    return [r for r in records if any(matches(name, r["doc_key"]) for name in wanted)]


def save_document(parsed_dir: Path, document: dict) -> Path:
    """Write one parsed document as JSON and return where it went."""
    # Where it goes: parsed/<company>/md/<doc_key>.json (the first doc_key; it is unique per company and format)
    out = parsed_dir / document["company"] / FORMAT / f"{document['doc_key'][0]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)  # create the folders if they are missing
    # Write to a temporary name first, then rename. A crash can then never leave a half-written file.
    temporary = out.with_name(out.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        # ensure_ascii=False keeps characters like the dash as they are. indent=2 makes it easy to read.
        json.dump(document, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(out)
    return out


def run(dataset_dir: Path, registry_dir: Path, parsed_dir: Path) -> tuple[list[tuple[Path, int]], list[str]]:
    """Parse the chosen Markdown files. Returns what was saved and what failed."""
    if not registry_dir.is_dir():
        raise NotADirectoryError(f"registry folder not found: {registry_dir}")

    saved: list[tuple[Path, int]] = []  # (where it was saved, how many blocks)
    failed: list[str] = []  # one message per problem

    # Company folders in the registry that have a Markdown registry file.
    companies = sorted(p.name for p in registry_dir.iterdir() if (p / f"{FORMAT}.jsonl").is_file())

    # Warn if the test list names a company that is not in the registry.
    for company in SAMPLE_FILES or {}:
        if company not in companies:
            failed.append(f"{company}: not in the registry")

    for company in companies:
        # Read this company's records, then keep only the ones we want to parse.
        chosen = select_records(company, read_records(registry_dir, company))
        # Warn if a file in the test list was not found in this company's registry.
        for name in (SAMPLE_FILES or {}).get(company, []):
            if not any(matches(name, r["doc_key"]) for r in chosen):
                failed.append(f"{company}/{name}: not in the registry")
        for record in chosen:
            try:
                # Open the real file (dataset folder + the path from the registry) and parse it.
                content = parse_md_file(dataset_dir / record["path"])
                if not content["blocks"] and not content["sections"]:
                    raise ValueError("no content found")
            except Exception as error:  # one bad file must not stop the run
                failed.append(f"{record['path']}: {error}")
                continue
            # The parsed document: the registry details plus the content (the sections).
            document = {
                "doc_id": record["doc_id"],
                "doc_key": record["doc_key"],
                "path": record["path"],
                "company": company,
                "format": FORMAT,
                "content": content,
            }
            saved.append((save_document(parsed_dir, document), count_blocks(content)))
    return saved, failed


def main() -> int:
    # Read default.yaml, then turn the three folder settings into full paths.
    config = load_config()
    dataset_dir = path_setting(config, DATASET_DIR)
    registry_dir = path_setting(config, REGISTRY_DIR)
    parsed_dir = path_setting(config, PARSED_DIR)
    # Do the work: read the registry, parse the files, save the results.
    saved, failed = run(dataset_dir, registry_dir, parsed_dir)

    # Print what happened.
    for out, count in saved:
        print(f"saved {out} ({count} blocks)")
    print(f"parsed {len(saved)}, failed {len(failed)}")
    for message in failed:
        print(f"  failed: {message}")
    return 0


# True only when the file is started directly (python -m ...), not when another file imports it.
if __name__ == "__main__":
    raise SystemExit(main())
