"""Render the tailored resume and cover letter into Word documents.

When the default resume is a mapped .docx, the documents are written into a copy of
it so the user's own formatting is kept. Otherwise plain documents are built.
"""

import copy
import io
from datetime import date

import docx
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph as DocxParagraph

from jobmecloud.applydocs.content import CoverLetter, TailoredContent
from jobmecloud.config.profile import MasterResume, UserProfile
from jobmecloud.resumes.docx_text import iter_paragraph_objects, remove_paragraph, set_paragraph_text
from jobmecloud.resumes.mapping import ResumeMapping

SEP = " · "


def _open(template: bytes) -> "docx.document.Document":
    return docx.Document(io.BytesIO(template))


def _save(doc: "docx.document.Document") -> bytes:
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _labelled(doc: "docx.document.Document", mapping: ResumeMapping) -> list[tuple[DocxParagraph, str]]:
    """Pair each paragraph with its label, refusing a mapping made for a different file."""
    paras = iter_paragraph_objects(doc)
    indexes = [p.index for p in mapping.paragraphs]
    if indexes != list(range(len(paras))):
        raise ValueError(
            f"The resume mapping does not match this file: the mapping has {len(indexes)} paragraphs "
            f"and the file has {len(paras)}. Review the resume's mapping again."
        )
    return [(p, m.label) for p, m in zip(paras, mapping.paragraphs)]


def _drop(p: DocxParagraph) -> None:
    """Remove a paragraph. A section break it carries moves to the paragraph before it."""
    ppr = p._p.pPr
    sect = ppr.find(qn("w:sectPr")) if ppr is not None else None
    if sect is not None:
        prev = p._p.getprevious()
        if prev is not None and prev.tag == qn("w:p") and prev.find(f"{qn('w:pPr')}/{qn('w:sectPr')}") is None:
            prev.get_or_add_pPr()._insert_sectPr(sect)  # schema order; lxml moves the element
        else:
            # Nowhere to move it: empty the paragraph so the section layout stays.
            for child in list(p._p):
                if child.tag in (qn("w:r"), qn("w:hyperlink")):
                    p._p.remove(child)
            return
    remove_paragraph(p)


def _fill_first(paras: list[DocxParagraph], text: str) -> None:
    if paras:
        set_paragraph_text(paras[0], text)
        for extra in paras[1:]:
            _drop(extra)


def render_resume(template: bytes, mapping: ResumeMapping, content: TailoredContent) -> bytes:
    doc = _open(template)
    headline: list[DocxParagraph] = []
    summary: list[DocxParagraph] = []
    skills: list[DocxParagraph] = []
    slots: dict[int, list[DocxParagraph]] = {}
    for p, label in _labelled(doc, mapping):
        if label == "headline":
            headline.append(p)
        elif label == "summary":
            summary.append(p)
        elif label == "skills":
            skills.append(p)
        elif label.startswith("bullet:"):
            slots.setdefault(int(label.split(":")[1]), []).append(p)

    if headline and content.headline:
        set_paragraph_text(headline[0], content.headline)  # other headlines and all titles stay as written
    _fill_first(summary, content.summary)
    # Several skills paragraphs are the user's own category lines: one comma list would merge
    # them, so they all stay as written. An empty skills list also leaves the paragraph alone.
    if len(skills) == 1 and content.skills:
        set_paragraph_text(skills[0], ", ".join(content.skills))
    bullets = {r.role: r.bullets for r in content.roles}
    for role, role_slots in slots.items():
        tailored = bullets.get(role, [])
        for k, slot in enumerate(role_slots):
            if k < len(tailored):
                set_paragraph_text(slot, tailored[k].text)
            else:
                _drop(slot)
    return _save(doc)


def _letter_lines(letter: CoverLetter, user: UserProfile, today: date) -> list[str]:
    return [f"{today:%B} {today.day}, {today.year}", "", letter.greeting, *letter.paragraphs, letter.sign_off, user.name]


