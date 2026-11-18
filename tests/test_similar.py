from fakes import add_job
from sqlmodel import Session

from jobmecloud.jobs.similar import find_similar

POSTING = ("We are hiring a Director of Software Engineering to lead platform teams. You will own delivery, mentor "
           "technical leads, manage budgets and vendors, and partner with product on the roadmap. " * 6)


def _find(engine, exclude=None, **kw):
    args = {"employer": "Northwind Labs", "title": "Senior Data Engineer", "location": None,
            "requisition_id": None, "url": None, "description": None}
    with Session(engine) as s:
        return [(m.job.id, m.strength, m.reasons) for m in find_similar(s, exclude_id=exclude, **{**args, **kw})]


def test_the_same_link_is_a_strong_match(engine):
    job = add_job(engine, employer="Elsewhere", title="Other", apply_url="https://jobs.example.com/p/9/")
    [(jid, strength, reasons)] = _find(engine, employer="Acme", title="Else", url="https://JOBS.example.com/p/9")
    assert (jid, strength) == (job, "strong") and "link" in reasons[0].lower()


def test_the_same_employer_and_requisition_is_a_strong_match(engine):
    job = add_job(engine, requisition_id="R-7", title="Data Lead")
    [(jid, strength, reasons)] = _find(engine, title="Lead of Data", requisition_id="r-7")
    assert (jid, strength) == (job, "strong") and "requisition" in reasons[0].lower()


def test_the_same_employer_and_title_without_a_requisition_is_strong(engine):
    job = add_job(engine, location="Boston, MA")
    assert [(j, s) for j, s, _ in _find(engine, location=None)] == [(job, "strong")]


def test_the_same_title_under_a_different_requisition_is_only_a_possible_repost(engine):
    job = add_job(engine, requisition_id="R-1")
    [(jid, strength, reasons)] = _find(engine, requisition_id="R-2")
    assert (jid, strength) == (job, "possible") and "repost" in " ".join(reasons).lower()


def test_a_similar_title_at_the_same_employer_is_possible(engine):
    job = add_job(engine, title="Director, Software Engineering")
    assert [(j, s) for j, s, _ in _find(engine, title="Director of Software Engineering Platform")] == [(job, "possible")]


def test_matching_posting_text_finds_a_job_under_a_different_employer_name(engine):
    job = add_job(engine, employer="Staffing Partner (anonymous company)", title="Director, Engineering",
                  description=POSTING)
    found = _find(engine, employer="Umbrella Press", title="Director of Software Engineering", description=POSTING)
    assert [(j, s) for j, s, _ in found] == [(job, "possible")] and "text" in found[0][2][0].lower()


def test_unrelated_jobs_are_not_matches(engine):
    add_job(engine, employer="Globex", title="Chef", description="Cook food in a kitchen.")
    assert _find(engine, description=POSTING) == []


def test_the_job_itself_is_never_its_own_match(engine):
    me = add_job(engine)
    assert _find(engine, exclude=me) == []


def test_strong_matches_come_first_and_the_list_is_limited(engine):
    possible = add_job(engine, title="Senior Data Engineer II")
    strong = add_job(engine, requisition_id="R-9")
    for i in range(8):
        add_job(engine, title=f"Senior Data Engineer {i}")
    found = _find(engine, requisition_id="R-9")
    assert found[0][0] == strong and len(found) <= 5
    assert possible not in [j for j, s, _ in found if s == "strong"]
