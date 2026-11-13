"""Tests for the Markdown parser (parsing/src/md_parser.py).

Every test feeds a tiny piece of Markdown to the parser and checks what comes out.
The tests are grouped by the rule they protect. Each group and each test has a
plain-English comment, so anyone can see which rule a test belongs to and what
would be broken if it failed.
"""

from parsing.src.md_parser import nest_blocks, parse_md_file, parse_markdown


# ---- helpers used by the tests ---------------------------------------------


def parse(text):
    """Parse Markdown the way the pipeline does: find the blocks, then nest them into sections."""
    return nest_blocks(parse_markdown(text))


def child_titles(section):
    """The titles of the sections directly inside a section, in order."""
    return [child["title"] for child in section["sections"]]


def child(section, title):
    """The section directly inside `section` that has this title."""
    return next(c for c in section["sections"] if c["title"] == title)


def block_texts(section):
    """The text of each block directly inside a section. A list shows its items joined by ' | '."""
    return [
        " | ".join(item["text"] for item in block["items"]) if block["type"] == "list" else block["text"]
        for block in section["blocks"]
    ]


# ============================================================================
# GROUP 1: block types
# The parser turns each piece of Markdown into one block with a type. These
# tests check that every kind of block is recognised and keeps its content.
# ============================================================================


# A normal line of text becomes a "paragraph" block.
def test_a_paragraph_becomes_a_paragraph_block():
    blocks = parse_markdown("Just some text.\n")
    assert [(b["type"], b["text"]) for b in blocks] == [("paragraph", "Just some text.")]


# Lines starting with "-" become one "list" block that is not numbered.
def test_bullets_become_an_unordered_list_block():
    (block,) = parse_markdown("- one\n- two\n")
    assert block["type"] == "list" and block["ordered"] is False
    assert [item["text"] for item in block["items"]] == ["one", "two"]


# Lines starting with "1." become a list block marked as numbered.
def test_numbers_become_an_ordered_list_block():
    (block,) = parse_markdown("1. first\n2. second\n")
    assert block["type"] == "list" and block["ordered"] is True
    assert [item["text"] for item in block["items"]] == ["first", "second"]


# A bullet inside a bullet stays in the same list block, one level deeper (depth 1).
def test_a_nested_bullet_has_a_deeper_depth():
    (block,) = parse_markdown("- parent\n  - child\n")
    assert [(item["text"], item["depth"]) for item in block["items"]] == [("parent", 0), ("child", 1)]


# A table becomes one "table" block with a header row and a list of data rows.
def test_a_table_becomes_a_table_block():
    (block,) = parse_markdown("| Name | Price |\n|---|---|\n| Edge | 20 |\n")
    assert block["type"] == "table"
    assert block["header"] == ["Name", "Price"]
    assert block["rows"] == [["Edge", "20"]]


# A line starting with ">" becomes a "quote" block.
def test_a_quote_becomes_a_quote_block():
    (block,) = parse_markdown("> Note: be careful\n")
    assert (block["type"], block["text"]) == ("quote", "Note: be careful")


# A fenced code block becomes a "code" block that keeps the code as written.
def test_a_code_fence_becomes_a_code_block():
    (block,) = parse_markdown("```\nprint(1)\n```\n")
    assert block["type"] == "code"
    assert block["text"].strip() == "print(1)"


# Raw HTML written in the Markdown stays as an "html" block with its text untouched.
def test_raw_html_stays_as_an_html_block():
    root = parse("<div>hello</div>\n")
    (block,) = root["blocks"]
    assert block["type"] == "html"
    assert "<div>hello</div>" in block["text"]


# ============================================================================
# GROUP 2: the section tree
# Each heading becomes a section that holds its own blocks and the sections
# under it. These tests check how headings nest, including odd cases.
# ============================================================================


# A heading becomes a section with its title, its level and the blocks under it.
# The whole file is held by a top section with no title and level 0.
def test_a_heading_becomes_a_section_with_its_blocks():
    root = parse("# Title\n\nHello\n")
    assert (root["title"], root["level"], root["location"]) == (None, 0, None)
    (section,) = root["sections"]
    assert (section["title"], section["level"]) == ("Title", 1)
    assert block_texts(section) == ["Hello"]


