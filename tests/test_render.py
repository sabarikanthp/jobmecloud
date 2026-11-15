import copy
import io
from datetime import date

import docx
import pytest
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls, qn

from docx_fixtures import FIXTURE_LABELS, FIXTURE_READING, HEADLINE, make_resume_docx
from jobmecloud.applydocs.content import CoverLetter, TailoredBullet, TailoredContent, TailoredRole, original_content
from jobmecloud.applydocs.render import (
    render_cover_letter,
    render_plain_cover_letter,
    render_plain_resume,
    render_resume,
)
from jobmecloud.config.profile import UserProfile
from jobmecloud.resumes.docx_text import iter_paragraph_objects, iter_paragraphs
from jobmecloud.resumes.mapping import MappedParagraph, ResumeMapping


def mapping(data=None, labels=None):
    paras = iter_paragraphs(data or make_resume_docx())
    labels = FIXTURE_LABELS if labels is None else labels
    return ResumeMapping(paragraphs=[MappedParagraph(index=p.index, text=p.text, label=labels.get(p.index, "keep"))
                                     for p in paras])


def texts(data):
    return [p.text for p in iter_paragraphs(data)]


def _save(doc) -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


LETTER = CoverLetter(greeting="Dear Hiring Manager,", paragraphs=["One.", "Two."], sign_off="Sincerely,")


def test_render_resume_fills_slots_and_keeps_layout():
    content = TailoredContent(headline="", summary="Tailored summary.", skills=["SQL", "Python"],
                              roles=[TailoredRole(role=0, bullets=[TailoredBullet(source=2, text="Third first"),
                                                                   TailoredBullet(source=0, text="First second")]),
                                     TailoredRole(role=1, bullets=[TailoredBullet(source=0, text="C1"), TailoredBullet(source=1, text="C2")])])
    out = render_resume(make_resume_docx(), mapping(), content)
    t = texts(out)
    assert t[4] == "Tailored summary." and t[7:9] == ["Third first", "First second"]
    assert "Northwind Labs — Senior Engineer — 2021–2025" in t and t[-2:] == ["B.S. Computer Science", "State University, 2018"]
    assert "SQL, Python" in t and len(t) == 16                       # one bullet slot removed
    doc = docx.Document(io.BytesIO(out))
    bullet = iter_paragraph_objects(doc)[7]
    assert bullet.style.name == "List Bullet" and len(bullet.runs) == 1
    assert not bullet.runs[0].bold                                 # the long normal run's look, not the bold lead-in
    assert len(doc.tables) == 1


def test_render_cover_letter_keeps_contact_only():
    letter = CoverLetter(greeting="Dear Hiring Manager,", paragraphs=["One.", "Two."], sign_off="Sincerely,")
    out = render_cover_letter(make_resume_docx(), mapping(), letter, UserProfile(name="Jordan Example"), date(2026, 11, 12))
    t = texts(out)
    assert t[:2] == ["Jordan Example", "jordan@example.com · Springfield"] and "November 12, 2026" in t
    assert t[-4:] == ["One.", "Two.", "Sincerely,", "Jordan Example"] and "Northwind Labs — Senior Engineer — 2021–2025" not in t


def test_plain_fallbacks():
    c = original_content(FIXTURE_READING)
    t = texts(render_plain_resume(FIXTURE_READING, c, UserProfile(name="Jordan Example", email="jordan@example.com")))
    assert t[0] == "Jordan Example" and FIXTURE_READING.roles[0].bullets[0] in t
    t2 = texts(render_plain_cover_letter(CoverLetter(greeting="Hi,", paragraphs=["Body."], sign_off="Best,"),
                                         UserProfile(name="Jordan Example"), date(2026, 1, 2)))
    assert "January 2, 2026" in t2 and t2[-1] == "Jordan Example"


