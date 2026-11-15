import json

import httpx
import pytest

from jobmecloud.llm.search import (
    BraveSearch,
    SearchError,
    SearchResult,
    TavilySearch,
    fetch_page,
)

PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731


def mock(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_tavily_maps_results():
    def handler(req):
        assert req.method == "POST"
        assert str(req.url) == "https://api.tavily.com/search"
        assert req.headers["Authorization"] == "Bearer tk"
        assert json.loads(req.read()) == {"query": "director engineering", "max_results": 3}
        return httpx.Response(200, json={"results": [{"title": "Dir Eng", "url": "https://a.co/j/1", "content": "..."}]})

    r = TavilySearch("tk", client=mock(handler)).search("director engineering", max_results=3)
    assert r == [SearchResult("Dir Eng", "https://a.co/j/1", "...")]


def test_brave_maps_results():
    def handler(req):
        assert req.method == "GET"
        assert req.url.host == "api.search.brave.com"
        assert req.url.path == "/res/v1/web/search"
        assert req.url.params["q"] == "director engineering"
        assert req.url.params["count"] == "5"
        assert req.headers["X-Subscription-Token"] == "bk"
        return httpx.Response(200, json={"web": {"results": [{"title": "T", "url": "https://b.co", "description": "D"}]}})

    r = BraveSearch("bk", client=mock(handler)).search("director engineering", max_results=5)
    assert r == [SearchResult("T", "https://b.co", "D")]


def test_brave_no_web_results():
    assert BraveSearch("bk", client=mock(lambda r: httpx.Response(200, json={}))).search("x") == []


@pytest.mark.parametrize("code", [401, 403])
def test_bad_key_raises_friendly(code):
    with pytest.raises(SearchError, match="rejected"):
        TavilySearch("bad", client=mock(lambda r: httpx.Response(code))).search("x")


def test_other_status_raises():
    with pytest.raises(SearchError, match="Search service error 500"):
        BraveSearch("k", client=mock(lambda r: httpx.Response(500))).search("x")


def test_search_network_error():
    def boom(req):
        raise httpx.ConnectError("down")

    with pytest.raises(SearchError, match="Couldn't reach the search service"):
        TavilySearch("k", client=mock(boom)).search("x")


def test_fetch_page_strips_html():
    html = "<html><script>x()</script><style>p{}</style><body><h1>Director</h1><p>Apply now</p></body></html>"
    r = fetch_page("https://a.co/j/1", client=mock(lambda r: httpx.Response(200, text=html, headers={"content-type": "text/html"})), resolve=PUBLIC)
    assert r.status == 200 and "Director Apply now" in r.text and "x()" not in r.text and "p{}" not in r.text


def test_fetch_page_truncates():
    html = "<p>" + "a" * 100 + "</p>"
    r = fetch_page("https://a.co", client=mock(lambda r: httpx.Response(200, text=html, headers={"content-type": "text/html"})), max_chars=10, resolve=PUBLIC)
    assert len(r.text) == 10


def test_fetch_page_non_html_returns_raw_truncated():
    r = fetch_page("https://a.co/x.json", client=mock(lambda r: httpx.Response(200, text='{"a": "<b>1</b>"}' + "z" * 50, headers={"content-type": "application/json"})), max_chars=20, resolve=PUBLIC)
    assert r.text == '{"a": "<b>1</b>"}' + "zzz"
    assert len(r.text) == 20


def test_fetch_page_sends_user_agent_and_follows_redirects():
    def handler(req):
        if req.url.path == "/old":
            return httpx.Response(302, headers={"location": "/new"})
        assert req.headers["User-Agent"] == "Mozilla/5.0 (compatible; JobMe/0.1)"
        return httpx.Response(200, text="<p>ok</p>", headers={"content-type": "text/html"})

    r = fetch_page("https://a.co/old", client=httpx.Client(transport=httpx.MockTransport(handler)), resolve=PUBLIC)
    assert r.status == 200 and r.text == "ok"


def test_fetch_page_network_error():
    def boom(req):
        raise httpx.ConnectError("down")

    r = fetch_page("https://a.co", client=mock(boom), resolve=PUBLIC)
    assert (r.url, r.status, r.text) == ("https://a.co", 0, "")


def test_fetch_page_sniffs_html_without_html_content_type():
    html = "<html><script>x()</script><body><h1>Director</h1><p>Apply now</p></body></html>"
    r = fetch_page("https://a.co/j/1", client=mock(lambda r: httpx.Response(200, text=html)), resolve=PUBLIC)
    assert "Director Apply now" in r.text and "x()" not in r.text


def test_fetch_refuses_private_addresses():
    called = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: called.append(r) or httpx.Response(200)))
    assert fetch_page("http://127.0.0.1/admin", client=client).status == 0
    assert fetch_page("http://intranet/", client=client, resolve=lambda h: ["10.0.0.5"]).status == 0
    assert fetch_page("file:///c:/x", client=client).status == 0
    assert called == []