# A deeper heading goes inside the heading above it, level by level.
def test_deeper_headings_nest_inside_their_parent():
    root = parse("# A\n## B\n### C\n")
    a = child(root, "A")
    b = child(a, "B")
    assert child_titles(b) == ["C"]


# Two headings of the same level sit side by side under the same parent.
def test_headings_of_the_same_level_are_siblings():
    root = parse("# A\n## B\n## C\n")
    assert child_titles(child(root, "A")) == ["B", "C"]


# When a shallower heading comes back, the deeper sections close and it joins their parent.
def test_a_shallower_heading_closes_the_deeper_sections():
    root = parse("# A\n## B\n### C\n## D\n")
    a = child(root, "A")
    assert child_titles(a) == ["B", "D"]
    assert child_titles(child(a, "B")) == ["C"]


# Rule: if a level is skipped (a ### right after a #), the heading goes under the nearest
# heading above with a smaller level, and it keeps its real level number.
def test_a_skipped_level_goes_under_the_nearest_shallower_heading():
    root = parse("# A\n### C\n## B\n")
    a = child(root, "A")
    assert child_titles(a) == ["C", "B"]
    assert child(a, "C")["level"] == 3


# A file may start with a heading deeper than level 1. It simply goes under the top section.
def test_the_first_heading_can_be_deeper_than_level_one():
    root = parse("## Only\n\ntext\n")
    (section,) = root["sections"]
    assert (section["title"], section["level"]) == ("Only", 2)


# Rule: text before the first heading goes into the top section, which has no title.
def test_text_before_the_first_heading_goes_in_the_top_section():
    root = parse("Intro line.\n\n# A\n")
    assert block_texts(root) == ["Intro line."]
    assert child_titles(root) == ["A"]


# Rule: a heading with nothing directly under it stays as a section with an empty block list.
def test_a_heading_with_nothing_under_it_is_an_empty_section():
    root = parse("# A\n## B\n\ntext\n")
    a = child(root, "A")
    assert a["blocks"] == []
    assert child_titles(a) == ["B"]


# Rule: text that comes after a sub-section stays with that sub-section, not with the parent.
def test_text_after_a_sub_section_stays_with_that_sub_section():
    root = parse("# A\n\na text\n\n## B\n\nb text\n\nlate text\n")
    a = child(root, "A")
    assert block_texts(a) == ["a text"]
    assert block_texts(child(a, "B")) == ["b text", "late text"]


# ============================================================================
# GROUP 3: plain text
# The text of every block is plain words. Formatting marks are removed, links keep
# their address, and line breaks the author wrote are kept.
# ============================================================================


# Rule: the marks for bold, italic and inline code are removed and the words are kept.
def test_bold_italic_and_code_marks_are_removed():
    (block,) = parse_markdown("This is **bold**, *italic* and `code`.\n")
    assert block["text"] == "This is bold, italic and code."


# The same clean-up applies to heading text.
def test_marks_are_removed_from_headings():
    root = parse("## Why **Choose** us\n")
    assert child_titles(root) == ["Why Choose us"]


# The same clean-up applies to list items and to table cells.
def test_marks_are_removed_from_list_items_and_table_cells():
    list_block, table_block = parse_markdown("- **Label:** value\n\n| **Edge** | 20 |\n|---|---|\n| x | y |\n")
    assert list_block["items"][0]["text"] == "Label: value"
    assert table_block["header"] == ["Edge", "20"]


# Rule: a link keeps both its text and its address, written as "text (address)".
def test_a_link_keeps_its_text_and_its_address():
    (block,) = parse_markdown("See [the site](https://example.com) now.\n")
    assert block["text"] == "See the site (https://example.com) now."


# A link whose text is already the address still repeats the address. We keep both on purpose.
def test_a_link_whose_text_is_its_address_repeats_it():
    (block,) = parse_markdown("[a.com](https://a.com)\n")
    assert block["text"] == "a.com (https://a.com)"


# Rule: a line break the author wrote (two spaces at the end of a line) is kept as a new line.
def test_a_hard_line_break_is_kept():
    (block,) = parse_markdown("Line one  \nLine two\n")
    assert block["text"] == "Line one\nLine two"


