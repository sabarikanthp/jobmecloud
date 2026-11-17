"""Web links the user types into the "What should change?" box, and where they go on the resume.

The AI only rewrites words. A link the user asks for is not something to be written by the AI (it could
invent or alter one), so the app finds the links the user typed and adds them to the contact line itself.
"""

import re
from collections.abc import Sequence
from urllib.parse import urlsplit

URL = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)
MAX_LINKS = 3


def _trim(url: str) -> str:
    return url.rstrip(".,;:!?")


def _key(link: str) -> str:
    link = re.sub(r"^https?://", "", link.strip().lower())
    link = re.sub(r"^www\.", "", link)
    return link.rstrip("/")


def feedback_links(feedback: str | None) -> list[str]:
    """The links in the text, shown short (no scheme, query or trailing slash), once each."""
    out: list[str] = []
    for raw in URL.findall(feedback or ""):
        try:
            parts = urlsplit(_trim(raw))
        except ValueError:
            continue
        host = (parts.hostname or "").lower()
        if not host:
            continue
        shown = _key(host + parts.path)
        if shown and shown not in out:
            out.append(shown)
    return out[:MAX_LINKS]


def new_links(contact_text: str, links: Sequence[str]) -> list[str]:
    """The links that are not already on the contact line."""
    have = {_key(t) for t in re.split(r"\s*[|·•,;]\s*|\s+", contact_text or "") if t}
    return [link for link in links if _key(link) not in have]


def contact_index(paragraphs: Sequence[tuple[str, str]]) -> int | None:
    """Which paragraph is the contact line, from (text, label) pairs: a contact-labelled paragraph with an
    email, else the last contact-labelled one, else an early paragraph that has an email."""
    contact = [i for i, (_, label) in enumerate(paragraphs) if label == "contact"]
    with_email = [i for i in contact if "@" in paragraphs[i][0]]
    if with_email:
        return with_email[0]
    if contact:
        return contact[-1]
    return next((i for i, (text, _) in enumerate(paragraphs[:8]) if "@" in text), None)
