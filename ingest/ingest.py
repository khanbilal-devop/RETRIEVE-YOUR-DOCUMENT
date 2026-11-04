"""Layer 1, ingestion: register every file before any content is read.

Walks ``<dataset>/<company>/**`` and writes ``<registry>/<company>/<format>.jsonl``
(one registry per company and format) plus ``<registry>/<company>/rejected.jsonl``. A
registry record is ``{"doc_id", "doc_key", "path"}``:

- ``doc_id``: SHA-256 of the file's bytes.
- ``doc_key``: normalized names
- ``path``: relative to the dataset folder

The format is not stored in a record: it is the name of the registry file.

Run: ``python -m ingest.ingest`` (paths come from ``default.yaml``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from config.config import DEFAULT_CONFIG, load_config, path_setting
from config.constants import DATASET_DIR, REGISTRY_DIR

FORMATS = ("pdf", "docx", "pptx", "html", "md")

_SYSTEM_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
_KNOWN_EXTENSIONS = (".pdf", ".docx", ".pptx", ".html", ".htm", ".md", ".markdown")
_ESCAPE = re.compile(r"#U([0-9A-Fa-f]{4})")
_SUFFIX = re.compile(r"_\d+$")
# The dataset's HTML files are fragments (they start "<h1 ...>" with no <html> or
# <body>), so HTML is recognized by a tag at the very start of the file.
_HTML_START = re.compile(
    rb"^(?:\xef\xbb\xbf)?\s*<\s*(?:!doctype|html|head|body|h[1-6]|p|div|ul|ol|table|section|article|span|a|br|hr)\b",
    re.IGNORECASE,
)
_SNIFF_BYTES = 8192


def normalize_name(name: str) -> str:
    """Normalize a file name so format copies and benchmark citations line up.

    Decodes ``#UXXXX`` escapes (an unzip artifact for characters such as the en
    dash), maps every dash to a hyphen, collapses and trims spaces, lowercases,
    and drops a known extension.
    """

    def decode(match: re.Match) -> str:
        code = int(match.group(1), 16)
        return match.group(0) if 0xD800 <= code <= 0xDFFF else chr(code)

    name = _ESCAPE.sub(decode, name)
    name = "".join("-" if unicodedata.category(c) == "Pd" else c for c in name)
    name = " ".join(name.split()).lower()
    for extension in _KNOWN_EXTENSIONS:
        if name.endswith(extension):
            name = name[: -len(extension)]
            break
    return name.strip()


def match_key(name: str) -> str:
    """Normalize ``name`` and drop a trailing ``_N`` collision suffix."""
    return _SUFFIX.sub("", normalize_name(name))


def matches(name: str, doc_key: list[str]) -> bool:
    """True if a benchmark file name equals any name in a record's ``doc_key``."""
    key = match_key(name)
    return any(match_key(candidate) == key for candidate in doc_key)


def is_system_file(name: str) -> bool:
    lowered = name.lower()
    return lowered in _SYSTEM_NAMES or lowered.startswith(("._", "~$"))


def detect_format(path: Path) -> str | None:
    """Return the file's format judged from its content, or None if unsupported.

    PDF and the zip-based Office formats have signatures and HTML starts with a
    tag. Markdown has no signature, so plain text counts as markdown only when
    the extension is ``.md``.
    """
    with open(path, "rb") as handle:
        head = handle.read(_SNIFF_BYTES)
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK"):
        try:
            with zipfile.ZipFile(path) as archive:
                names = set(archive.namelist())
        except zipfile.BadZipFile:
            return None
        if "word/document.xml" in names:
            return "docx"
        if "ppt/presentation.xml" in names:
            return "pptx"
        return None
    if _HTML_START.match(head):
        return "html"
    if path.suffix.lower() == ".md" and b"\x00" not in head:
        return "md"
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class IngestResult:
    registered: int
    rejected: list[dict]
    format_mismatches: list[str]  # registered files whose folder name differs from their detected format


class _Reject(Exception):
    """A file that is skipped; the message is the reason logged."""


def _inspect(path: Path) -> tuple[str, str]:
    """Return ``(format, doc_id)`` for a file, or raise ``_Reject``."""
    if is_system_file(path.name):
        raise _Reject("system file")
    if path.stat().st_size == 0:
        raise _Reject("empty file")
    fmt = detect_format(path)
    if fmt is None:
        raise _Reject("unsupported type")
    return fmt, sha256_file(path)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    temporary.replace(path)


def ingest(dataset_dir: Path | str, registry_dir: Path | str) -> IngestResult:
    """Register every file under ``dataset_dir/<company>/`` and write the registries.

    Files are processed in sorted order. A file that cannot be read is logged in
    ``rejected.jsonl`` and the run continues. Re-running rewrites identical output.
    """
    dataset_dir, registry_dir = Path(dataset_dir), Path(registry_dir)
    if not dataset_dir.is_dir():
        raise NotADirectoryError(f"dataset folder not found: {dataset_dir}")

    registries: dict[tuple[str, str], list[dict]] = {}
    seen: dict[tuple[str, str, str], dict] = {}  # (company, format, doc_id) -> kept record
    taken: dict[tuple[str, str], set[str]] = {}  # (company, format) -> doc_key names in use
    rejected: list[dict] = []
    mismatches: list[str] = []

    for company_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir()):
        company = company_dir.name
        for fmt in FORMATS:
            registries[(company, fmt)] = []
        files = sorted(
            (p for p in company_dir.rglob("*") if p.is_file()),
            key=lambda p: p.relative_to(dataset_dir).as_posix(),
        )
        for path in files:
            rel = path.relative_to(dataset_dir).as_posix()
            try:
                rel.encode("utf-8")
                fmt, doc_id = _inspect(path)
            except _Reject as reason:
                rejected.append({"path": rel, "reason": str(reason)})
                continue
            except Exception as error:  # one bad file must never stop the run
                rejected.append({"path": rel, "reason": f"unreadable: {error}"})
                continue

            name = normalize_name(path.name)
            names = taken.setdefault((company, fmt), set())
            kept = seen.get((company, fmt, doc_id))
            if kept is not None:
                rejected.append({"path": rel, "reason": f"duplicate of {kept['path']}"})
                if name not in kept["doc_key"]:
                    kept["doc_key"].append(name)
                names.add(name)
                continue

            doc_key, suffix = name, 2
            while doc_key in names:
                doc_key = f"{name}_{suffix}"
                suffix += 1
            names.add(doc_key)
            record = {"doc_id": doc_id, "doc_key": [doc_key], "path": rel}
            seen[(company, fmt, doc_id)] = record
            registries[(company, fmt)].append(record)
            if path.relative_to(company_dir).parts[0].lower() != fmt:
                mismatches.append(rel)

    for (company, fmt), records in registries.items():
        _write_jsonl(registry_dir / company / f"{fmt}.jsonl", records)
    for company in sorted({company for company, _ in registries}):
        rows = [r for r in rejected if r["path"].split("/", 1)[0] == company]
        _write_jsonl(registry_dir / company / "rejected.jsonl", rows)
    registered = sum(len(records) for records in registries.values())
    return IngestResult(registered, rejected, mismatches)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ingest.ingest", description="Register every dataset file (layer 1)."
    )
    parser.add_argument(
        "--config",
        type=Path,
        help=f"config file with the dataset and registry paths (default: {DEFAULT_CONFIG.name})",
    )
    args = parser.parse_args(argv)

    config = load_config(args.config)
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


if __name__ == "__main__":
    raise SystemExit(main())