# Rule: a plain new line inside a paragraph is also kept as a new line.
def test_a_plain_new_line_inside_a_paragraph_is_kept():
    (block,) = parse_markdown("Line one\nLine two\n")
    assert block["text"] == "Line one\nLine two"


# ============================================================================
# GROUP 4: the "---" divider
# A "---" line normally changes nothing. The exception: when content follows it
# before the next heading, that content starts a new section with no title.
# ============================================================================


# Rule: content after a "---" starts a new section with no title. Its location is the line of the "---".
def test_content_after_a_divider_starts_an_untitled_section():
    root = parse("# A\n\nfirst\n\n---\n\nsecond\n")
    assert child_titles(root) == ["A", None]
    untitled = root["sections"][1]
    assert block_texts(untitled) == ["second"]
    assert untitled["location"] == {"line": 5}
    assert block_texts(child(root, "A")) == ["first"]


# The new section sits next to the one before it: same level and same parent heading.
def test_the_untitled_section_has_the_same_level_and_parent():
    root = parse("# A\n\n## B\n\nbody\n\n---\n\nnote\n")
    a = child(root, "A")
    assert child_titles(a) == ["B", None]
    untitled = a["sections"][1]
    assert untitled["level"] == 2
    assert untitled["location"] == {"line": 7, "heading": "A"}


# A "---" right before a heading changes nothing, because the heading starts a section anyway.
def test_a_divider_before_a_heading_changes_nothing():
    root = parse("# A\n\ntext\n\n---\n\n# B\n")
    assert child_titles(root) == ["A", "B"]


# A "---" at the very end of the file has nothing after it, so it changes nothing.
def test_a_divider_at_the_end_of_the_file_changes_nothing():
    root = parse("# A\n\ntext\n\n---\n")
    assert child_titles(root) == ["A"]
    assert block_texts(child(root, "A")) == ["text"]


# Rule: a "---" straight after a heading with nothing under it is ignored. The content
# that follows stays in that heading's section.
def test_a_divider_straight_after_a_heading_is_ignored():
    root = parse("# A\n\n---\n\nintro\n")
    assert child_titles(root) == ["A"]
    assert block_texts(child(root, "A")) == ["intro"]


# In the top section (before any heading) there is nothing to split from, so a "---" does nothing.
def test_a_divider_in_the_top_section_does_nothing():
    root = parse("Intro\n\n---\n\nStill intro\n\n# A\n")
    assert block_texts(root) == ["Intro", "Still intro"]
    assert child_titles(root) == ["A"]


# Inside a <details> section a "---" does not split it. The details pair is one section.
def test_a_divider_inside_details_does_nothing():
    root = parse("<details>\n<summary>Group</summary>\n\none\n\n---\n\ntwo\n</details>\n")
    (group,) = root["sections"]
    assert group["title"] == "Group"
    assert block_texts(group) == ["one", "two"]


# Two "---" lines in a row make only one new section, not two.
def test_two_dividers_in_a_row_make_one_section():
    root = parse("# A\n\ntext\n\n---\n\n---\n\nnote\n")
    assert child_titles(root) == ["A", None]


# The "---" itself never shows up as a block in the output.
def test_the_divider_never_appears_as_a_block():
    root = parse("# A\n\ntext\n\n---\n\nnote\n")
    kinds = [b["type"] for s in [child(root, "A"), root["sections"][1]] for b in s["blocks"]]
    assert kinds == ["paragraph", "paragraph"]


# ============================================================================
# GROUP 5: <details> sections
# Rule: each <details> ... </details> pair is one section. A text tag right after
# <details> gives the title, tags like <strong> are stripped, and the content inside
# is parsed as normal Markdown.
# ============================================================================


# A <details> pair becomes a section titled by its <summary>. It sits one level below the
# section it is in, and its location is the line of the <details> tag.
def test_details_becomes_a_section_titled_by_its_summary():
    root = parse("# Parent\n\n<details>\n<summary>Engine</summary>\n\n- item one\n- item two\n</details>\n")
    parent = child(root, "Parent")
    engine = child(parent, "Engine")
    assert engine["level"] == 2
    assert engine["location"] == {"line": 3, "heading": "Parent"}
    assert block_texts(engine) == ["item one | item two"]


