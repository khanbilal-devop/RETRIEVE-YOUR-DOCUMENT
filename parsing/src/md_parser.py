"""Parse Markdown text into typed blocks, using only what markdown-it-py gives us.

There are no custom rules yet. We look at the results first and add rules where
the structure comes out wrong.

Blocks come back in reading order. Each one is a dict with a ``type`` and the
``line`` it starts on:

- ``heading``: ``level`` and ``text``
- ``paragraph``: ``text``
- ``list``: ``ordered`` and ``items``. Each item has ``text`` and ``depth``.
- ``table``: ``header`` and ``rows``
- ``code``: ``text``
- ``quote``: ``text``
- ``html``: ``text``, the raw HTML as the library found it

``text`` is the source text of the block, so marks like ``**`` stay in.
"""

from __future__ import annotations

from pathlib import Path

from markdown_it import MarkdownIt

_PARSER = MarkdownIt("commonmark").enable("table")


def _block(kind: str, token, **fields) -> dict:
    line = token.map[0] + 1 if token.map else None
    return {"type": kind, "line": line, **fields}


def parse_markdown(text: str) -> list[dict]:
    """Turn Markdown text into a list of blocks."""
    tokens = _PARSER.parse(text)
    blocks: list[dict] = []
    list_block = None  # the outermost list that is open
    list_depth = 0
    items: list[dict] = []  # list items that are open, innermost last
    quote_depth = 0
    table = None
    row: list[str] = []
    in_head = False

    for index, token in enumerate(tokens):
        kind = token.type
        following = tokens[index + 1] if index + 1 < len(tokens) else None

        if kind == "heading_open":
            blocks.append(_block("heading", token, level=int(token.tag[1]), text=following.content))

        elif kind == "paragraph_open":
            if items:
                items[-1]["text"] = (items[-1]["text"] + " " + following.content).strip()
            else:
                blocks.append(_block("quote" if quote_depth else "paragraph", token, text=following.content))

        elif kind in ("bullet_list_open", "ordered_list_open"):
            if list_depth == 0:
                list_block = _block("list", token, ordered=kind == "ordered_list_open", items=[])
            list_depth += 1
        elif kind == "list_item_open":
            item = {"text": "", "depth": list_depth - 1}
            list_block["items"].append(item)
            items.append(item)
        elif kind == "list_item_close":
            items.pop()
        elif kind in ("bullet_list_close", "ordered_list_close"):
            list_depth -= 1
            if list_depth == 0:
                blocks.append(list_block)

        elif kind == "blockquote_open":
            quote_depth += 1
        elif kind == "blockquote_close":
            quote_depth -= 1

        elif kind == "table_open":
            table = _block("table", token, header=[], rows=[])
        elif kind == "thead_open":
            in_head = True
        elif kind == "thead_close":
            in_head = False
        elif kind == "tr_open":
            row = []
        elif kind in ("th_open", "td_open"):
            row.append(following.content)
        elif kind == "tr_close":
            if in_head:
                table["header"] = row
            else:
                table["rows"].append(row)
        elif kind == "table_close":
            blocks.append(table)

        elif kind in ("fence", "code_block"):
            blocks.append(_block("code", token, text=token.content))

        elif kind == "html_block":
            blocks.append(_block("html", token, text=token.content))

    return blocks


def parse_md_file(path: Path | str) -> list[dict]:
    """Read a Markdown file and return its blocks."""
    with open(path, encoding="utf-8-sig") as handle:
        return parse_markdown(handle.read())
