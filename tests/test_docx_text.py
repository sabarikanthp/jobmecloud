import io
import zipfile

import docx

from docx_fixtures import make_resume_docx, set_app_pages
from jobmecloud.resumes.docx_text import (
    iter_paragraph_objects,
    iter_paragraphs,
    remove_paragraph,
    set_paragraph_text,
)


def test_iter_paragraphs_includes_tables_in_order():
    paras = iter_paragraphs(make_resume_docx())
    assert [p.text for p in paras][:2] == ["Jordan Example", "jordan@example.com · Springfield"]
    assert paras[15].in_table and paras[15].text == "B.S. Computer Science" and len(paras) == 17
    assert [p.index for p in paras] == list(range(17)) and not paras[14].in_table


def test_set_paragraph_text_keeps_style_numbering_and_longest_run_format():
    doc = docx.Document(io.BytesIO(make_resume_docx()))
    p = iter_paragraph_objects(doc)[7]
    longest = max(p.runs, key=lambda r: len(r.text))
    style, numpr, bold = p.style.name, p._p.pPr.numPr, longest.bold
    set_paragraph_text(p, "New bullet")
    assert (p.text, p.style.name, len(p.runs), p.runs[0].bold) == ("New bullet", style, 1, bold)
    assert (p._p.pPr.numPr is None) == (numpr is None)


def test_set_paragraph_text_short_bold_lead_in_does_not_spread():
    doc = docx.Document()
    p = doc.add_paragraph()
    p.add_run("Lead: ").bold = True
    p.add_run("a much longer normal sentence.").font.size = docx.shared.Pt(13)
    set_paragraph_text(p, "Rewritten bullet")
    assert (p.text, len(p.runs), p.runs[0].bold, p.runs[0].font.size) == ("Rewritten bullet", 1, None, docx.shared.Pt(13))


def test_set_paragraph_text_keeps_bold_when_bold_run_is_longest():
    doc = docx.Document()
    p = doc.add_paragraph()
    p.add_run("A long bold heading-like run").bold = True
    p.add_run(" tail")
    set_paragraph_text(p, "Rewritten")
    assert (p.text, len(p.runs), p.runs[0].bold) == ("Rewritten", 1, True)


def test_set_paragraph_text_tie_takes_earliest_run():
    doc = docx.Document()
    p = doc.add_paragraph()
    p.add_run("abc").italic = True
    p.add_run("xyz").bold = True
    set_paragraph_text(p, "New")
    assert (len(p.runs), p.runs[0].italic, p.runs[0].bold) == (1, True, None)


def test_set_paragraph_text_adds_run_when_none():
    doc = docx.Document(io.BytesIO(make_resume_docx()))
    p = doc.add_paragraph()
    set_paragraph_text(p, "Hello")
    assert p.text == "Hello"


def test_remove_paragraph():
    doc = docx.Document(io.BytesIO(make_resume_docx()))
    remove_paragraph(iter_paragraph_objects(doc)[5])
    assert len(iter_paragraph_objects(doc)) == 16
    assert iter_paragraph_objects(doc)[5].text.startswith("Northwind")


def test_set_app_pages_replaces_and_adds():
    data = set_app_pages(make_resume_docx(), 3)
    xml = zipfile.ZipFile(io.BytesIO(data)).read("docProps/app.xml").decode()
    assert "<Pages>3</Pages>" in xml
    again = zipfile.ZipFile(io.BytesIO(set_app_pages(data, 5))).read("docProps/app.xml").decode()
    assert "<Pages>5</Pages>" in again and again.count("<Pages>") == 1
    docx.Document(io.BytesIO(data))


def test_remove_paragraph_keeps_last_paragraph_in_table_cell():
    from docx.oxml.ns import qn

    doc = docx.Document(io.BytesIO(make_resume_docx()))
    cell = doc.tables[0].cell(0, 0)
    cell.add_paragraph("Second")
    paras = iter_paragraph_objects(doc)
    remove_paragraph(paras[15])  # first of two: removed normally
    assert [p.text for p in cell.paragraphs] == ["Second"]
    remove_paragraph(iter_paragraph_objects(doc)[15])  # the only one left: emptied, not removed
    tc = cell._tc
    ps = tc.findall(qn("w:p"))
    assert len(ps) == 1 and ps[0].findall(qn("w:r")) == [] and cell.paragraphs[0].text == ""