def render_cover_letter(template: bytes, mapping: ResumeMapping, letter: CoverLetter, user: UserProfile,
                        today: date) -> bytes:
    doc = _open(template)
    labelled = _labelled(doc, mapping)
    contact = {p._p for p, label in labelled if label == "contact"}
    summary = next((p for p, label in labelled if label == "summary"), None)
    ppr = _summary_ppr(summary)
    rpr = _summary_rpr(summary)

    body = doc.element.body
    for child in list(body):
        if child.tag == qn("w:p"):
            keep = child in contact
        elif child.tag in (qn("w:tbl"), qn("w:sdt")):
            # A table holding contact details stays for its layout; any other table or content control goes.
            keep = any(p in contact for p in child.iter(qn("w:p")))
            if keep:
                # Only the contact paragraphs keep their text. The others are emptied, not removed,
                # so every table cell still has a paragraph.
                for p in child.iter(qn("w:p")):
                    if p not in contact:
                        _empty(p)
        else:
            keep = True  # the final w:sectPr and non-content markup
        if not keep:
            body.remove(child)

    for text in _letter_lines(letter, user, today):
        p = doc.add_paragraph()
        if ppr is not None:
            if p._p.pPr is not None:
                p._p.remove(p._p.pPr)
            p._p.insert(0, copy.deepcopy(ppr))
        if text:
            run = p.add_run(text)
            if rpr is not None:
                run._r.insert(0, copy.deepcopy(rpr))
    return _save(doc)


TRACKED = ("w:rPrChange", "w:ins", "w:del")
EMPHASIS = ("w:b", "w:bCs", "w:i", "w:iCs", "w:u", "w:highlight")


def _strip(el, tags: tuple[str, ...]) -> None:
    for tag in tags:
        for found in el.findall(qn(tag)):
            el.remove(found)


def _summary_ppr(summary: DocxParagraph | None):
    """The summary's paragraph properties, without its section break, numbering or tracked changes."""
    if summary is None or summary._p.pPr is None:
        return None
    ppr = copy.deepcopy(summary._p.pPr)
    _strip(ppr, ("w:sectPr", "w:numPr", "w:pPrChange"))
    mark = ppr.find(qn("w:rPr"))
    if mark is not None:
        _strip(mark, TRACKED)
    return ppr


def _summary_rpr(summary: DocxParagraph | None):
    """The summary's first run formatting (font name, size, colour), without emphasis or tracked changes."""
    if summary is None or not summary.runs or summary.runs[0]._r.rPr is None:
        return None
    rpr = copy.deepcopy(summary.runs[0]._r.rPr)
    _strip(rpr, TRACKED + EMPHASIS)
    return rpr


def _empty(p) -> None:
    for child in list(p):
        if child.tag in (qn("w:r"), qn("w:hyperlink")):
            p.remove(child)


def _contact_line(user: UserProfile) -> str:
    fields = [user.email, user.phone, user.location, user.linkedin_url, *user.links]
    return SEP.join(f for f in fields if f)


def _plain_header(doc: "docx.document.Document", user: UserProfile, name_style: str | None,
                  headline: str = "") -> None:
    if user.name:
        doc.add_paragraph(user.name, style=name_style)
    if headline:
        doc.add_paragraph(headline)
    if line := _contact_line(user):
        doc.add_paragraph(line)


def _join(parts: list[str], sep: str) -> str:
    return sep.join(p for p in parts if p)


def render_plain_resume(resume: MasterResume, content: TailoredContent, user: UserProfile) -> bytes:
    doc = docx.Document()
    _plain_header(doc, user, "Title", content.headline)
    if content.summary:
        doc.add_paragraph("Summary", style="Heading 1")
        doc.add_paragraph(content.summary)
    roles = [(resume.roles[r.role], r.bullets) for r in content.roles if 0 <= r.role < len(resume.roles)]
    if roles:
        doc.add_paragraph("Experience", style="Heading 1")
        for role, bullets in roles:
            dates = _join([role.start, role.end], "–")
            doc.add_paragraph(_join([role.employer, role.title, dates], " — "))
            for bullet in bullets:
                doc.add_paragraph(bullet.text, style="List Bullet")
    if content.skills:
        doc.add_paragraph("Skills", style="Heading 1")
        doc.add_paragraph(", ".join(content.skills))
    if resume.education:
        doc.add_paragraph("Education", style="Heading 1")
        for e in resume.education:
            doc.add_paragraph(_join([_join([e.degree, e.field], " "), e.school, e.year], ", "))
    if resume.certifications:
        doc.add_paragraph("Certifications", style="Heading 1")
        for c in resume.certifications:
            doc.add_paragraph(_join([c.name, c.issuer, c.year], ", "))
    return _save(doc)


def render_plain_cover_letter(letter: CoverLetter, user: UserProfile, today: date) -> bytes:
    doc = docx.Document()
    _plain_header(doc, user, None)
    if user.name or _contact_line(user):
        doc.add_paragraph()
    for text in _letter_lines(letter, user, today):
        doc.add_paragraph(text)
    return _save(doc)
