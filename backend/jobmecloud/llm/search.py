"""Web search backends (Tavily, Brave) and a simple page fetcher."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urljoin, urlparse, urlsplit

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; JobMe/0.1)"
TIMEOUT = 20
MAX_RESULTS_LIMIT = 20
MAX_DOWNLOAD_BYTES = 2_000_000
MAX_REDIRECTS = 5
QUOTA_COPY = "The search service says you've used up your searches for now. Try again later or check your plan."
BAD_REPLY_COPY = "The search service sent back something JobMe couldn't read."


class SearchError(Exception):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str


class SearchBackend(Protocol):
    def search(self, query: str, max_results: int = 8) -> list[SearchResult]: ...


def _send(client: httpx.Client | None, method: str, url: str, **kwargs) -> httpx.Response:
    try:
        if client is not None:
            response = client.request(method, url, **kwargs)
        else:
            with httpx.Client(timeout=TIMEOUT) as own:
                response = own.request(method, url, **kwargs)
    except httpx.HTTPError:
        raise SearchError("Couldn't reach the search service. Check your internet connection.") from None
    if response.status_code in (429, 432, 433):
        raise SearchError(QUOTA_COPY)
    if response.status_code in (401, 403):
        raise SearchError("The search key was rejected")
    if response.status_code != 200:
        raise SearchError(f"Search service error {response.status_code}")
    return response


def _clamp(max_results: int) -> int:
    return max(1, min(int(max_results), MAX_RESULTS_LIMIT))


def _json(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError:
        raise SearchError(BAD_REPLY_COPY) from None
    if not isinstance(data, dict):
        raise SearchError(BAD_REPLY_COPY)
    return data


def _to_results(items, snippet_key: str) -> list[SearchResult]:
    out = []
    for r in items or []:
        if not isinstance(r, dict) or not r.get("url"):
            continue
        out.append(SearchResult(r.get("title") or "", r["url"], r.get(snippet_key) or ""))
    return out


class TavilySearch:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self._key = api_key
        self._client = client

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        response = _send(
            self._client,
            "POST",
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {self._key}"},
            json={"query": query, "max_results": _clamp(max_results)},
        )
        return _to_results(_json(response).get("results"), "content")


class BraveSearch:
    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self._key = api_key
        self._client = client

    def search(self, query: str, max_results: int = 8) -> list[SearchResult]:
        response = _send(
            self._client,
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": self._key},
            params={"q": query, "count": _clamp(max_results)},
        )
        results = (_json(response).get("web") or {}).get("results")
        return _to_results(results, "description")


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    content_type: str = ""


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return []
    return [info[4][0] for info in infos]


BLOCKED_DOMAINS = ("linkedin.com",)


def is_blocked_host(url: str) -> bool:
    """True for hosts JobMe must never fetch: linkedin.com and its subdomains."""
    try:
        host = (urlsplit(url.strip()).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return any(host == d or host.endswith("." + d) for d in BLOCKED_DOMAINS)


def is_public_url(url: str, resolve: Callable[[str], list[str]] = _resolve) -> bool:
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not host:
        return False
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        addresses = resolve(host)
    if not addresses:
        return False
    try:
        return all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)
    except ValueError:
        return False


def _is_text_type(content_type: str) -> bool:
    if not content_type:
        return True
    ct = content_type.split(";")[0].strip().lower()
    return ct.startswith("text/") or "html" in ct or "xml" in ct or "json" in ct


def _decode(raw: bytes, encoding: str | None) -> str:
    try:
        return raw.decode(encoding or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _looks_like_html(content_type: str, text: str) -> bool:
    if "html" in content_type.lower():
        return True
    head = text[:1000].lower()
    return "<!doctype html" in head or "<html" in head or "<body" in head


def _fetch_with(
    client: httpx.Client, url: str, max_chars: int, resolve: Callable[[str], list[str]]
) -> FetchResult:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        # Every hop is checked, so a redirect can't lead to a private or blocked host.
        if not is_public_url(current, resolve) or is_blocked_host(current):
            return FetchResult(url, 0, "")
        with client.stream("GET", current, headers={"User-Agent": USER_AGENT}) as response:
            location = response.headers.get("location")
            if response.status_code in (301, 302, 303, 307, 308) and location:
                current = urljoin(current, location)
                continue
            content_type = response.headers.get("content-type", "")
            if not _is_text_type(content_type):
                return FetchResult(url, response.status_code, "", content_type)
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size >= MAX_DOWNLOAD_BYTES:
                    break
            text = _decode(b"".join(chunks)[:MAX_DOWNLOAD_BYTES], response.encoding)
            status = response.status_code
        break
    else:
        return FetchResult(url, 0, "")
    if _looks_like_html(content_type, text):
        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
    return FetchResult(url, status, text[:max_chars], content_type)


def fetch_page(
    url: str,
    client: httpx.Client | None = None,
    max_chars: int = 50_000,
    resolve: Callable[[str], list[str]] = _resolve,
) -> FetchResult:
    try:
        if client is not None:
            return _fetch_with(client, url, max_chars, resolve)
        with httpx.Client(timeout=TIMEOUT) as own:
            return _fetch_with(own, url, max_chars, resolve)
    except (httpx.HTTPError, httpx.InvalidURL):
        return FetchResult(url, 0, "")
