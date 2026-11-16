from fakes import add_job
from sqlmodel import Session

from jobmecloud.jobs.duplicates import find_duplicate


def _find(engine, **kw):
    args = {"employer": "Northwind Labs", "title": "Senior Data Engineer", "location": None,
            "requisition_id": None, "url": None}
    with Session(engine) as s:
        found = find_duplicate(s, **{**args, **kw})
        return found.id if found else None


def test_same_requisition_is_a_duplicate_even_with_a_reworded_title(engine):
    job = add_job(engine, requisition_id="R-1001", title="Data Engineering Lead")
    assert _find(engine, title="Lead, Data Engineering", requisition_id="R-1001") == job


def test_same_employer_title_and_location_is_a_duplicate(engine):
    job = add_job(engine, location="Boston, MA")
    assert _find(engine, location="boston, ma") == job


def test_a_missing_location_on_either_side_still_matches(engine):
    job = add_job(engine, location="Boston, MA")
    assert _find(engine, location=None) == job
    other = add_job(engine, employer="Acme", title="VP Data", location=None)
    assert _find(engine, employer="Acme", title="VP Data", location="Austin, TX") == other


def test_same_address_is_a_duplicate_ignoring_case_and_trailing_slash(engine):
    job = add_job(engine, employer="Acme", title="Director", apply_url="https://Jobs.Example.com/p/9/")
    assert _find(engine, employer="Other", title="Else", url="https://jobs.example.com/p/9") == job


def test_different_requisitions_at_the_same_employer_are_not_duplicates(engine):
    add_job(engine, requisition_id="R-1", title="Data Engineer")
    assert _find(engine, title="Platform Lead", requisition_id="R-2") is None


def test_an_unrelated_job_is_not_a_duplicate(engine):
    add_job(engine)
    assert _find(engine, employer="Globex", title="Chef") is None


def test_the_finder_returns_the_existing_job(engine):
    job = add_job(engine)
    with Session(engine) as s:
        found = find_duplicate(s, employer="Northwind Labs", title="Senior Data Engineer",
                               location=None, requisition_id=None, url=None)
        assert found is not None and found.id == job and found.title == "Senior Data Engineer"


def test_different_requisitions_with_the_same_title_are_not_duplicates(engine):
    add_job(engine, requisition_id="R-1", title="Senior Data Engineer", location=None)
    assert _find(engine, requisition_id="R-2", title="Senior Data Engineer") is None
    assert _find(engine, requisition_id="R-1", title="Senior Data Engineer") is not None


def test_the_same_address_is_still_a_duplicate_even_with_different_requisitions(engine):
    job = add_job(engine, requisition_id="R-1", apply_url="https://jobs.example.com/p/9")
    assert _find(engine, requisition_id="R-2", title="Else", employer="Other", url="https://jobs.example.com/p/9") == job
