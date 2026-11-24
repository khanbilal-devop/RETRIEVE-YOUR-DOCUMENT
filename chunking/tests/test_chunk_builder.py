"""Tests for the chunk builder (chunking/src/chunk_builder.py).

Each test builds a tiny parsed document by hand, runs ``build_chunks`` on it, and
compares the chunks with what the rules in chunking/docs/rules_for_chunking.md say
they should be. The documents are made up, so the tests never touch the real data.
Tests are grouped by rule, and each group and each test has a plain-English comment.
"""

from itertools import count

import pytest

from chunking.src.chunk_builder import build_chunks


# ---- helpers used by the tests ---------------------------------------------

_lines = count(1)  # every block gets its own line number, like in a real file


def _location():
    return {"line": next(_lines), "heading": None}


def para(text):
    """A paragraph block."""
    return {"type": "paragraph", "location": _location(), "text": text}


def quote(text):
    """A quote block."""
    return {"type": "quote", "location": _location(), "text": text}


def bullets(*items, ordered=False):
    """A list block. An item is a string, or a (string, depth) pair for a nested item."""
    entries = [{"text": item, "depth": 0} if isinstance(item, str) else {"text": item[0], "depth": item[1]} for item in items]
    return {"type": "list", "location": _location(), "ordered": ordered, "items": entries}


def table(header, rows):
    """A table block."""
    return {"type": "table", "location": _location(), "header": header, "rows": rows}


def section(title, blocks=(), sections=()):
    """A section. A title of None makes an untitled section (the kind a --- divider makes)."""
    return {"title": title, "level": 2, "location": None, "blocks": list(blocks), "sections": list(sections)}


def document(blocks=(), sections=()):
    """A parsed document. The top section has no title."""
    return {
        "doc_id": "d1",
        "doc_key": ["doc"],
        "company": "Acme",
        "format": "md",
        "content": section(None, blocks, sections),
    }


def long(tag):
    """A paragraph text of 14 words, so it is never small. It does not end with a colon."""
    return f"{tag} is a sentence with more than ten words so it is never small."


def intro(tag):
    """A paragraph text of 12 words that ends with a colon."""
    return f"{tag} is an introduction sentence with more than ten words in it:"


def texts(doc):
    """The text of every chunk the builder makes for a document."""
    return [chunk["text"] for chunk in build_chunks(doc)]


# ============================================================================
# GROUP 1: the starting point (rules 1 and 2)
# Every block starts as its own chunk. A section with no blocks makes no chunk.
# ============================================================================


# Two long paragraphs in a row stay two chunks.
def test_each_block_is_its_own_chunk():
    doc = document(blocks=[para(long("First")), para(long("Second"))])
    assert texts(doc) == [long("First"), long("Second")]


# A list is one block, so it stays in one chunk, one item per line.
def test_a_list_stays_in_one_chunk():
    doc = document(blocks=[bullets("one two three four", "five six seven eight", "nine ten eleven twelve")])
    assert texts(doc) == ["- one two three four\n- five six seven eight\n- nine ten eleven twelve"]


# A table is one block, so it stays in one chunk, one row per line.
def test_a_table_stays_in_one_chunk():
    doc = document(blocks=[table(["Name", "City"], [["Asha Rao", "Pune"], ["Dev Mehta", "Delhi"], ["Sam Lee", "Goa"]])])
    assert len(build_chunks(doc)) == 1


# A heading with nothing directly under it makes no chunk. Its title is still in the path below it.
def test_a_section_with_no_blocks_makes_no_chunk():
    doc = document(sections=[section("Outer", sections=[section("Inner", blocks=[para(long("Body"))])])])
    chunks = build_chunks(doc)
    assert len(chunks) == 1
    assert chunks[0]["path"] == "Outer > Inner"


# ============================================================================
# GROUP 2: the path (rule 3)
# The path is the section titles above the chunk, on one line, joined with " > ".
# ============================================================================


# Titles are joined with " > ", from the outside in.
def test_the_path_joins_the_titles_with_an_arrow():
    doc = document(sections=[section("Main", sections=[section("Sub", sections=[section("Deep", blocks=[para(long("Body"))])])])])
    assert build_chunks(doc)[0]["path"] == "Main > Sub > Deep"


# A section with no title (made by a --- divider) adds nothing to the path.
def test_an_untitled_section_adds_nothing_to_the_path():
    doc = document(sections=[section("Main", sections=[section(None, blocks=[para(long("Body"))])])])
    assert build_chunks(doc)[0]["path"] == "Main"