# Tags inside the summary, like <strong>, are stripped, and HTML entities are turned into characters.
def test_tags_inside_the_summary_are_stripped():
    root = parse("<details>\n<summary><strong>1. Engine &amp; Transmission</strong></summary>\n\n- a\n</details>\n")
    assert child_titles(root) == ["1. Engine & Transmission"]


# A <p> tag right after <details> can give the title too, not only <summary>.
def test_a_p_tag_can_give_the_title():
    root = parse("<details>\n<p><strong>Engine</strong> details</p>\n\n- a\n</details>\n")
    assert child_titles(root) == ["Engine details"]


# Rule: heading tags (<h1> to <h6>) are not used as a title. They are sections of their own.
# So the details section has no title and the heading becomes a section inside it.
def test_heading_tags_are_not_used_as_a_details_title():
    root = parse("<details>\n<h2>Inner</h2>\n\n- a\n</details>\n")
    (group,) = root["sections"]
    assert group["title"] is None
    assert child_titles(group) == ["Inner"]


# If no text tag follows <details>, the section has no title and the text becomes a normal block.
def test_details_without_a_title_tag_has_no_title():
    root = parse("<details>\nPlain text first.\n\n- a\n</details>\n")
    (group,) = root["sections"]
    assert group["title"] is None
    assert block_texts(group) == ["Plain text first.", "a"]


# Everything inside <details> is parsed as normal Markdown, so bold marks are removed there too.
def test_content_inside_details_is_parsed_as_markdown():
    root = parse("<details>\n<summary>T</summary>\n\nSome **bold** text.\n</details>\n")
    assert block_texts(child(root, "T")) == ["Some bold text."]


# It also works when the whole <details> is written with no blank lines, as one HTML block.
def test_details_written_in_one_block_still_works():
    root = parse("<details><summary>Tight</summary>\nSome **bold** text.\n</details>\n")
    assert block_texts(child(root, "Tight")) == ["Some bold text."]


# A <details> inside another <details> becomes a section inside that section.
def test_nested_details_make_nested_sections():
    root = parse(
        "<details><summary>Outer</summary>\nOuter text.\n<details>\n<summary>Inner</summary>\n\nInner text.\n"
        "</details>\n</details>\n"
    )
    outer = child(root, "Outer")
    assert block_texts(outer) == ["Outer text."]
    assert block_texts(child(outer, "Inner")) == ["Inner text."]


# Text written after </details> goes back to the section the <details> was in.
def test_text_after_the_closing_tag_returns_to_the_outer_section():
    root = parse("# A\n\n<details>\n<summary>D</summary>\n\ninside\n</details>\n\nafter\n")
    a = child(root, "A")
    assert block_texts(a) == ["after"]
    assert block_texts(child(a, "D")) == ["inside"]


# Rule: a heading inside <details> stays inside it. Only </details> closes the section.
def test_a_heading_inside_details_stays_inside_it():
    root = parse("# Guide\n\n<details>\n<summary>Group</summary>\n\n## Inside\n\ntext\n</details>\n\n## Outside\n")
    guide = child(root, "Guide")
    assert child_titles(guide) == ["Group", "Outside"]
    assert child_titles(child(guide, "Group")) == ["Inside"]


# ============================================================================
# GROUP 6: HTML headings
# Rule: an HTML heading tag (<h1> to <h6>) written in the Markdown becomes a
# heading, the same as a "#" line, so it starts a section.
# ============================================================================


# An <h2> tag becomes a level-2 section with the blocks that follow it.
def test_an_html_heading_becomes_a_section():
    root = parse("# Guide\n\n<h2>Engine</h2>\n\nPetrol.\n")
    engine = child(child(root, "Guide"), "Engine")
    assert engine["level"] == 2
    assert block_texts(engine) == ["Petrol."]


# Tags inside the heading are stripped and entities are turned into characters.
def test_tags_inside_an_html_heading_are_stripped():
    root = parse("<h3><strong>Bold</strong> title &amp; more</h3>\n")
    assert child_titles(root) == ["Bold title & more"]


