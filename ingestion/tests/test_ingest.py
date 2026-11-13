import hashlib
import json
import os
import zipfile

import pytest

from ingestion.src.ingest import (
    FORMATS,
    detect_format,
    ingest,
    is_system_file,
    match_key,
    matches,
    normalize_name,
)
from ingestion.src.runner import main

PDF = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n"
HTML_FRAGMENT = b'<h1 id="title">Title</h1>\n<p>Some text.</p>\n'
HTML_DOCUMENT = b"<!DOCTYPE html><html><body><h1>Hi</h1></body></html>"
MD = b"# Title\n\nSome text.\n"


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def put_zip(path, member):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, "<root/>")


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def folders(tmp_path):
    data = tmp_path / "datasets"
    data.mkdir()
    return data, tmp_path / "registry"


# ---- names ----------------------------------------------------------------


def test_escape_and_dash_become_a_hyphen():
    assert normalize_name("Fees #U2013 Overview.pdf") == "fees - overview"


def test_real_dash_and_escape_give_the_same_key():
    assert normalize_name("A – B.md") == normalize_name("A #U2013 B.docx")


def test_spaces_and_case_are_cleaned():
    assert normalize_name("  Account   Close  Guide .md") == "account close guide"
    assert normalize_name(" Aventro Motors- How to Change a Tyre.html") == "aventro motors- how to change a tyre"


def test_only_a_known_extension_is_dropped():
    assert normalize_name("Plan v2.0.md") == "plan v2.0"
    assert normalize_name("Plan v2.0") == "plan v2.0"


def test_surrogate_escape_is_left_alone():
    assert normalize_name("x#UD800y.md") == "x#ud800y"


def test_matches_any_name_in_doc_key():
    doc_key = ["personal loan", "personal loan information"]
    assert matches("Personal Loan Information.md", doc_key)
    assert matches(" personal  loan .md", doc_key)
    assert not matches("Home Loan.md", doc_key)


def test_collision_suffix_is_ignored_when_matching():
    assert match_key("Guide_2.md") == "guide"
    assert matches("Guide.md", ["guide_2"])


def test_system_files_are_flagged():
    for name in (".DS_Store", "Thumbs.db", "._guide.pdf", "~$draft.docx"):
        assert is_system_file(name)
    assert not is_system_file("Guide.pdf")


# ---- format detection -----------------------------------------------------


def detect(tmp_path, name, data=None, zip_member=None):
    path = tmp_path / name
    if zip_member:
        put_zip(path, zip_member)
    else:
        put(path, data)
    return detect_format(path)


def test_each_supported_format(tmp_path):
    assert detect(tmp_path, "a.pdf", PDF) == "pdf"
    assert detect(tmp_path, "a.docx", zip_member="word/document.xml") == "docx"
    assert detect(tmp_path, "a.pptx", zip_member="ppt/presentation.xml") == "pptx"
    assert detect(tmp_path, "a.html", HTML_FRAGMENT) == "html"
    assert detect(tmp_path, "b.html", HTML_DOCUMENT) == "html"
    assert detect(tmp_path, "a.md", MD) == "md"


def test_html_after_bom_and_blank_space(tmp_path):
    assert detect(tmp_path, "bom.html", b"\xef\xbb\xbf\n  <p>text</p>") == "html"


def test_format_comes_from_content_not_extension(tmp_path):
    assert detect(tmp_path, "misnamed.txt", PDF) == "pdf"
    assert detect(tmp_path, "misnamed.md", HTML_FRAGMENT) == "html"


def test_markdown_that_mentions_a_tag_stays_markdown(tmp_path):
    assert detect(tmp_path, "tags.md", b"# Title\n\nUse <br> for breaks.\n") == "md"


def test_plain_text_is_markdown_only_with_md_extension(tmp_path):
    assert detect(tmp_path, "notes.txt", MD) is None
    assert detect(tmp_path, "table.csv", b"a,b\n1,2\n") is None


def test_unsupported_and_broken_files(tmp_path):
    assert detect(tmp_path, "sheet.xlsx", zip_member="xl/workbook.xml") is None
    assert detect(tmp_path, "broken.docx", b"PK\x03\x04 not a zip") is None
    assert detect(tmp_path, "binary.md", b"\x00\x01\x02 binary") is None


# ---- ingest ---------------------------------------------------------------


def test_each_format_gets_its_own_registry_file(folders):
    data, out = folders
    put(data / "Acme/pdf/Guide.pdf", PDF)
    put_zip(data / "Acme/docx/Guide.docx", "word/document.xml")
    put_zip(data / "Acme/pptx/Guide.pptx", "ppt/presentation.xml")
    put(data / "Acme/html/Guide.html", HTML_FRAGMENT)
    put(data / "Acme/md/Guide.md", MD)

    result = ingest(data, out)

    assert result.registered == 5
    assert result.rejected == []
    names = sorted(p.name for p in (out / "Acme").iterdir())
    assert names == sorted(list(FORMATS) + ["rejected.jsonl"])
    for fmt in FORMATS:
        (record,) = read_jsonl(out / "Acme" / fmt / "registry.jsonl")
        assert record["doc_key"] == ["guide"]


def test_record_has_hash_key_and_relative_path(folders):
    data, out = folders
    put(data / "Acme/md/Fees #U2013 Overview.md", MD)

    ingest(data, out)

    (record,) = read_jsonl(out / "Acme/md/registry.jsonl")
    assert set(record) == {"doc_id", "doc_key", "path"}
    assert record["doc_id"] == hashlib.sha256(MD).hexdigest()
    assert record["doc_key"] == ["fees - overview"]
    assert record["path"] == "Acme/md/Fees #U2013 Overview.md"
    assert (data / record["path"]).read_bytes() == MD


