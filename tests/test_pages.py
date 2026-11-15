import io

import docx
from docx_fixtures import make_resume_docx, set_app_pages

from jobmecloud.applydocs.content import TailoredBullet, TailoredContent, TailoredRole
from jobmecloud.applydocs.pages import fit_pages, original_page_count, unverified_page_counter


def texts(data):
    return [p.text for p in docx.Document(io.BytesIO(data)).paragraphs]


def fake_counter(pages_by_bullets):
    def count(data):
        return pages_by_bullets(sum(1 for t in texts(data) if t.startswith("B")))
    return count


def content(n):
    return TailoredContent(headline="", summary="S", skills=[], roles=[TailoredRole(role=0, bullets=[TailoredBullet(source=i, text=f"B{i}") for i in range(n)])])


def render_fn(c):
    d = docx.Document()
    for r in c.roles:
        for b in r.bullets:
            d.add_paragraph(b.text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_drops_bullets_until_pages_match():
    r = fit_pages(render_fn, content(6), content(6), target=2, counter=fake_counter(lambda n: 3 if n > 4 else 2))
    assert r.pages == 2 and r.note == "2 pages, same as your resume" and len(r.content.roles[0].bullets) == 4


def test_puts_back_left_out_bullets_when_short():
    r = fit_pages(render_fn, content(2), content(5), target=2, counter=fake_counter(lambda n: 2 if n >= 4 else 1))
    assert r.pages == 2 and [b.source for b in r.content.roles[0].bullets] == [0, 1, 2, 3]


def test_word_missing_uses_estimate():
    long = content(3)
    long.roles[0].bullets[0].text = "B" + "x" * 400
    r = fit_pages(render_fn, long, content(3), target=2, counter=lambda data: None)
    assert r.note == "Couldn't confirm the page count" and r.content.roles[0].bullets[0].text == "B0"


def test_closest_when_cannot_match():
    r = fit_pages(render_fn, content(2), content(2), target=2, counter=fake_counter(lambda n: 1))
    assert r.pages == 1 and r.note == "1 page; your resume has 2. JobMe kept the closest version."


def test_original_page_count_reads_docx_metadata():
    assert original_page_count(set_app_pages(make_resume_docx(), 2)) == 2


def test_unverified_counter_never_confirms():
    assert unverified_page_counter(make_resume_docx()) is None


def test_original_page_count_bad_input():
    assert original_page_count(b"not a zip") is None
    assert original_page_count(set_app_pages(make_resume_docx(), 0)) is None
