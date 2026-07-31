import pytest

from document_parser import extract_text


def test_extract_txt(tmp_path):
    file_path = tmp_path / "notes.txt"
    file_path.write_text("Hello, this is a plain text document.", encoding="utf-8")

    assert extract_text(str(file_path)) == "Hello, this is a plain text document."


def test_extract_docx(tmp_path):
    docx = pytest.importorskip("docx")
    file_path = tmp_path / "notes.docx"

    document = docx.Document()
    document.add_paragraph("First paragraph.")
    document.add_paragraph("Second paragraph.")
    document.add_paragraph("")  # blank paragraphs should be skipped
    document.save(str(file_path))

    text = extract_text(str(file_path))
    assert "First paragraph." in text
    assert "Second paragraph." in text


def test_unsupported_extension_raises():
    with pytest.raises(ValueError):
        extract_text("document.xyz")
