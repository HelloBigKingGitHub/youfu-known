"""Tests for the document loader and individual parsers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rag.loader import (
    UnsupportedFormat,
    detect_ext,
    load_document,
    supported_extensions,
)
from app.rag.parser_docx import parse_docx
from app.rag.parser_html import parse_html, parse_html_text
from app.rag.parser_md import parse_md, parse_md_text
from app.rag.parser_pdf import parse_pdf
from app.rag.parser_txt import parse_txt, parse_txt_text


def test_supported_extensions_contains_known_types() -> None:
    exts = supported_extensions()
    assert ".pdf" in exts
    assert ".docx" in exts
    assert ".md" in exts
    assert ".txt" in exts
    assert ".html" in exts


def test_detect_ext_lowercase() -> None:
    assert detect_ext("foo.PDF") == ".pdf"
    assert detect_ext(Path("Bar.Md")) == ".md"


def test_load_document_unsupported(tmp_path: Path) -> None:
    p = tmp_path / "x.bin"
    p.write_bytes(b"junk")
    with pytest.raises(UnsupportedFormat):
        load_document(p)


def test_load_document_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_document(tmp_path / "nope.pdf")


@pytest.mark.parametrize(
    "ext,fixture_name",
    [
        (".txt", "sample_txt"),
        (".md", "sample_md"),
        (".html", "sample_html"),
        (".docx", "sample_docx"),
        (".pdf", "sample_pdf"),
    ],
)
def test_load_document_returns_nonempty_list(
    request, ext: str, fixture_name: str
) -> None:
    path: Path = request.getfixturevalue(fixture_name)
    sections = load_document(path)
    assert isinstance(sections, list)
    assert sections, f"loader returned empty list for {ext}"
    for s in sections:
        assert "text" in s
        assert isinstance(s["text"], str)
        assert s["text"].strip()


def test_parse_txt_text_splits_on_blank_lines() -> None:
    body = "first paragraph.\n\nsecond paragraph.\n\n\nthird."
    sections = parse_txt_text(body)
    assert len(sections) == 3
    assert sections[0]["text"] == "first paragraph."
    assert sections[2]["text"] == "third."
    for s in sections:
        assert s["page"] is None


def test_parse_md_text_blocks() -> None:
    body = (
        "# Title\n\n"
        "A paragraph.\n\n"
        "- item one\n"
        "- item two\n\n"
        "```python\nprint('hi')\n```\n"
    )
    sections = parse_md_text(body)
    assert len(sections) >= 3
    # Heading first, then paragraph, then list, then code block.
    assert "Title" in sections[0]["text"]
    joined = "\n\n".join(s["text"] for s in sections)
    assert "item one" in joined and "item two" in joined
    assert "print('hi')" in joined


def test_parse_html_text_strips_script() -> None:
    body = (
        "<html><body>"
        "<h1>Hello</h1>"
        "<p>World.</p>"
        "<script>alert('x')</script>"
        "</body></html>"
    )
    sections = parse_html_text(body)
    joined = "\n".join(s["text"] for s in sections)
    assert "Hello" in joined
    assert "World." in joined
    assert "alert" not in joined


def test_parse_pdf_returns_page_numbers(sample_pdf: Path) -> None:
    sections = parse_pdf(sample_pdf)
    assert sections
    for s in sections:
        assert isinstance(s["page"], int)
        assert s["page"] >= 1


def test_parse_docx_returns_paragraphs(sample_docx: Path) -> None:
    sections = parse_docx(sample_docx)
    assert sections
    for s in sections:
        assert s["page"] is None


def test_parse_md_and_parse_txt_smoke(sample_md: Path, sample_txt: Path) -> None:
    assert parse_md(sample_md)
    assert parse_txt(sample_txt)