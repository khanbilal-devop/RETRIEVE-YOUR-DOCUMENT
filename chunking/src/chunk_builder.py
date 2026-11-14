"""Build the chunks of one parsed document.

The rules are written in chunking/docs/rules_for_chunking.md. Keep the two in step:
if a rule changes, change the document first, then this file.

Every block starts as its own chunk. Then three merge steps run, in this order:

1. Colon rule: a paragraph ending with ":" takes the block below it.
2. Note rule: a quote, or a paragraph that starts with Note, Disclaimer or Important,
   joins the block above it.
3. Small rule: a chunk under SMALL_CHUNK_WORDS words takes the block below it.

A chunk is saved as a dict:
``{"id", "text", "path", "doc_key", "company", "format", "locations"}``
where ``path`` is one line, the section titles joined with " > ".
"""

from __future__ import annotations

import re

# A chunk with fewer words than this joins the block below it. It is a starting
# value that we tune by testing retrieval.
SMALL_CHUNK_WORDS = 10

# The titles in a path are joined with this, so the path reads like a breadcrumb:
# "Main heading > Sub-heading > Sub-sub-heading". No section title contains ">".
PATH_SEPARATOR = " > "

# A paragraph starting with one of these words is a note.
_NOTE = re.compile(r"^\W*(note|disclaimer|important)\b", re.IGNORECASE)


# ---- small questions about a block -----------------------------------------


def _words(block: dict) -> int:
    """Words in a block's content (not counting the dashes and labels we add when writing the text)."""
    if block["type"] == "list":
        return sum(len(item["text"].split()) for item in block["items"])
    if block["type"] == "table":
        return sum(len(cell.split()) for cell in block["header"] + [c for row in block["rows"] for c in row])
    return len(block.get("text", "").split())


def _is_colon(block: dict) -> bool:
    """A paragraph that ends with a colon introduces what comes next."""
    return block["type"] == "paragraph" and block["text"].rstrip().endswith(":")


def _is_note(block: dict) -> bool:
    """A quote, or a full-sentence paragraph that starts with Note, Disclaimer or Important."""
    if block["type"] == "quote":
        return True
    # A paragraph ending with a colon is a label, and the colon rule handles it.
    return block["type"] == "paragraph" and bool(_NOTE.match(block["text"])) and not _is_colon(block)


# ---- step 0: list every block in reading order ------------------------------


def _flatten(section: dict, path: list[str], entries: list[dict]) -> list[dict]:
    """List every block in reading order, with its path and the section it sits in."""
    # The path is the titles of the sections above. A section with no title adds nothing.
    here = path + [section["title"]] if section["title"] else path
    for index, block in enumerate(section["blocks"]):
        entries.append(
            {
                "block": block,
                "path": here,
                "section": id(section),  # blocks with the same value sit in the same section
                "untitled": section["title"] is None,
                "first": index == 0,  # the first block of its section
            }
        )
    for child in section["sections"]:
        _flatten(child, here, entries)
    return entries


# ---- the three merge steps --------------------------------------------------
# A chunk is a list of entries (see _flatten). Merging joins neighbouring chunks.


def _merge_colon(chunks: list[list[dict]]) -> list[list[dict]]:
    """Step 1: a colon paragraph takes the one block below it, in the same section, and stops."""
    merged = []
    index = 0
    while index < len(chunks):
        current = chunks[index]
        index += 1
        last = current[-1]
        if _is_colon(last["block"]) and index < len(chunks) and chunks[index][0]["section"] == last["section"]:
            current = current + chunks[index]
            index += 1  # one block only: the merged chunk is not checked again
        merged.append(current)
    return merged


def _joins_above(above: dict, entry: dict) -> bool:
    """True if a note may join the block above it."""
    if above["section"] == entry["section"]:
        return True
    # Across a section, only a quote that starts an untitled section (after a --- divider).
    return entry["block"]["type"] == "quote" and entry["first"] and entry["untitled"]


def _merge_notes(chunks: list[list[dict]]) -> list[list[dict]]:
    """Step 2: a note or quote joins the chunk above it. A chunk takes at most one."""
    merged = []
    took_a_note = False  # whether the last chunk in `merged` already took one
    for chunk in chunks:
        first = chunk[0]
        if merged and not took_a_note and _is_note(first["block"]) and _joins_above(merged[-1][-1], first):
            merged[-1] = merged[-1] + chunk
            took_a_note = True
        else:
            merged.append(chunk)
            took_a_note = False
    return merged


def _merge_small(chunks: list[list[dict]]) -> list[list[dict]]:
    """Step 3: a small chunk takes the next chunk in its section, until it is big enough."""
    merged = []
    index = 0
    while index < len(chunks):
        current = chunks[index]
        index += 1
        while (
            sum(_words(entry["block"]) for entry in current) < SMALL_CHUNK_WORDS
            and index < len(chunks)
            and chunks[index][0]["section"] == current[-1]["section"]
        ):
            current = current + chunks[index]
            index += 1
        merged.append(current)
    return merged


# ---- writing the text of a chunk --------------------------------------------


def _render_list(block: dict) -> str:
    """One item per line with a dash. Numbered lists get their numbers back."""
    lines = []
    number = 0
    for item in block["items"]:
        parts = [part.strip() for part in item["text"].split("\n") if part.strip()]
        if not parts:
            continue  # an empty item has nothing to write
        indent = "  " * item["depth"]
        if block["ordered"] and item["depth"] == 0:
            number += 1
            marker = f"{number}."
        else:
            marker = "-"
        lines.append(f"{indent}{marker} {parts[0]}")
        # A line break inside an item: the lines after the first become sub-points.
        lines += [f"{indent}  - {part}" for part in parts[1:]]
    return "\n".join(lines)


def _render_table(block: dict) -> str:
    """One line per row, starting with a dash: "Label: value | Label: value". Empty cells stay empty."""
    lines = []
    for row in block["rows"]:
        pairs = [f"{label}: {value}" for label, value in zip(block["header"], row)]
        lines.append("- " + " | ".join(pairs))
    return "\n".join(lines)


def _render(block: dict) -> str:
    """The text of one block."""
    if block["type"] == "list":
        return _render_list(block)
    if block["type"] == "table":
        return _render_table(block)
    return block["text"].rstrip("\n")  # paragraph, quote, code and html are written as they are


# ---- the one function the rest of the project uses ---------------------------


def build_chunks(doc: dict) -> list[dict]:
    """Build the chunks of one parsed document, in reading order."""
    entries = _flatten(doc["content"], [], [])
    chunks = [[entry] for entry in entries]  # to start, one block is one chunk
    chunks = _merge_colon(chunks)
    chunks = _merge_notes(chunks)
    chunks = _merge_small(chunks)

    return [
        {
            "id": f"{doc['doc_id']}_{number}",
            "text": "\n".join(_render(entry["block"]) for entry in chunk),
            "path": PATH_SEPARATOR.join(chunk[0]["path"]),  # the path of the first block, on one line
            "doc_key": doc["doc_key"],
            "company": doc["company"],
            "format": doc["format"],
            "locations": [entry["block"]["location"] for entry in chunk],
        }
        for number, chunk in enumerate(chunks, start=1)
    ]
