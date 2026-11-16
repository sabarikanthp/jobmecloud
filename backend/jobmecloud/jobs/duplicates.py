from sqlmodel import Session, select

from jobmecloud.db.models import Job
from jobmecloud.jobs.dedup import dedup_key, fallback_key, normalize_employer, normalize_url


def _words(text: str) -> str:
    return " ".join(text.lower().split())


def find_duplicate(
    session: Session,
    *,
    employer: str,
    title: str,
    location: str | None,
    requisition_id: str | None,
    url: str | None,
) -> Job | None:
    """The job already in the tracker that this one repeats, or None.

    One place decides this, so adding a job by hand and checking a pasted job agree.
    """
    keys = {dedup_key(employer, requisition_id, title, location), fallback_key(employer, title, location)}
    norm_url = normalize_url(url) if url else None
    emp_norm, title_norm = normalize_employer(employer), _words(title)
    for other in session.exec(select(Job)):
        if keys & {dedup_key(other.employer, other.requisition_id, other.title, other.location),
                   fallback_key(other.employer, other.title, other.location)}:
            return other
        if (normalize_employer(other.employer) == emp_norm and _words(other.title) == title_norm
                and (not location or not other.location or _words(other.location) == _words(location))):
            return other
        if norm_url and other.apply_url and normalize_url(other.apply_url) == norm_url:
            return other
    return None