def test_wrong_folder_is_reported_but_content_decides_format(folders):
    data, out = folders
    put_zip(data / "Acme/misc/report.txt", "word/document.xml")

    result = ingest(data, out)

    assert len(read_jsonl(out / "Acme/docx/registry.jsonl")) == 1
    assert result.format_mismatches == ["Acme/misc/report.txt"]


def test_junk_files_are_skipped_and_logged_in_their_company(folders):
    data, out = folders
    put(data / "Acme/md/.DS_Store", b"\x00\x00\x00\x01Bud1")
    put(data / "Acme/Acme.csv", b"q,a\n1,2\n")
    put(data / "Acme/md/empty.md", b"")

    result = ingest(data, out)

    assert result.registered == 0
    reasons = {r["path"]: r["reason"] for r in read_jsonl(out / "Acme/rejected.jsonl")}
    assert reasons == {
        "Acme/md/.DS_Store": "system file",
        "Acme/Acme.csv": "unsupported type",
        "Acme/md/empty.md": "empty file",
    }


def test_rejects_stay_in_their_own_company_folder(folders):
    data, out = folders
    put(data / "Acme/md/Guide.md", MD)
    put(data / "Acme/md/.DS_Store", b"x")
    put(data / "Beta/md/Guide.md", MD)

    ingest(data, out)

    assert len(read_jsonl(out / "Acme/rejected.jsonl")) == 1
    assert read_jsonl(out / "Beta/rejected.jsonl") == []
    assert not (out / "rejected.jsonl").exists()


def test_same_bytes_register_once_and_keep_both_names(folders):
    data, out = folders
    put(data / "ZX/md/Personal Loan Information.md", MD)
    put(data / "ZX/md/Personal Loan.md", MD)

    result = ingest(data, out)

    assert result.registered == 1
    (record,) = read_jsonl(out / "ZX/md/registry.jsonl")
    assert record["doc_key"] == ["personal loan information", "personal loan"]
    assert read_jsonl(out / "ZX/rejected.jsonl") == [
        {"path": "ZX/md/Personal Loan.md", "reason": "duplicate of ZX/md/Personal Loan Information.md"}
    ]


def test_same_name_different_bytes_gets_a_number(folders):
    data, out = folders
    put(data / "Acme/md/Guide.md", MD)
    put(data / "Acme/md/old/Guide.md", MD + b"changed\n")
    put(data / "Acme/md/older/Guide.md", MD + b"changed again\n")

    ingest(data, out)

    keys = [r["doc_key"] for r in read_jsonl(out / "Acme/md/registry.jsonl")]
    assert keys == [["guide"], ["guide_2"], ["guide_3"]]


def test_same_bytes_in_two_companies_are_not_duplicates(folders):
    data, out = folders
    put(data / "Acme/md/Guide.md", MD)
    put(data / "Beta/md/Guide.md", MD)

    result = ingest(data, out)

    assert result.registered == 2
    assert result.rejected == []


def test_files_outside_company_folders_are_ignored(folders):
    data, out = folders
    put(data / "queries.csv", b"q,a\n")
    put(data / "Acme/md/Guide.md", MD)

    result = ingest(data, out)

    assert result.registered == 1
    assert result.rejected == []


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs permission checks")
def test_unreadable_file_is_logged_and_the_run_continues(folders):
    data, out = folders
    put(data / "Acme/md/A good.md", MD)
    locked = data / "Acme/md/B locked.md"
    put(locked, MD + b"locked\n")
    locked.chmod(0)
    try:
        result = ingest(data, out)
    finally:
        locked.chmod(0o644)

    assert result.registered == 1
    (entry,) = read_jsonl(out / "Acme/rejected.jsonl")
    assert entry["path"] == "Acme/md/B locked.md"
    assert entry["reason"].startswith("unreadable")


def test_rerun_gives_identical_output(folders):
    data, out = folders
    put(data / "Acme/md/Guide.md", MD)
    put(data / "Acme/md/Copy of Guide.md", MD)
    put(data / "Acme/pdf/Guide.pdf", PDF)
    put(data / "Acme/md/.DS_Store", b"x")

    def snapshot():
        return {str(p.relative_to(out)): p.read_bytes() for p in sorted(out.rglob("*.jsonl"))}

    ingest(data, out)
    first = snapshot()
    ingest(data, out)

    assert snapshot() == first
    assert list(out.rglob("*.tmp")) == []


def test_missing_dataset_folder_raises(folders):
    data, out = folders
    with pytest.raises(NotADirectoryError):
        ingest(data / "nope", out)


def test_main_reads_both_paths_from_the_config(folders, monkeypatch, capsys):
    data, out = folders
    put(data / "Acme/md/Guide.md", MD)
    put(data / "Acme/md/.DS_Store", b"x")
    settings = {"paths": {"dataset_dir": str(data), "registry_dir": str(out)}}
    monkeypatch.setattr("ingestion.src.runner.load_config", lambda: settings)

    code = main()

    printed = capsys.readouterr().out
    assert code == 0
    assert "registered 1, rejected 1" in printed
    assert "system file: 1" in printed
    assert len(read_jsonl(out / "Acme/md/registry.jsonl")) == 1
