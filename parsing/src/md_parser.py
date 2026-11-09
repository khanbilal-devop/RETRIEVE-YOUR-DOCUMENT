"""Parse Markdown text into typed blocks, using only what markdown-it-py gives us.

There are few custom rules. We look at the results first and add rules where the
structure comes out wrong. So far: formatting marks are removed from text.

Blocks come back in reading order. Each one is a dict with a ``type`` and the
``line`` it starts on (``nest_blocks`` later swaps ``line`` for ``location``):

- ``heading``: ``level`` and ``text``
- ``paragraph``: ``text``
- ``list``: ``ordered`` and ``items``. Each item has ``text`` and ``depth``.
- ``table``: ``header`` and ``rows``
- ``code``: ``text``
- ``quote``: ``text``
- ``html``: ``text``, the raw HTML as the library found it

``text`` is plain words: the marks for bold, italic and inline code are removed.
Links keep both their text and their address, as ``text (address)``. Raw HTML
stays as it is. Line breaks inside a block are kept as new lines.

``parse_md_file`` returns these blocks nested by heading. Each heading becomes a
section: ``{"title", "level", "location", "blocks", "sections"}``. The blocks under a
heading go in its ``blocks`` and the headings below it go in its ``sections``. The
whole file is one top section with no title (``title`` None, ``level`` 0). It also
holds any text that comes before the first heading.

In the nested result every block and section has a ``location`` instead of a
``line``: the ``line`` where it starts, plus the ``heading`` it sits under (its
immediate parent). ``heading`` is left out when there is no parent, for example
for text before the first heading and for a top level heading.
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


def _plain_text(token) -> str:
    """Text of an inline token without the formatting marks.

    The library splits a line like ``Some **bold** text`` into pieces: some text,
    "bold start", the word, "bold end", more text. We keep the pieces that hold
    words and skip the ones that only mark bold or italic.
    """
    parts = []
    address = ""  # the web address of the link we are inside
    for child in token.children or []:
        if child.type in ("text", "code_inline"):
            parts.append(child.content)
        elif child.type in ("softbreak", "hardbreak"):
            parts.append("\n")
        elif child.type == "link_open":
            # A link keeps its text and its address: the text comes next, then " (address)".
            address = child.attrs["href"]
        elif child.type == "link_close":
            parts.append(f" ({address})")
        elif child.type == "image":
            parts.append(f"![{child.content}]({child.attrs['src']})")
        elif child.type == "html_inline":
            parts.append(child.content)  # raw HTML stays as it is
        # strong_open, strong_close, em_open and em_close are only marks, so they are skipped.
    return "".join(parts)


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
        # _plain_text gives the heading words without the ** marks.
        if kind == "heading_open":
            blocks.append(_block("heading", token, level=int(token.tag[1]), text=_plain_text(following)))

        # A paragraph starts here.
        elif kind == "paragraph_open":
            if items:
                # We are inside a list item, so this text belongs to that item.
                items[-1]["text"] = (items[-1]["text"] + " " + _plain_text(following)).strip()
            else:
                # Otherwise it is a normal paragraph, or a quote if we are inside one.
                blocks.append(_block("quote" if quote_depth else "paragraph", token, text=_plain_text(following)))

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
            row.append(_plain_text(following))
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


def _location(line: int, parent_title: str | None) -> dict:
    """Where something sits in the file: its line, and the heading right above it if there is one."""
    location = {"line": line}
    if parent_title is not None:
        location["heading"] = parent_title
    return location


def _with_location(block: dict, parent_title: str | None) -> dict:
    """Copy of a block with ``line`` swapped for ``location``."""
    fields = {key: value for key, value in block.items() if key not in ("type", "line")}
    return {"type": block["type"], "location": _location(block["line"], parent_title), **fields}


def nest_blocks(blocks: list[dict]) -> dict:
    """Group a flat list of blocks into sections, one per heading."""
    # The top section stands for the whole file. It has no title and level 0,
    # so no real heading (level 1 or more) can ever close it. It has no location either.
    root = {"title": None, "level": 0, "location": None, "blocks": [], "sections": []}
    # The sections that are open right now: the top section, then one per heading level we are inside.
    open_sections = [root]

    for block in blocks:
        if block["type"] == "heading":
            # Close every open section that is at the same level or deeper than this heading.
            # What is left on top is the nearest earlier heading with a smaller level: the parent.
            # This also covers a skipped level (a ### right after a #): the # stays the parent.
            while open_sections[-1]["level"] >= block["level"]:
                open_sections.pop()
            section = {
                "title": block["text"],
                "level": block["level"],
                # open_sections[-1] is the parent now, so its title is the heading above this one.
                "location": _location(block["line"], open_sections[-1]["title"]),
                "blocks": [],
                "sections": [],
            }
            open_sections[-1]["sections"].append(section)
            open_sections.append(section)
        else:
            # Anything that is not a heading belongs to the section that is open now.
            # Before the first heading, that is the top section.
            # Its location names that section's title as the heading it sits under.
            open_sections[-1]["blocks"].append(_with_location(block, open_sections[-1]["title"]))

    return root


def parse_md_file(path: Path | str) -> dict:
    """Read a Markdown file and return it as sections (see the top of this file)."""
    # "utf-8-sig" reads normal UTF-8 and also skips the hidden marker some editors put at the start.
    with open(path, encoding="utf-8-sig") as handle:
        return nest_blocks(parse_markdown(handle.read()))
