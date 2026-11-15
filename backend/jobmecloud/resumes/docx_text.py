import io
from dataclasses import dataclass

import docx
from docx.oxml.ns import qn
from docx.table import _Cell
from docx.text.paragraph import Paragraph as DocxParagraph


@dataclass
class Paragraph:
    index: int
    text: str
    in_table: bool


def _walk(container, parent) -> list[DocxParagraph]:
    found: list[DocxParagraph] = []
    for child in container.iterchildren():
        if child.tag == qn("w:p"):
            found.append(DocxParagraph(child, parent))
        elif child.tag == qn("w:tbl"):
            for tr in child.iterchildren(qn("w:tr")):
                for tc in tr.iterchildren(qn("w:tc")):
                    found.extend(_walk(tc, _Cell(tc, parent)))
    return found


def iter_paragraph_objects(doc: "docx.document.Document") -> list[DocxParagraph]:
    """Body and table-cell paragraphs in document order. Text boxes, headers and footers are left out."""
    return _walk(doc.element.body, doc)


def iter_paragraphs(data: bytes) -> list[Paragraph]:
    doc = docx.Document(io.BytesIO(data))
    return [
        Paragraph(i, p.text, p._p.getparent().tag == qn("w:tc"))
        for i, p in enumerate(iter_paragraph_objects(doc))
    ]


def set_paragraph_text(p: DocxParagraph, text: str) -> None:
    """Replace the text, keeping the paragraph's properties and the longest run's formatting.

    The longest run (the earliest on a tie) carries the paragraph's main look, so a short
    bold lead-in does not spread over the whole new text.
    """
    runs = p.runs
    if runs:
        kept = max(runs, key=lambda r: len(r.text))  # max keeps the earliest on a tie
        kept.text = text
    else:
        kept = p.add_run(text)
    for child in list(p._p):
        if child is not kept._r and child.tag in (qn("w:r"), qn("w:hyperlink")):
            p._p.remove(child)


def remove_paragraph(p: DocxParagraph) -> None:
    parent = p._p.getparent()
    if parent.tag == qn("w:tc") and len(parent.findall(qn("w:p"))) == 1:
        # A table cell must keep a paragraph, so empty it instead.
        for child in list(p._p):
            if child.tag in (qn("w:r"), qn("w:hyperlink")):
                p._p.remove(child)
        return
    parent.remove(p._p)