# Text above the first heading has an empty path.
def test_text_above_the_first_heading_has_an_empty_path():
    doc = document(blocks=[para(long("Body"))])
    assert build_chunks(doc)[0]["path"] == ""


# A merged chunk uses the path of its first block.
def test_a_merged_chunk_uses_the_path_of_its_first_block():
    doc = document(sections=[section("Main", blocks=[para(intro("Steps")), bullets("one two three", "four five six")])])
    assert build_chunks(doc)[0]["path"] == "Main"


# ============================================================================
# GROUP 3: the colon rule (rule 4)
# A paragraph or quote that ends with a colon joins the block below it,
# in the same section, and takes only that one block.
# ============================================================================


# A line ending with a colon joins the list below it.
def test_a_colon_paragraph_joins_the_list_below():
    doc = document(blocks=[para(intro("Controls")), bullets("tap once", "tap twice")])
    assert texts(doc) == [f"{intro('Controls')}\n- tap once\n- tap twice"]


# The rule works for a one-word label as well as a long sentence.
def test_the_colon_rule_works_at_any_length():
    doc = document(blocks=[para("Controls:"), bullets("tap once to play or pause the music", "tap twice to skip to the next track")])
    assert texts(doc) == ["Controls:\n- tap once to play or pause the music\n- tap twice to skip to the next track"]


# A quote that ends with a colon joins the list below it, like a paragraph does.
def test_a_colon_quote_joins_the_list_below():
    doc = document(blocks=[quote(intro("Colours")), bullets("red", "blue", "green")])
    assert texts(doc) == [f"{intro('Colours')}\n- red\n- blue\n- green"]


# A colon quote is a label, not a note, so it does not join the block above it.
def test_a_colon_quote_is_not_treated_as_a_note():
    doc = document(blocks=[para(long("Above")), quote(intro("Colours")), bullets("red", "blue", "green")])
    assert texts(doc) == [long("Above"), f"{intro('Colours')}\n- red\n- blue\n- green"]


# The colon line takes one block only, so it cannot start a chain that swallows the section.
def test_the_colon_rule_takes_one_block_only():
    doc = document(blocks=[para(intro("Steps")), para(long("First")), para(long("Second"))])
    assert texts(doc) == [f"{intro('Steps')}\n{long('First')}", long("Second")]


# If nothing is below the colon line in its section, it stays alone. It does not take a sub-section.
def test_a_colon_line_does_not_join_a_sub_section():
    doc = document(sections=[section("Main", blocks=[para(intro("Ways"))], sections=[section("One", blocks=[para(long("Body"))])])])
    chunks = build_chunks(doc)
    assert [c["text"] for c in chunks] == [intro("Ways"), long("Body")]
    assert chunks[1]["path"] == "Main > One"


# A colon line at the end of a section does not join the first block of the next section.
def test_a_colon_line_does_not_join_the_next_section():
    doc = document(sections=[section("A", blocks=[para(intro("Ways"))]), section("B", blocks=[para(long("Body"))])])
    assert texts(doc) == [intro("Ways"), long("Body")]


# A colon line that is the very last block of the document stays alone.
def test_a_colon_line_at_the_end_stays_alone():
    doc = document(blocks=[para(long("Body")), para(intro("Ways"))])
    assert texts(doc) == [long("Body"), intro("Ways")]


# ============================================================================
# GROUP 4: the note and quote rule (rule 5)
# A quote, or a paragraph starting with Note, Disclaimer or Important, joins the
# block above it. Exceptions and guards are tested below.
# ============================================================================


# A quote joins the block above it in the same section.
def test_a_quote_joins_the_block_above():
    doc = document(blocks=[table(["Class", "Bags"], [["Economy", "1 bag of 23 kg"], ["Premium", "2 bags of 23 kg"]]), quote(long("Extra"))])
    assert len(build_chunks(doc)) == 1


# A paragraph that starts with Note, Disclaimer or Important joins the block above it.
@pytest.mark.parametrize("word", ["Note", "Disclaimer", "Important"])
def test_a_note_paragraph_joins_the_block_above(word):
    doc = document(blocks=[para(long("Body")), para(f"{word}: {long('Extra')}")])
    assert texts(doc) == [f"{long('Body')}\n{word}: {long('Extra')}"]


# A word like Note in the middle of a sentence does not make a note.
def test_a_note_word_in_the_middle_is_not_a_note():
    doc = document(blocks=[para(long("Body")), para(f"See the Note below. {long('Extra')}")])
    assert len(build_chunks(doc)) == 2


