import re
from urllib.parse import urlsplit, urlunsplit

_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc"}


def normalize_employer(name: str) -> str:
    words = re.sub(r"[^\w\s]", " ", name.lower()).split()
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words)


def dedup_key(
    employer: str, requisition_id: str | None, title: str, location: str | None
) -> str:
    emp = normalize_employer(employer)
    req = (requisition_id or "").strip().lower()
    if req:
        return f"{emp}|req:{req}"
    return fallback_key(employer, title, location)


def fallback_key(employer: str, title: str, location: str | None) -> str:
    emp = normalize_employer(employer)
    t = " ".join(title.lower().split())
    loc = " ".join((location or "").lower().split())
    return f"{emp}|t:{t}|l:{loc}"


def normalize_url(url: str) -> str:
    """Lower-case scheme and host, drop the fragment and a trailing slash.

    Never raises: a URL that can't be parsed is just stripped and lower-cased.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip().lower()
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))