def test_render_resume_extra_bullets_dropped_extra_summary_removed_and_several_skills_kept():
    labels = {**FIXTURE_LABELS, 3: "summary", 13: "skills"}      # two summary and two skills paragraphs
    content = TailoredContent(headline="", summary="S.", skills=["Go"],
                              roles=[TailoredRole(role=0, bullets=[TailoredBullet(source=i % 3, text=f"N{i}") for i in range(5)]),
                                     TailoredRole(role=1, bullets=[TailoredBullet(source=0, text="C1")])])
    out = render_resume(make_resume_docx(), mapping(labels=labels), content)
    t = texts(out)
    # Several skills paragraphs are the user's own category lines: all stay as written.
    assert t == ["Jordan Example", "jordan@example.com · Springfield", HEADLINE, "S.", "Experience",
                 "Northwind Labs — Senior Engineer — 2021–2025", "N0", "N1", "N2",
                 "Contoso Health — Engineer — 2018–2021", "C1", "Skills", "Python, SQL, Airflow",
                 "B.S. Computer Science", "State University, 2018"]


def test_render_resume_empty_skills_leaves_the_skills_paragraph():
    content = original_content(FIXTURE_READING)
    content.skills = []
    t = texts(render_resume(make_resume_docx(), mapping(), content))
    assert t[14] == "Python, SQL, Airflow" and len(t) == 17


def test_render_resume_single_skills_paragraph_is_filled():
    content = original_content(FIXTURE_READING)
    content.skills = ["SQL"]
    t = texts(render_resume(make_resume_docx(), mapping(), content))
    assert t[14] == "SQL"


def test_render_resume_role_missing_from_content_loses_its_slots():
    content = TailoredContent(headline="", summary="S.", skills=[], roles=[TailoredRole(role=1, bullets=[TailoredBullet(source=1, text="C2")])])
    t = texts(render_resume(make_resume_docx(), mapping(), content))
    assert t[6:9] == ["Northwind Labs — Senior Engineer — 2021–2025", "Contoso Health — Engineer — 2018–2021", "C2"]


def test_render_resume_does_not_mutate_input_and_reopens():
    template = make_resume_docx()
    before = bytes(template)
    out = render_resume(template, mapping(), original_content(FIXTURE_READING))
    assert template == before
    t = texts(out)
    assert t[7] == FIXTURE_READING.roles[0].bullets[0] and t[14] == "Python, SQL, Airflow" and len(t) == 17


def test_render_resume_rejects_mapping_for_a_different_file():
    m = mapping()
    short = ResumeMapping(paragraphs=m.paragraphs[:-1])
    with pytest.raises(ValueError, match="mapping"):
        render_resume(make_resume_docx(), short, original_content(FIXTURE_READING))
    with pytest.raises(ValueError, match="mapping"):
        render_cover_letter(make_resume_docx(), short, LETTER, UserProfile(name="Jordan Example"), date(2026, 1, 2))
    shuffled = ResumeMapping(paragraphs=[m.paragraphs[1], m.paragraphs[0], *m.paragraphs[2:]])
    with pytest.raises(ValueError, match="mapping"):
        render_resume(make_resume_docx(), shuffled, original_content(FIXTURE_READING))


def test_render_resume_removed_cell_paragraph_leaves_cell_valid():
    labels = {**FIXTURE_LABELS, 15: "summary", 16: "summary"}    # the second summary paragraph is the only one in its cell
    labels.pop(4)
    out = render_resume(make_resume_docx(), mapping(labels=labels), original_content(FIXTURE_READING))
    doc = docx.Document(io.BytesIO(out))
    cells = doc.tables[0].rows[0].cells
    assert cells[0].text == FIXTURE_READING.summary and cells[1].text == ""
    for tc in doc.element.body.iter(qn("w:tc")):
        assert tc.findall(qn("w:p"))


