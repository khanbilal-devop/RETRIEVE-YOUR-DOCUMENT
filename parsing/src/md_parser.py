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

# The library's parser. "commonmark" means the standard Markdown rules.
# Tables are not part of standard Markdown, so we switch them on.
_PARSER = MarkdownIt("commonmark").enable("table")


def _block(kind: str, token, **fields) -> dict:
    # token.map holds [first line, last line] of the block, counting from 0.
    # We add 1 so the line number matches what you see in the editor.
    line = token.map[0] + 1 if token.map else None
    # Build the block: its type, its line, then the extra fields (level, text, ...).
    return {"type": kind, "line": line, **fields}


def parse_markdown(text: str) -> list[dict]:
    """Turn Markdown text into a list of blocks."""
    # The library does not return a tree. It returns a flat list of "tokens".
    # A heading comes as three tokens in a row:
    #   heading_open -> inline (holds the heading text) -> heading_close
    tokens = _PARSER.parse(text)

    # The result: the blocks we build, in reading order.
    blocks: list[dict] = []

    # Things we remember while walking the tokens.
    list_block = None  # the outermost list that is open right now
    list_depth = 0  # how deep inside lists we are (0 = not in a list)
    items: list[dict] = []  # list items that are open, innermost last
    quote_depth = 0  # how deep inside quotes we are (0 = not in a quote)
    table = None  # the table being built
    row: list[str] = []  # the table row being built
    in_head = False  # True while we are inside the table header

    # Walk through the tokens one by one, from first to last.
    for index, token in enumerate(tokens):
        kind = token.type
        # The next token. For headings, paragraphs and table cells it holds the text.
        following = tokens[index + 1] if index + 1 < len(tokens) else None

        # A heading starts here. token.tag is "h1", "h2", ... so [1] is the level number.
        # following.content is the heading text exactly as written (** marks included).
        if kind == "heading_open":
            blocks.append(_block("heading", token, level=int(token.tag[1]), text=following.content))

        # A paragraph starts here.
        elif kind == "paragraph_open":
            if items:
                # We are inside a list item, so this text belongs to that item.
                items[-1]["text"] = (items[-1]["text"] + " " + following.content).strip()
            else:
                # Otherwise it is a normal paragraph, or a quote if we are inside one.
                blocks.append(_block("quote" if quote_depth else "paragraph", token, text=following.content))

        # A list starts here (bullet or numbered).
        elif kind in ("bullet_list_open", "ordered_list_open"):
            if list_depth == 0:
                # This is the outermost list, so start a new list block.
                list_block = _block("list", token, ordered=kind == "ordered_list_open", items=[])
            # A list inside a list does not get its own block. Its items go in the same one.
            list_depth += 1
        # One list item starts here.
        elif kind == "list_item_open":
            # depth is 0 for the top level, 1 for an item in a list inside a list, and so on.
            item = {"text": "", "depth": list_depth - 1}
            list_block["items"].append(item)
            items.append(item)  # remember it as open, so paragraph text can be added to it
        # The list item ends.
        elif kind == "list_item_close":
            items.pop()
        # A list ends here.
        elif kind in ("bullet_list_close", "ordered_list_close"):
            list_depth -= 1
            if list_depth == 0:
                # The outermost list is finished, so save it.
                blocks.append(list_block)

        # Quotes (lines starting with >). Paragraphs inside become "quote" blocks.
        elif kind == "blockquote_open":
            quote_depth += 1
        elif kind == "blockquote_close":
            quote_depth -= 1

        # A table starts here. We fill in the header and the rows as we go.
        elif kind == "table_open":
            table = _block("table", token, header=[], rows=[])
        # The header part of the table starts or ends.
        elif kind == "thead_open":
            in_head = True
        elif kind == "thead_close":
            in_head = False
        # A table row starts here, so begin with an empty list of cells.
        elif kind == "tr_open":
            row = []
        # A table cell starts here (th = header cell, td = normal cell). Add its text to the row.
        elif kind in ("th_open", "td_open"):
            row.append(following.content)
        # The row ends. Save it as the header or as a normal row.
        elif kind == "tr_close":
            if in_head:
                table["header"] = row
            else:
                table["rows"].append(row)
        # The table ends, so save it.
        elif kind == "table_close":
            blocks.append(table)

        # A code block (fenced with ``` or indented). The code is in token.content itself.
        elif kind in ("fence", "code_block"):
            blocks.append(_block("code", token, text=token.content))

        # Raw HTML written directly in the Markdown, such as <details>. Kept as it is.
        elif kind == "html_block":
            blocks.append(_block("html", token, text=token.content))

    return blocks


def parse_md_file(path: Path | str) -> list[dict]:
    """Read a Markdown file and return its blocks."""
    # "utf-8-sig" reads normal UTF-8 and also skips the hidden marker some editors put at the start.
    with open(path, encoding="utf-8-sig") as handle:
        return parse_markdown(handle.read())