def test_fetch_refuses_redirect_to_private():
    def handler(r):
        if r.url.host == "jobs.example.com":
            return httpx.Response(302, headers={"location": "http://internal.example/"})
        return httpx.Response(200, text="secret")

    resolve = lambda h: ["93.184.216.34"] if h == "jobs.example.com" else ["192.168.1.2"]  # noqa: E731
    r = fetch_page("https://jobs.example.com/1", client=httpx.Client(transport=httpx.MockTransport(handler)), resolve=resolve)
    assert r.status == 0 and r.text == ""


def test_fetch_caps_size_and_skips_pdf():
    big = httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"a" * 5_000_000))
    assert len(fetch_page("https://e.example/", client=httpx.Client(transport=big), resolve=PUBLIC).text) <= 50_000
    pdf = httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.7"))
    r = fetch_page("https://e.example/a.pdf", client=httpx.Client(transport=pdf), resolve=PUBLIC)
    assert (r.status, r.text, r.content_type) == (200, "", "application/pdf")


def test_fetch_too_many_redirects():
    loop = httpx.MockTransport(lambda r: httpx.Response(302, headers={"location": "/again"}))
    assert fetch_page("https://e.example/", client=httpx.Client(transport=loop), resolve=PUBLIC).status == 0


def test_fetch_invalid_url():
    assert fetch_page("http://[bad", client=mock(lambda r: httpx.Response(200)), resolve=PUBLIC).status == 0


def test_search_quota_bad_json_none_fields_and_clamp():
    seen = {}

    def tavily(r):
        seen["body"] = json.loads(r.content)
        return httpx.Response(200, json={"results": [{"title": None, "url": "https://a.example", "content": None},
                                                     {"title": "x", "url": None}]})

    out = TavilySearch("k", client=httpx.Client(transport=httpx.MockTransport(tavily))).search("q", max_results=50)
    assert seen["body"]["max_results"] == 20 and out == [SearchResult("", "https://a.example", "")]
    for code in (429, 432, 433):
        c = httpx.Client(transport=httpx.MockTransport(lambda r, code=code: httpx.Response(code)))
        with pytest.raises(SearchError, match="used up your searches"):
            TavilySearch("k", client=c).search("q")
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>")))
    with pytest.raises(SearchError, match="couldn't read"):
        BraveSearch("k", client=c).search("q")


def test_brave_clamps_low():
    seen = {}

    def handler(r):
        seen["count"] = r.url.params["count"]
        return httpx.Response(200, json={})

    BraveSearch("k", client=mock(handler)).search("q", max_results=0)
    assert seen["count"] == "1"


def test_fetch_refuses_redirect_to_linkedin():
    seen = []

    def handler(r):
        seen.append(r.url.host)
        if r.url.host == "jobs.example.com":
            return httpx.Response(302, headers={"location": "https://www.LinkedIn.com/jobs/view/1"})
        return httpx.Response(200, text="Senior Data Engineer " * 50)

    r = fetch_page("https://jobs.example.com/1", client=mock(handler), resolve=PUBLIC)
    assert (r.status, r.text) == (0, "") and seen == ["jobs.example.com"]
    assert fetch_page("https://linkedin.com/jobs/1", client=mock(handler), resolve=PUBLIC).status == 0
    assert seen == ["jobs.example.com"]
