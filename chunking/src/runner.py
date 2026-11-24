"""Build chunks for parsed documents and save them, one JSON file per document.

For each company it reads ``<parsed>/<company>/md/*.json``, builds the chunks of each
document with ``build_chunks``, and writes ``<chunks>/<company>/md/<doc_key>.json``.
The file holds a list of chunks, in reading order.

Run: ``python -m chunking.src.runner`` (paths come from ``default.yaml``).
"""

from __future__ import annotations

import json
from pathlib import Path

from chunking.src.chunk_builder import build_chunks
from config.src.config import load_config, path_setting
from config.src.constants import CHUNKS_DIR, PARSED_DIR

# The format this runner handles. Used in folder names.
FORMAT = "md"

# TEMPORARY: while we look at the first results, only these documents are chunked.
# Each entry is a company and the doc_key names of its documents. Set it to None to
# chunk every document, then delete it.
SAMPLE_FILES: dict[str, list[str]] | None = None


def save_chunks(path: Path, chunks: list[dict]) -> None:
    """Write the chunks of one document as a JSON list."""
    path.parent.mkdir(parents=True, exist_ok=True)  # create the folders if they are missing
    # Write to a temporary name first, then rename, so a crash never leaves a half-written file.
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        # ensure_ascii=False keeps characters like the dash as they are. indent=2 makes it easy to read.
        json.dump(chunks, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temporary.replace(path)


def is_wanted(company: str, doc_key: str) -> bool:
    """True if this document should be chunked (always, unless SAMPLE_FILES limits it)."""
    return SAMPLE_FILES is None or doc_key in SAMPLE_FILES.get(company, [])


def run(parsed_dir: Path, chunks_dir: Path) -> list[tuple[Path, int]]:
    """Chunk the chosen documents. Returns where each file went and how many chunks it holds."""
    if not parsed_dir.is_dir():
        raise NotADirectoryError(f"parsed folder not found: {parsed_dir}")

    saved = []
    for company_dir in sorted(p for p in parsed_dir.iterdir() if p.is_dir()):
        folder = company_dir / FORMAT
        if not folder.is_dir():
            continue
        for file in sorted(folder.glob("*.json")):
            if not is_wanted(company_dir.name, file.stem):
                continue
            with open(file, encoding="utf-8") as handle:
                chunks = build_chunks(json.load(handle))
            out = chunks_dir / company_dir.name / FORMAT / file.name
            save_chunks(out, chunks)
            saved.append((out, len(chunks)))
    return saved


def main() -> int:
    # Read default.yaml, then turn the two folder settings into full paths.
    config = load_config()
    parsed_dir = path_setting(config, PARSED_DIR)
    chunks_dir = path_setting(config, CHUNKS_DIR)
    saved = run(parsed_dir, chunks_dir)

    for out, count in saved:
        print(f"saved {out} ({count} chunks)")
    print(f"chunked {len(saved)} documents")
    return 0


# True only when the file is started directly (python -m ...), not when another file imports it.
if __name__ == "__main__":
    raise SystemExit(main())
