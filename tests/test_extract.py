import json

from jobmecloud.agents.jobscout.extract import extract_posting, posting_from_candidate
from jobmecloud.agents.jobscout.search_agent import Candidate
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.search import FetchResult
from fakes import FakeProvider

LONG = "Senior Data Engineer at Northwind Labs. " + "Responsibilities and requirements. " * 30


def test_extract_normalizes_and_falls_back():
    reply = json.dumps({"employer": "", "title": "Senior Data Engineer", "requisition_id": "R-12", "location": "",
                        "work_mode": "unknown", "pay_min": 180000, "pay_max": 150000, "posted_date": "2026-13-40",
                        "apply_url": ""})
    c = Candidate("https://northwind.example/j/1", "Northwind Labs", "Data Engineer")
    post = extract_posting(FakeProvider(replies=[reply]), "m", c, FetchResult(c.url, 200, LONG), CostTracker({}, 0))
    assert (post.employer, post.title, post.requisition_id, post.location, post.work_mode) == (
        "Northwind Labs", "Senior Data Engineer", "R-12", None, None)
    assert (post.pay_min, post.pay_max, post.posted_date, post.apply_url) == (150000, 180000, None, c.url)
    assert post.description == LONG


def test_posting_from_candidate():
    p = posting_from_candidate(Candidate("https://a.example", "A", "T"))
    assert (p.employer, p.title, p.apply_url, p.description, p.pay_max) == ("A", "T", "https://a.example", None, None)


def _extracted_apply_url(apply_url):
    reply = json.dumps({"employer": "A", "title": "T", "requisition_id": "", "location": "", "work_mode": "remote",
                        "pay_min": 0, "pay_max": 0, "posted_date": "", "apply_url": apply_url})
    c = Candidate("https://a.example/j/1", "A", "T")
    return extract_posting(FakeProvider(replies=[reply]), "m", c, FetchResult(c.url, 200, LONG), CostTracker({}, 0)).apply_url


def test_extract_keeps_only_valid_apply_url():
    assert _extracted_apply_url(" https://apply.example/j/1?src=x ") == "https://apply.example/j/1?src=x"
    for bad in ["/apply/1", "apply.example/j/1", "mailto:jobs@a.example", "javascript:alert(1)", "http://[oops/x",
                "https://", "https://www.linkedin.com/jobs/view/1", "ftp://a.example/x"]:
        assert _extracted_apply_url(bad) == "https://a.example/j/1", bad


def test_extract_accepts_whole_number_float_pay():
    reply = json.dumps({"employer": "A", "title": "T", "requisition_id": "", "location": "", "work_mode": "remote",
                        "pay_min": 120000.0, "pay_max": 150000.0, "posted_date": "", "apply_url": ""})
    c = Candidate("https://a.example/j/1", "A", "T")
    post = extract_posting(FakeProvider(replies=[reply]), "m", c, FetchResult(c.url, 200, LONG), CostTracker({}, 0))
    assert (post.pay_min, post.pay_max) == (120000, 150000)
    assert type(post.pay_min) is int and type(post.pay_max) is int
