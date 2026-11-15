import io
import logging
import warnings
from pathlib import PurePath

_SUPPORTED = {".docx", ".pdf", ".txt", ".md"}


class ImportFileError(Exception):
    """A problem with an uploaded file, worded for the user."""


def _docx_text(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    lines = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            lines.extend(cell.text for cell in row.cells)
    return "\n".join(lines)


def _pdf_text(data: bytes) -> str:
    import pypdf

    pdf_logger = logging.getLogger("pypdf")
    previous = pdf_logger.level
    pdf_logger.setLevel(logging.CRITICAL)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reader = pypdf.PdfReader(io.BytesIO(data))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
    finally:
        pdf_logger.setLevel(previous)


def _plain_text(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def extract_text(filename: str, data: bytes) -> str:
    ext = PurePath(filename).suffix.lower()
    if ext == ".doc":
        raise ImportFileError(
            "Old .doc files aren't supported. Open it in Word and save it as .docx first."
        )
    if ext not in _SUPPORTED:
        raise ImportFileError("JobMe can read .docx, .pdf, .txt and .md files.")
    try:
        if ext == ".docx":
            text = _docx_text(data)
        elif ext == ".pdf":
            text = _pdf_text(data)
        else:
            text = _plain_text(data)
    except Exception as exc:
        raise ImportFileError(
            f"Couldn't open that file. Is it a real {ext[1:].upper()} file?"
        ) from exc
    text = text.strip()
    if not text:
        raise ImportFileError(
            "Couldn't find any text in that file. If it's a scanned PDF, try the Word version."
        )
    return text
