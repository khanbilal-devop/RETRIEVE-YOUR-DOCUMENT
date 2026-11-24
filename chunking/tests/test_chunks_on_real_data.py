"""Checks on the real chunks in data/chunks, against the parsed documents in data/parsed.

The rule tests (test_chunk_builder.py) use small made-up documents. These checks read
every real chunk file next to its parsed file and test things that must always be true,
so they can catch cases we did not think of. They do not run the chunker. They check
the files it already wrote, so run ``python -m chunking.src.runner`` first.

Each check is one test. When it fails, it lists the first few documents that broke it.
The checks use their own simple code (not the chunk builder's helpers), so a mistake
in the builder cannot hide itself.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PARSED_DIR = ROOT / "data" / "parsed"
CHUNKS_DIR = ROOT / "data" / "chunks"

pytestmark = pytest.mark.skipif(
    not PARSED_DIR.is_dir() or not CHUNKS_DIR.is_dir(), reason="data/parsed and data/chunks are not there"
)

SMALL = 10  # a chunk under this many words should be alone in its section
NOTE = re.compile(r"^\W*(note|disclaimer|important)\b", re.IGNORECASE)


# ---- helpers used by the checks --------------------------------------------


def blocks_of(section, titles=(), entries=None):
    """Every block of a parsed document, in reading order, with where it sits."""
    if entries is None:
        entries = []
    here = titles + (section["title"],) if section["title"] else titles
    for index, block in enumerate(section["blocks"]):
        entries.append(
            {
                "block": block,
                "titles": here,
                "section": id(section),
                "untitled": section["title"] is None,
                "first": index == 0,
            }
        )
    for child in section["sections"]:
        blocks_of(child, here, entries)
    return entries


def words(block):
    """Words in the content of a block."""
    if block["type"] == "list":
        return sum(len(item["text"].split()) for item in block["items"])
    if block["type"] == "table":
        return sum(len(cell.split()) for cell in block["header"] + [c for row in block["rows"] for c in row])
    return len(block.get("text", "").split())


def is_colon(block):
    """A paragraph or quote ending with a colon."""
    return block["type"] in ("paragraph", "quote") and block["text"].rstrip().endswith(":")


def is_note(block):
    """A quote, or a paragraph starting with Note, Disclaimer or Important, that is not a colon line."""
    if is_colon(block):
        return False
    return block["type"] == "quote" or (block["type"] == "paragraph" and bool(NOTE.match(block["text"])))


@pytest.fixture(scope="module")
def corpus():
    """Every document: its name, its parsed blocks, and its chunks, each chunk paired with its blocks."""
    documents = []
    for chunk_file in sorted(CHUNKS_DIR.glob("*/md/*.json")):
        parsed_file = PARSED_DIR / chunk_file.relative_to(CHUNKS_DIR)
        if not parsed_file.is_file():
            continue
        parsed = json.loads(parsed_file.read_text(encoding="utf-8"))
        chunks = json.loads(chunk_file.read_text(encoding="utf-8"))
        entries = blocks_of(parsed["content"])
        # The locations of the chunks, in order, say which blocks each chunk holds.
        spans, start = [], 0
        for chunk in chunks:
            spans.append(entries[start : start + len(chunk["locations"])])
            start += len(chunk["locations"])
        documents.append({"name": str(chunk_file.relative_to(CHUNKS_DIR)), "parsed": parsed, "entries": entries, "chunks": chunks, "spans": spans})
    assert documents, "no chunk files found"
    return documents


def report(problems):
    """Fail with a short list of what went wrong."""
    assert not problems, f"{len(problems)} problems, for example:\n" + "\n".join(problems[:8])


# ============================================================================
# GROUP 1: nothing is lost, nothing is repeated
# ============================================================================


# Every block of the parsed document is in exactly one chunk, in reading order.
def test_every_block_is_in_exactly_one_chunk_in_order(corpus):
    problems = []
    for doc in corpus:
        in_chunks = [location for chunk in doc["chunks"] for location in chunk["locations"]]
        in_document = [entry["block"]["location"] for entry in doc["entries"]]
        if in_chunks != in_document:
            problems.append(f"{doc['name']}: {len(in_chunks)} blocks in the chunks, {len(in_document)} in the document")
    report(problems)


# ============================================================================
# GROUP 2: merging stays inside one section
# ============================================================================


# No chunk mixes blocks from two sections. The one exception is a quote that starts an untitled section.
def test_no_chunk_mixes_blocks_of_two_sections(corpus):
    problems = []
    for doc in corpus:
        for number, span in enumerate(doc["spans"], start=1):
            for previous, entry in zip(span, span[1:]):
                crosses_a_divider = entry["block"]["type"] == "quote" and entry["first"] and entry["untitled"]
                if entry["section"] != previous["section"] and not crosses_a_divider:
                    problems.append(f"{doc['name']} chunk {number}: mixes two sections ({' > '.join(entry['titles'])})")
    report(problems)


# The path of a chunk is the section titles above its first block.
def test_the_path_is_the_titles_above_the_first_block(corpus):
    problems = []
    for doc in corpus:
        for number, (chunk, span) in enumerate(zip(doc["chunks"], doc["spans"]), start=1):
            expected = " > ".join(span[0]["titles"])
            if chunk["path"] != expected:
                problems.append(f"{doc['name']} chunk {number}: path {chunk['path']!r}, expected {expected!r}")
    report(problems)


# ============================================================================
# GROUP 3: the rules were followed
# ============================================================================


# A colon line is never left apart from the block below it in the same section.
def test_a_colon_line_is_joined_to_the_block_below(corpus):
    problems = []
    for doc in corpus:
        for number, (span, below) in enumerate(zip(doc["spans"], doc["spans"][1:]), start=1):
            last, first_below = span[-1], below[0]
            if is_colon(last["block"]) and first_below["section"] == last["section"]:
                problems.append(f"{doc['name']} chunk {number}: ends with a colon line but the next block is in the same section")
    report(problems)


# A chunk under 10 words is alone in its section: no chunk above or below it in the same section.
def test_a_small_chunk_has_no_neighbour_in_its_section(corpus):
    problems = []
    for doc in corpus:
        spans = doc["spans"]
        for number, span in enumerate(spans):
            if sum(words(entry["block"]) for entry in span) >= SMALL:
                continue
            has_above = number > 0 and spans[number - 1][-1]["section"] == span[0]["section"]
            has_below = number + 1 < len(spans) and spans[number + 1][0]["section"] == span[-1]["section"]
            if has_above or has_below:
                problems.append(f"{doc['name']} chunk {number + 1}: small, but has a neighbour in its section")
    report(problems)


# A note or quote only starts its own chunk where a rule allows it: it is first in its section,
# or the chunk above already took a note.
def test_a_note_starts_a_chunk_only_where_allowed(corpus):
    problems = []
    for doc in corpus:
        spans = doc["spans"]
        for number in range(1, len(spans)):
            first, above = spans[number][0], spans[number - 1]
            if not is_note(first["block"]) or above[-1]["section"] != first["section"]:
                continue
            took_a_note = any(is_note(entry["block"]) for entry in above[1:])
            if not took_a_note:
                problems.append(f"{doc['name']} chunk {number + 1}: a note starts a chunk, but it could have joined the chunk above")
    report(problems)


# ============================================================================
# GROUP 4: the fields of every chunk
# ============================================================================


# Ids count from 1 in reading order, the document fields are copied, and no chunk is empty.
def test_every_chunk_has_its_fields(corpus):
    problems = []
    for doc in corpus:
        parsed = doc["parsed"]
        for number, chunk in enumerate(doc["chunks"], start=1):
            if chunk["id"] != f"{parsed['doc_id']}_{number}":
                problems.append(f"{doc['name']} chunk {number}: id {chunk['id']}")
            if (chunk["doc_key"], chunk["company"], chunk["format"]) != (parsed["doc_key"], parsed["company"], parsed["format"]):
                problems.append(f"{doc['name']} chunk {number}: document fields do not match")
            if not chunk["text"].strip():
                problems.append(f"{doc['name']} chunk {number}: empty text")
    report(problems)
