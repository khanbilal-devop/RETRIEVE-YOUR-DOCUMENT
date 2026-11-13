"""Tests for the parsing runner (parsing/src/runner.py).

The runner reads the registry, parses each listed Markdown file, and saves one JSON
file per document. These tests build a tiny fake dataset and registry in a temporary
folder, so they never touch the real data. Tests are grouped by what they protect,
and each group and each test has a plain-English comment.
"""

import json

import pytest

from parsing.src import runner


# ---- helpers used by the tests ---------------------------------------------


@pytest.fixture(autouse=True)
def no_sample_list(monkeypatch):
    """Turn the temporary test list off for every test, so the tests do not depend on its current value."""
    monkeypatch.setattr(runner, "SAMPLE_FILES", None)


def make_corpus(tmp_path, documents):
    """Build a tiny dataset and registry for the company "Acme".

    `documents` maps a file name (without .md) to its Markdown text. Returns the three
    folders the runner needs: the dataset, the registry and the (still empty) parsed folder.
    """
    dataset, registry, parsed = tmp_path / "dataset", tmp_path / "registry", tmp_path / "parsed"
    records = []
    for number, (name, text) in enumerate(documents.items(), start=1):
        file = dataset / "Acme" / "md" / f"{name}.md"
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")
        records.append({"doc_id": f"id{number}", "doc_key": [name.lower()], "path": f"Acme/md/{name}.md"})
    registry_file = registry / "Acme" / "md" / "registry.jsonl"
    registry_file.parent.mkdir(parents=True)
    registry_file.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return dataset, registry, parsed


# ============================================================================
# GROUP 1: reading the registry
# The runner finds the Markdown documents by reading the registry that the
# ingestion layer wrote.
# ============================================================================


# It reads the Markdown registry file of one company and returns its records.
def test_it_reads_the_markdown_registry_of_a_company(tmp_path):
    _, registry, _ = make_corpus(tmp_path, {"Guide": "# A\n", "Other": "# B\n"})
    records = runner.read_records(registry, "Acme")
    assert [r["doc_key"] for r in records] == [["guide"], ["other"]]


# A company that has no Markdown registry (only another format) is skipped, and no folder is made for it.
def test_a_company_without_a_markdown_registry_is_skipped(tmp_path):
    dataset, registry, parsed = make_corpus(tmp_path, {"Guide": "# A\n"})
    other = registry / "Beta" / "pdf" / "registry.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text("", encoding="utf-8")
    runner.run(dataset, registry, parsed)
    assert not (parsed / "Beta").exists()


# If the registry folder does not exist, the runner stops with a clear error.
def test_a_missing_registry_folder_raises(tmp_path):
    with pytest.raises(NotADirectoryError):
        runner.run(tmp_path, tmp_path / "nope", tmp_path / "parsed")


# ============================================================================
# GROUP 2: saving the parsed documents
# Each document is saved as one JSON file, named after its doc_key, holding the
# registry details and the parsed content.
# ============================================================================


# One JSON file is written per document, named after its doc_key, inside <company>/md.
def test_it_saves_one_file_per_document_named_by_doc_key(tmp_path):
    dataset, registry, parsed = make_corpus(tmp_path, {"Guide": "# A\n\ntext\n", "Other": "# B\n\ntext\n"})
    runner.run(dataset, registry, parsed)
    assert sorted(p.name for p in (parsed / "Acme" / "md").iterdir()) == ["guide.json", "other.json"]


# The saved document carries the registry details (doc_id, doc_key, path), the company, the format and the content.
def test_the_saved_document_keeps_the_registry_details(tmp_path):
    dataset, registry, parsed = make_corpus(tmp_path, {"Guide": "# A\n\ntext\n"})
    runner.run(dataset, registry, parsed)
    document = json.loads((parsed / "Acme" / "md" / "guide.json").read_text(encoding="utf-8"))
    assert set(document) == {"doc_id", "doc_key", "path", "company", "format", "content"}
    assert document["doc_id"] == "id1"
    assert document["doc_key"] == ["guide"]
    assert document["path"] == "Acme/md/Guide.md"
    assert (document["company"], document["format"]) == ("Acme", "md")
    assert document["content"]["sections"][0]["title"] == "A"


# The runner reports where each file went and how many blocks it holds.
def test_it_reports_what_was_saved_with_the_block_counts(tmp_path):
    dataset, registry, parsed = make_corpus(tmp_path, {"Guide": "# A\n\none\n\ntwo\n"})
    saved, failed = runner.run(dataset, registry, parsed)
    assert failed == []
    assert saved == [(parsed / "Acme" / "md" / "guide.json", 2)]


