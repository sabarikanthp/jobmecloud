"""Find the jobs already in the tracker that a new job may repeat.

Code decides this, not the AI: it is free, quick and explainable. A strong match is the same job for all practical
purposes (same link, same requisition, same employer and title). A possible match deserves a look (the same role
reposted under a new requisition, a reworded title, or the same posting text under another company name).
"""

import re
from dataclasses import dataclass
from typing import Literal

from sqlmodel import Session, select

from jobmecloud.db.models import Job
from jobmecloud.jobs.dedup import normalize_employer, normalize_url

LIMIT = 5
TITLE_SIMILAR = 0.6   # share of title words in common (of all the words used) to be called similar
TEXT_SIMILAR = 0.6    # share of 4-word phrases in common to be called the same posting text
TEXT_CHARS = 4000     # how much of a description is compared
MIN_TEXT_CHARS = 200  # shorter descriptions say too little to compare
_STOP = {"of", "and", "the", "a", "an", "for", "in", "to", "at", "with"}


@dataclass
class Match:
    job: Job
    strength: Literal["strong", "possible"]
    reasons: list[str]
    score: float


def _title_words(title: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[a-z0-9]+", (title or "").lower()) if w not in _STOP)


def _phrases(text: str | None) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9]+", (text or "")[:TEXT_CHARS].lower())
    return {tuple(words[i:i + 4]) for i in range(len(words) - 3)}


def _jaccard(a: set | frozenset, b: set | frozenset) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def _same_place(a: str | None, b: str | None) -> bool:
    a, b = " ".join((a or "").lower().split()), " ".join((b or "").lower().split())
    return not a or not b or a == b


def find_similar(
    session: Session,
    *,
    employer: str,
    title: str,
    location: str | None,
    requisition_id: str | None,
    url: str | None,
    description: str | None = None,
    exclude_id: int | None = None,
    limit: int = LIMIT,
) -> list[Match]:
    emp = normalize_employer(employer or "")
    words = _title_words(title)
    req = (requisition_id or "").strip().lower()
    norm_url = normalize_url(url) if url else None
    mine = _phrases(description) if len((description or "").strip()) >= MIN_TEXT_CHARS else set()

    found: list[Match] = []
    for other in session.exec(select(Job)):
        if other.id == exclude_id:
            continue
        reasons: list[str] = []
        strong, score = False, 0.0
        other_req = (other.requisition_id or "").strip().lower()
        same_employer = bool(emp) and normalize_employer(other.employer or "") == emp

        if norm_url and other.apply_url and normalize_url(other.apply_url) == norm_url:
            strong, score = True, 1.0
            reasons.append("Same link")
        if same_employer:
            theirs = _title_words(other.title)
            conflict = bool(req and other_req and req != other_req)
            if req and other_req and req == other_req:
                strong, score = True, 1.0
                reasons.append(f"Same requisition ({requisition_id.strip()})")
            elif words and words == theirs:
                if conflict:
                    score = max(score, 0.8)
                    reasons.append("Same title under another requisition (a repost?)")
                elif _same_place(location, other.location):
                    strong, score = True, 1.0
                    reasons.append("Same employer and title")
                else:
                    score = max(score, 0.75)
                    reasons.append("Same employer and title, different location")
            elif (similar := _jaccard(words, theirs)) >= TITLE_SIMILAR:
                score = max(score, 0.5 + 0.3 * similar)
                reasons.append("Same employer, similar title")
        if mine and not strong:
            theirs_text = _phrases(other.description) if len((other.description or "").strip()) >= MIN_TEXT_CHARS else set()
            shared = _jaccard(mine, theirs_text)
            if shared >= TEXT_SIMILAR:
                score = max(score, 0.5 + 0.4 * shared)
                reasons.append(f"Posting text is {round(shared * 100)}% the same")
        if reasons:
            found.append(Match(other, "strong" if strong else "possible", reasons, score))

    found.sort(key=lambda m: (m.strength != "strong", -m.score, -(m.job.id or 0)))
    return found[:limit]