def test_render_resume_removed_slot_hands_its_section_break_back():
    doc = docx.Document(io.BytesIO(make_resume_docx()))
    last = iter_paragraph_objects(doc)[9]                         # the third Northwind bullet ends a section
    last._p.get_or_add_pPr()._insert_sectPr(copy.deepcopy(doc.element.body.sectPr))
    data = _save(doc)
    content = original_content(FIXTURE_READING)
    content.roles[0].bullets = content.roles[0].bullets[:2]
    out = render_resume(data, mapping(data), content)
    result = docx.Document(io.BytesIO(out))
    paras = iter_paragraph_objects(result)
    assert len(result.sections) == 2 and len(paras) == 16
    assert paras[8]._p.pPr.find(qn("w:sectPr")) is not None


def test_render_cover_letter_contact_table_keeps_only_contact_text_and_copies_summary_format():
    doc = docx.Document(io.BytesIO(make_resume_docx()))
    summary = iter_paragraph_objects(doc)[4]
    summary.paragraph_format.space_after = docx.shared.Pt(17)
    doc.tables[0].cell(0, 0).text = "555-0100 · example.com/jordan"  # contact details in a layout table
    data = _save(doc)
    labels = {**FIXTURE_LABELS, 15: "contact"}                   # cell 16 (education) stays keep
    out = render_cover_letter(data, mapping(data, labels), LETTER, UserProfile(name="Jordan Example"), date(2026, 3, 4))
    result = docx.Document(io.BytesIO(out))
    t = texts(out)
    assert t == ["Jordan Example", "jordan@example.com · Springfield", "555-0100 · example.com/jordan", "",
                 "March 4, 2026", "", "Dear Hiring Manager,", "One.", "Two.", "Sincerely,", "Jordan Example"]
    assert "State University" not in result.element.body.xml
    assert len(result.tables) == 1
    for tc in result.element.body.iter(qn("w:tc")):
        assert tc.findall(qn("w:p"))
    body = list(result.element.body)
    assert body[-1].tag == qn("w:sectPr")
    appended = iter_paragraph_objects(result)[4:]
    assert all(p.paragraph_format.space_after == docx.shared.Pt(17) for p in appended)


def test_render_cover_letter_uses_resume_run_font_without_emphasis():
    doc = docx.Document(io.BytesIO(make_resume_docx()))
    for p in iter_paragraph_objects(doc):
        for run in p.runs:
            run.font.name, run.font.size = "Garamond", docx.shared.Pt(11)
    iter_paragraph_objects(doc)[4].runs[0].bold = True             # emphasis on the summary is not copied
    data = _save(doc)
    out = render_cover_letter(data, mapping(data), LETTER, UserProfile(name="Jordan Example"), date(2026, 3, 4))
    paras = iter_paragraph_objects(docx.Document(io.BytesIO(out)))
    runs = [r for p in paras[2:] for r in p.runs]
    assert len(runs) == 6                                         # date, greeting, two paragraphs, sign-off, name
    assert all((r.font.name, r.font.size, r.bold) == ("Garamond", docx.shared.Pt(11), None) for r in runs)
    assert paras[0].runs[0].font.name == "Garamond"


def test_render_cover_letter_without_summary_uses_normal_style():
    labels = {k: v for k, v in FIXTURE_LABELS.items() if v != "summary"}
    out = render_cover_letter(make_resume_docx(), mapping(labels=labels), LETTER, UserProfile(name="Jordan Example"),
                              date(2026, 3, 4))
    appended = iter_paragraph_objects(docx.Document(io.BytesIO(out)))[2:]
    assert len(appended) == 7 and all(p.style.name == "Normal" for p in appended)


def test_render_cover_letter_removes_content_controls():
    doc = docx.Document(io.BytesIO(make_resume_docx()))
    sdt = parse_xml(f'<w:sdt {nsdecls("w")}><w:sdtContent><w:p><w:r><w:t>Old resume text</w:t></w:r></w:p>'
                    '</w:sdtContent></w:sdt>')
    doc.element.body.insert(2, sdt)
    data = _save(doc)
    out = render_cover_letter(data, mapping(data), LETTER, UserProfile(name="Jordan Example"), date(2026, 3, 4))
    assert "Old resume text" not in docx.Document(io.BytesIO(out)).element.body.xml