# Counting blocks includes the blocks inside every sub-section.
def test_count_blocks_counts_every_block_in_the_tree():
    tree = {
        "blocks": [{}],
        "sections": [{"blocks": [{}, {}], "sections": [{"blocks": [{}], "sections": []}]}],
    }
    assert runner.count_blocks(tree) == 4


# Running twice gives exactly the same files, and no half-written temporary files are left behind.
def test_running_twice_gives_identical_files(tmp_path):
    dataset, registry, parsed = make_corpus(tmp_path, {"Guide": "# A\n\ntext\n"})
    runner.run(dataset, registry, parsed)
    first = {p.name: p.read_bytes() for p in (parsed / "Acme" / "md").iterdir()}
    runner.run(dataset, registry, parsed)
    second = {p.name: p.read_bytes() for p in (parsed / "Acme" / "md").iterdir()}
    assert first == second
    assert list(parsed.rglob("*.tmp")) == []


# ============================================================================
# GROUP 3: failures
# One bad file must never stop the run. It is reported with a reason, and the
# other files are still parsed and saved.
# ============================================================================


# A file listed in the registry but missing on disk is reported, and the good file is still saved.
def test_a_missing_file_is_reported_and_the_run_continues(tmp_path):
    dataset, registry, parsed = make_corpus(tmp_path, {"Good": "# A\n\ntext\n", "Gone": "# B\n\ntext\n"})
    (dataset / "Acme" / "md" / "Gone.md").unlink()
    saved, failed = runner.run(dataset, registry, parsed)
    assert len(saved) == 1
    assert len(failed) == 1 and failed[0].startswith("Acme/md/Gone.md:")


# A file with no content at all is reported as "no content found" and is not saved.
def test_a_file_with_no_content_is_reported(tmp_path):
    dataset, registry, parsed = make_corpus(tmp_path, {"Empty": "   \n"})
    saved, failed = runner.run(dataset, registry, parsed)
    assert saved == []
    assert failed == ["Acme/md/Empty.md: no content found"]
    assert not (parsed / "Acme" / "md" / "empty.json").exists()


# ============================================================================
# GROUP 4: the temporary test list (SAMPLE_FILES)
# While we test, the runner can be limited to a few named files. Setting the list
# to None, which is the normal state, parses every Markdown file in the registry.
# ============================================================================


# With the list set, only the named files are parsed.
def test_only_the_files_in_the_test_list_are_parsed(tmp_path, monkeypatch):
    dataset, registry, parsed = make_corpus(tmp_path, {"Guide": "# A\n\ntext\n", "Other": "# B\n\ntext\n"})
    monkeypatch.setattr(runner, "SAMPLE_FILES", {"Acme": ["Guide.md"]})
    saved, failed = runner.run(dataset, registry, parsed)
    assert failed == []
    assert [p.name for p, _ in saved] == ["guide.json"]


# A company or file named in the test list that is not in the registry is reported, so a typo is visible.
def test_a_name_in_the_test_list_that_is_not_found_is_reported(tmp_path, monkeypatch):
    dataset, registry, parsed = make_corpus(tmp_path, {"Guide": "# A\n\ntext\n"})
    monkeypatch.setattr(runner, "SAMPLE_FILES", {"Acme": ["Nope.md"], "Other": ["x.md"]})
    _, failed = runner.run(dataset, registry, parsed)
    assert "Other: not in the registry" in failed
    assert "Acme/Nope.md: not in the registry" in failed


# With the list set to None, every Markdown file is parsed.
def test_with_no_test_list_every_file_is_parsed(tmp_path):
    dataset, registry, parsed = make_corpus(tmp_path, {"Guide": "# A\n\ntext\n", "Other": "# B\n\ntext\n"})
    saved, _ = runner.run(dataset, registry, parsed)
    assert len(saved) == 2


# ============================================================================
# GROUP 5: the command-line entry point
# main() reads the folder paths from the config, runs everything, and prints a summary.
# ============================================================================


# main() uses the three folders from the config and prints how many files were parsed and how many failed.
def test_main_prints_a_summary(tmp_path, monkeypatch, capsys):
    dataset, registry, parsed = make_corpus(tmp_path, {"Guide": "# A\n\ntext\n"})
    settings = {"paths": {"dataset_dir": str(dataset), "registry_dir": str(registry), "parsed_dir": str(parsed)}}
    monkeypatch.setattr(runner, "load_config", lambda: settings)

    code = runner.main()

    printed = capsys.readouterr().out
    assert code == 0
    assert "parsed 1, failed 0" in printed
    assert (parsed / "Acme" / "md" / "guide.json").exists()
