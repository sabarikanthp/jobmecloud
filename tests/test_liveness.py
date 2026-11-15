import pytest

from jobmecloud.agents.jobscout.liveness import check_page, classify_unclear, is_blocked_host
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.search import FetchResult
from fakes import FakeProvider

LONG = "Senior Data Engineer at Northwind Labs. " + "Responsibilities and requirements. " * 30


@pytest.mark.parametrize("status,text,expected", [
    (404, "", "closed"), (410, LONG, "closed"), (0, "", "unknown"), (403, LONG, "unknown"),
    (200, "Sorry, this job is no longer available.", "closed"), (200, "Loading...", "unknown"),
    (200, LONG, "active"), (200, "Welcome to our careers site. " * 40, "unclear")])
def test_check_page(status, text, expected):
    assert check_page(FetchResult("https://x.example", status, text), "Senior  Data Engineer") == expected


def test_blocked_hosts():
    assert is_blocked_host("https://www.linkedin.com/jobs/view/1") and is_blocked_host("https://linkedin.com/x")
    assert not is_blocked_host("https://notlinkedin.com/x")


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com./jobs/1",
    "https://LinkedIn.com:443/jobs/1",
    "https://user:pw@www.linkedin.com/jobs/1",
    "HTTPS://WWW.LINKEDIN.COM/jobs/1?x=1#y",
])
def test_blocked_host_variants(url):
    assert is_blocked_host(url)


def test_not_blocked_when_linkedin_only_in_path_or_userinfo():
    assert not is_blocked_host("https://a.example/linkedin.com")
    assert not is_blocked_host("https://www.linkedin.com@a.example/x")


def test_classify_unclear_uses_the_model():
    p = FakeProvider(replies=['{"state": "closed"}'])
    costs = CostTracker({}, 0)
    assert classify_unclear(p, "m", "text", "Eng", costs) == "closed" and costs.input_tokens == 10
