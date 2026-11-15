import io
import re

import docx
import pypdf
import pytest
from fastapi import FastAPI, File, UploadFile
from fastapi.testclient import TestClient

from jobmecloud.api.uploads import MAX_UPLOAD_BYTES, read_upload
from jobmecloud.importers.text import ImportFileError, extract_text


def test_docx_paragraphs_and_tables():
    doc = docx.Document()
    doc.add_paragraph("Senior Engineer")
    doc.add_table(1, 1).cell(0, 0).text = "Python"
    buf = io.BytesIO()
    doc.save(buf)
    text = extract_text("cv.docx", buf.getvalue())
    assert "Senior Engineer" in text and "Python" in text


def test_pdf_without_text_is_plain_error():
    w = pypdf.PdfWriter()
    w.add_blank_page(612, 792)
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(ImportFileError, match="Couldn't find any text"):
        extract_text("scan.pdf", buf.getvalue())


def test_txt_cp1252_fallback():
    assert extract_text("notes.txt", "café".encode("cp1252")) == "café"


def test_txt_bom_and_md_and_uppercase_extension():
    assert extract_text("N.MD", b"\xef\xbb\xbf# Hi\n") == "# Hi"


def test_empty_text_is_plain_error():
    with pytest.raises(ImportFileError, match="Couldn't find any text"):
        extract_text("a.txt", b"   \n")


@pytest.mark.parametrize("name,msg", [
    ("cv.doc", "Old .doc"),
    ("cv.png", "JobMe can read"),
    ("cv.pdf", "Is it a real PDF file?"),
    ("CV.PDF", "Is it a real PDF file?"),
    ("cv.docx", "Is it a real DOCX file?"),
])
def test_rejections(name, msg):
    with pytest.raises(ImportFileError, match=re.escape(msg)):
        extract_text(name, b"not really a file")


def _client():
    app = FastAPI()

    @app.post("/up")
    async def up(file: UploadFile = File(...)):
        try:
            return {"n": len(await read_upload(file))}
        except ImportFileError as exc:
            return {"error": str(exc)}

    return TestClient(app)


def test_read_upload_within_limit():
    r = _client().post("/up", files={"file": ("a.txt", b"x" * 100)})
    assert r.json() == {"n": 100}


def test_read_upload_too_big():
    r = _client().post("/up", files={"file": ("a.txt", b"x" * (MAX_UPLOAD_BYTES + 1))})
    assert r.json() == {"error": "That file is too big. The limit is 10 MB."}