# A note that ends with a colon is a label, so the colon rule wins and it joins the block below.
def test_a_note_ending_with_a_colon_is_a_label():
    doc = document(blocks=[para(long("Body")), para(f"Note: {intro('Steps')}"), bullets("one", "two", "three")])
    assert texts(doc) == [long("Body"), f"Note: {intro('Steps')}\n- one\n- two\n- three"]


# A quote that is the first block of a titled section stays alone, so the title is not hidden.
def test_a_quote_at_the_start_of_a_titled_section_stays_alone():
    doc = document(sections=[section("A", blocks=[para(long("Body"))]), section("B", blocks=[quote(long("Extra"))])])
    chunks = build_chunks(doc)
    assert [c["text"] for c in chunks] == [long("Body"), long("Extra")]
    assert chunks[1]["path"] == "B"


# The exception: a quote that starts an untitled section (after a --- divider) joins the chunk above it.
def test_a_quote_after_a_divider_joins_the_chunk_above():
    doc = document(sections=[section("A", blocks=[para(long("Body"))], sections=[section(None, blocks=[quote(long("Extra"))])])])
    chunks = build_chunks(doc)
    assert [c["text"] for c in chunks] == [f"{long('Body')}\n{long('Extra')}"]
    assert chunks[0]["path"] == "A"


# Only a quote crosses a divider. A note written as a plain paragraph does not.
def test_a_note_paragraph_after_a_divider_does_not_join():
    doc = document(sections=[section("A", blocks=[para(long("Body"))], sections=[section(None, blocks=[para(f"Note: {long('Extra')}")])])])
    assert len(build_chunks(doc)) == 2


# Guard: a chunk takes at most one note. A second quote in a row stays alone.
def test_a_chunk_takes_at_most_one_note():
    doc = document(blocks=[bullets("one two three four", "five six seven eight", "nine ten eleven twelve"), quote(long("First")), quote(long("Second"))])
    chunks = texts(doc)
    assert len(chunks) == 2
    assert chunks[1] == long("Second")


# ============================================================================
# GROUP 5: the small rule (rule 6)
# A chunk under 10 words joins the block below it. If it is last in its section,
# it joins the block above it. Alone in its section, it stays alone.
# ============================================================================


# A small block joins the block below it.
def test_a_small_block_joins_the_block_below():
    doc = document(blocks=[para("Starts at 20 lakh."), bullets("petrol model with a manual gearbox", "diesel model with an automatic gearbox")])
    assert len(build_chunks(doc)) == 1


# A small block joins the next block, and keeps joining until it has 10 words.
def test_a_small_block_keeps_joining_until_it_is_big_enough():
    doc = document(blocks=[para("One two three."), para("Four five six."), para(long("Body"))])
    assert texts(doc) == [f"One two three.\nFour five six.\n{long('Body')}"]


# A small block in the middle joins the block below it, and the block above is untouched.
def test_a_small_block_in_the_middle_joins_below_not_above():
    doc = document(blocks=[para(long("First")), para("Tiny."), para(long("Last"))])
    assert texts(doc) == [long("First"), f"Tiny.\n{long('Last')}"]


# A small block that is last in its section joins the block above it.
def test_a_small_last_block_joins_the_block_above():
    doc = document(blocks=[para(long("Body")), para("Prerequisites: None")])
    assert texts(doc) == [f"{long('Body')}\nPrerequisites: None"]


# A small block alone in its section has nothing above or below, so it stays alone.
def test_a_small_block_alone_in_its_section_stays_alone():
    doc = document(sections=[section("A", blocks=[para("Drive safe!")])])
    assert texts(doc) == ["Drive safe!"]


# A small block never joins a block in another titled section, above or below.
def test_a_small_block_never_joins_another_section():
    below = document(sections=[section("A", blocks=[para("Tiny.")]), section("B", blocks=[para(long("Body"))])])
    above = document(sections=[section("A", blocks=[para(long("Body"))]), section("B", blocks=[para("Tiny.")])])
    assert texts(below) == ["Tiny.", long("Body")]
    assert texts(above) == [long("Body"), "Tiny."]


# Exactly 10 words is not small, and 9 words is.
def test_ten_words_is_not_small_and_nine_is():
    ten = document(blocks=[para("one two three four five six seven eight nine ten"), para(long("Body"))])
    nine = document(blocks=[para("one two three four five six seven eight nine"), para(long("Body"))])
    assert len(build_chunks(ten)) == 2
    assert len(build_chunks(nine)) == 1


