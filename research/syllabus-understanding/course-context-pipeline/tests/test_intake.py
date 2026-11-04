"""Reviewer ask: text/Markdown syllabus intake."""
import pytest

from course_context_pipeline.intake import load_syllabus


def test_txt_normalizes_whitespace(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("Line 1\n\n\n\nLine 2  \n", encoding="utf-8")
    # trailing spaces stripped, runs of blank lines collapsed to one, ends trimmed
    assert load_syllabus(p) == "Line 1\n\nLine 2"


def test_markdown_is_read(tmp_path):
    p = tmp_path / "s.md"
    p.write_text("# Title\n\nBody text", encoding="utf-8")
    out = load_syllabus(p)
    assert "Title" in out and "Body text" in out


def test_extensionless_treated_as_text(tmp_path):
    p = tmp_path / "syllabus"
    p.write_text("plain content", encoding="utf-8")
    assert load_syllabus(p) == "plain content"


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_syllabus(tmp_path / "nope.txt")


def test_unsupported_format_raises(tmp_path):
    p = tmp_path / "s.docx"
    p.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        load_syllabus(p)


def test_empty_after_normalize_raises(tmp_path):
    p = tmp_path / "s.txt"
    p.write_text("   \n\n   \n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_syllabus(p)