def test_render_cover_letter_keeps_headers():
    doc = docx.Document(io.BytesIO(make_resume_docx()))
    doc.sections[0].header.paragraphs[0].text = "Jordan Example header"
    data = _save(doc)
    out = render_cover_letter(data, mapping(data), LETTER, UserProfile(name="Jordan Example"), date(2026, 3, 4))
    assert docx.Document(io.BytesIO(out)).sections[0].header.paragraphs[0].text == "Jordan Example header"


def test_plain_resume_layout():
    user = UserProfile(name="Jordan Example", email="jordan@example.com", location="Springfield",
                       links=["https://example.com/jordan"])
    content = original_content(FIXTURE_READING)
    out = render_plain_resume(FIXTURE_READING, content, user)
    doc = docx.Document(io.BytesIO(out))
    paras = iter_paragraph_objects(doc)
    t = [p.text for p in paras]
    assert paras[0].style.name == "Title"
    assert t[1] == "jordan@example.com · Springfield · https://example.com/jordan"
    assert FIXTURE_READING.summary in t and "Northwind Labs — Senior Engineer — 2021–2025" in t
    bullet = paras[t.index(FIXTURE_READING.roles[1].bullets[0])]
    assert bullet.style.name == "List Bullet"
    assert "Python, SQL, Airflow" in t
    assert any("State University" in x for x in t) and any("Example Cloud Practitioner" in x for x in t)


def _headline_mapping(extra_headline=False):
    labels = dict(FIXTURE_LABELS)
    if extra_headline:
        labels[16] = "headline"
    return mapping(labels=labels)


def test_render_resume_fills_only_first_headline_and_leaves_titles_and_extra_headlines():
    content = original_content(FIXTURE_READING, "Data Platforms | Engineering Leader")
    base = texts(make_resume_docx())
    t = texts(render_resume(make_resume_docx(), _headline_mapping(extra_headline=True), content))
    assert t[2] == "Data Platforms | Engineering Leader"
    assert t[6] == base[6] and t[10] == base[10]            # title paragraphs
    assert t[16] == base[16] and len(t) == len(base)         # the extra headline is unchanged, not removed
    assert t[:2] == base[:2]


def test_render_resume_empty_headline_leaves_the_paragraph():
    t = texts(render_resume(make_resume_docx(), mapping(), original_content(FIXTURE_READING)))
    assert t[2] == HEADLINE


def test_render_resume_headline_keeps_paragraph_formatting():
    doc = docx.Document(io.BytesIO(make_resume_docx()))
    iter_paragraph_objects(doc)[2].paragraph_format.space_after = docx.shared.Pt(9)
    data = _save(doc)
    out = render_resume(data, mapping(data), original_content(FIXTURE_READING, "Data Platforms"))
    p = iter_paragraph_objects(docx.Document(io.BytesIO(out)))[2]
    assert p.text == "Data Platforms" and p.paragraph_format.space_after == docx.shared.Pt(9)


def test_cover_letter_has_neither_headline_nor_title_lines():
    out = render_cover_letter(make_resume_docx(), mapping(), LETTER, UserProfile(name="Jordan Example"),
                              date(2026, 11, 12))
    t = texts(out)
    assert HEADLINE not in t and not any("Northwind Labs —" in x or "Contoso Health —" in x for x in t)
    assert t[:2] == ["Jordan Example", "jordan@example.com · Springfield"]


def test_plain_resume_prints_headline_under_the_name_when_present():
    user = UserProfile(name="Jordan Example", email="jordan@example.com")
    t = texts(render_plain_resume(FIXTURE_READING, original_content(FIXTURE_READING, "Data Platforms"), user))
    assert t[:3] == ["Jordan Example", "Data Platforms", "jordan@example.com"]
    t = texts(render_plain_resume(FIXTURE_READING, original_content(FIXTURE_READING), user))
    assert t[:2] == ["Jordan Example", "jordan@example.com"]