# Words are counted on the content, not on the dashes we add when writing a list.
def test_words_are_counted_on_the_content_not_the_dashes():
    doc = document(blocks=[bullets("a b", "c d", "e f", "g h", "i j"), para(long("Body"))])  # 10 words in 5 items
    assert len(build_chunks(doc)) == 2


# ============================================================================
# GROUP 6: writing the text of a chunk (section 5 of the rules)
# Lists and tables are written out as plain text.
# ============================================================================


# A paragraph and a quote are written as they are.
def test_paragraphs_and_quotes_are_written_as_they_are():
    doc = document(blocks=[para(long("Body")), quote(long("Extra"))])
    assert texts(doc) == [f"{long('Body')}\n{long('Extra')}"]


# A numbered list gets its numbers back.
def test_a_numbered_list_gets_its_numbers_back():
    doc = document(blocks=[bullets("Register the complaint now", "Upload the receipt of purchase", ordered=True)])
    assert texts(doc) == ["1. Register the complaint now\n2. Upload the receipt of purchase"]


# A nested item stays indented under its parent and always uses a dash. Only top-level items are numbered.
def test_a_nested_item_is_indented_and_uses_a_dash():
    doc = document(blocks=[bullets("Repairs for issues such as", ("Screen replacement", 1), "Battery swap at the store", ordered=True)])
    assert texts(doc) == ["1. Repairs for issues such as\n  - Screen replacement\n2. Battery swap at the store"]


# A line break inside an item makes the later lines sub-points under the first line.
def test_a_line_break_in_an_item_becomes_a_sub_point():
    doc = document(blocks=[bullets("Automatic Speed Regulation\nKeeps the car at a set speed", "Lane Assist keeps the car in its lane")])
    assert texts(doc) == ["- Automatic Speed Regulation\n  - Keeps the car at a set speed\n- Lane Assist keeps the car in its lane"]


# An empty list item is skipped.
def test_an_empty_list_item_is_skipped():
    doc = document(blocks=[bullets("first item of the list here", "", "second item of the list here")])
    assert texts(doc) == ["- first item of the list here\n- second item of the list here"]


# A table row is one line of "Label: value" pairs joined with " | ", and an empty cell stays empty.
def test_a_table_row_is_written_as_label_value_pairs():
    doc = document(blocks=[table(["Variant", "Trim", "Price"], [["Petrol", "Base", "6.5"], ["", "X", "7.0"]])])
    assert texts(doc) == ["- Variant: Petrol | Trim: Base | Price: 6.5\n- Variant:  | Trim: X | Price: 7.0"]


# A line break inside a table cell is written as " / ", so the row stays on one line.
def test_a_line_break_in_a_cell_is_written_as_a_slash():
    doc = document(blocks=[table(["Service", "Price"], [["Battery", "5 - 18 (petrol)\n50 - 160 (EV)"]])])
    assert texts(doc) == ["- Service: Battery | Price: 5 - 18 (petrol) / 50 - 160 (EV)"]


# ============================================================================
# GROUP 7: the fields of a chunk (section 8 of the rules)
# ============================================================================


# Ids are the doc id plus a number that counts from 1, in reading order.
def test_ids_count_from_one_in_reading_order():
    doc = document(blocks=[para(long("First")), para(long("Second")), para(long("Third"))])
    assert [c["id"] for c in build_chunks(doc)] == ["d1_1", "d1_2", "d1_3"]


# The document name, company and format are copied onto every chunk.
def test_every_chunk_carries_the_document_fields():
    doc = document(blocks=[para(long("Body"))])
    chunk = build_chunks(doc)[0]
    assert (chunk["doc_key"], chunk["company"], chunk["format"]) == (["doc"], "Acme", "md")


# A merged chunk keeps the location of every block in it.
def test_a_merged_chunk_keeps_every_location():
    first, second = para(intro("Steps")), bullets("one", "two", "three")
    doc = document(blocks=[first, second])
    assert build_chunks(doc)[0]["locations"] == [first["location"], second["location"]]


# Chunks come in reading order: a section's blocks, then its sub-sections, then the next section.
def test_chunks_come_in_reading_order():
    doc = document(
        sections=[
            section("A", blocks=[para(long("One"))], sections=[section("B", blocks=[para(long("Two"))]), section("C", blocks=[para(long("Three"))])]),
            section("D", blocks=[para(long("Four"))]),
        ]
    )
    assert texts(doc) == [long("One"), long("Two"), long("Three"), long("Four")]