# Other HTML written next to a heading tag stays as an html block inside that section.
def test_other_html_next_to_a_heading_tag_stays_html():
    root = parse("<h2>Engine</h2>\n<p>raw html text</p>\n")
    engine = child(root, "Engine")
    (block,) = engine["blocks"]
    assert block["type"] == "html"
    assert "<p>raw html text</p>" in block["text"]


# ============================================================================
# GROUP 7: a heading inside a list item
# Rule: a heading written inside a list item (like "1. ### Title") acts as a normal
# heading. The list is split around it, and the bullets under it form their own list.
# ============================================================================


# Each numbered item with a heading becomes its own section, holding its own bullet list.
def test_a_heading_inside_a_list_item_becomes_a_section_with_its_own_list():
    root = parse("## Steps\n\n1. ### First\n   - a\n   - b\n2. ### Second\n   - c\n")
    steps = child(root, "Steps")
    assert child_titles(steps) == ["First", "Second"]
    assert block_texts(child(steps, "First")) == ["a | b"]
    assert block_texts(child(steps, "Second")) == ["c"]


# The bullets are no longer nested: they start at depth 0, and they are not marked as numbered.
def test_the_bullets_under_such_a_heading_start_at_depth_zero():
    root = parse("## Steps\n\n1. ### First\n   - a\n   - b\n")
    (block,) = child(child(root, "Steps"), "First")["blocks"]
    assert block["ordered"] is False
    assert [item["depth"] for item in block["items"]] == [0, 0]


# The empty numbered wrapper items are dropped, so the parent section keeps no leftover list.
def test_the_empty_wrapper_items_are_dropped():
    root = parse("## Steps\n\n1. ### First\n   - a\n")
    assert child(root, "Steps")["blocks"] == []


# A normal list is not cleaned up: an empty parent item that only holds a nested bullet stays.
def test_an_empty_parent_item_in_a_normal_list_is_kept():
    (block,) = parse_markdown("- * child\n")
    assert [(item["text"], item["depth"]) for item in block["items"]] == [("", 0), ("child", 1)]


# ============================================================================
# GROUP 8: locations
# Every block and section records where it came from: the line in the file, plus
# the heading it sits under (its immediate parent). With no parent, only the line.
# ============================================================================


# A block under a heading records its line and the title of that heading.
def test_a_block_records_its_line_and_its_parent_heading():
    root = parse("# A\n\ntext\n")
    (block,) = child(root, "A")["blocks"]
    assert block["location"] == {"line": 3, "heading": "A"}


# A heading at the top has no parent heading, so its location is only the line.
def test_a_top_level_heading_has_only_a_line():
    root = parse("# A\n")
    assert child(root, "A")["location"] == {"line": 1}


# A sub-heading records the heading above it as its parent.
def test_a_sub_heading_names_its_parent():
    root = parse("# A\n## B\n")
    assert child(child(root, "A"), "B")["location"] == {"line": 2, "heading": "A"}


# A block before the first heading has no parent, so its location is only the line.
# The top section itself has no location at all.
def test_a_block_before_the_first_heading_has_only_a_line():
    root = parse("Intro\n\n# A\n")
    assert root["location"] is None
    assert root["blocks"][0]["location"] == {"line": 1}


# A block inside an untitled section has no parent title to name, so its location is only the line.
def test_a_block_in_an_untitled_section_has_only_a_line():
    root = parse("# A\n\nfirst\n\n---\n\nsecond\n")
    (block,) = root["sections"][1]["blocks"]
    assert block["location"] == {"line": 7}


# ============================================================================
# GROUP 9: reading a file
# parse_md_file reads a Markdown file from disk and returns its section tree.
# ============================================================================


# Reading a file gives the same result as parsing its text.
def test_parse_md_file_reads_a_file(tmp_path):
    file = tmp_path / "guide.md"
    file.write_text("# Title\n\nHello\n", encoding="utf-8")
    root = parse_md_file(file)
    assert block_texts(child(root, "Title")) == ["Hello"]


# Some editors put an invisible marker at the start of a file. It must not end up in the first title.
def test_a_byte_order_mark_at_the_start_is_ignored(tmp_path):
    file = tmp_path / "guide.md"
    file.write_bytes(b"\xef\xbb\xbf# Title\n")
    assert child_titles(parse_md_file(file)) == ["Title"]
