"""Dashboard numbers. One small function per metric, each pure over a session and today."""

from datetime import date, timedelta

from sqlalchemy import func
from sqlmodel import Session, select

from jobmecloud.api.routes_followups import FollowUpRow
from jobmecloud.api.routes_followups import _row as _followup_row
from jobmecloud.db.models import ActivityLog, FollowUp, Interview, Job
from jobmecloud.jobs.tracking import utc_date, utc_midnight

OPEN_FOLLOWUP = ("Open", "Snoozed")
MAX_SOURCES = 10
UNKNOWN_SOURCE = "Unknown"


def _has_failed_rule(hard_rules) -> bool:
    if not isinstance(hard_rules, list):
        return False
    return any(isinstance(r, dict) and r.get("passed") is False for r in hard_rules)


def _logged_to(session: Session, status: str) -> set[int]:
    return set(session.exec(
        select(ActivityLog.job_id).where(ActivityLog.action == "status_changed",
                                         ActivityLog.to_value == status,
                                         ActivityLog.job_id.is_not(None))))


def found(session: Session, today: date) -> int:
    return session.exec(select(func.count()).select_from(Job)).one()


def matched_jobs(session: Session, today: date, cutoff: int) -> list[Job]:
    rows = session.exec(select(Job).where(Job.match_score >= cutoff))
    return [j for j in rows if not _has_failed_rule(j.hard_rules)]


def matched(session: Session, today: date, cutoff: int) -> int:
    return len(matched_jobs(session, today, cutoff))


def applied(session: Session, today: date) -> int:
    return session.exec(select(func.count()).select_from(Job).where(Job.applied_at.is_not(None))).one()


def interviewing(session: Session, today: date) -> int:
    ids = _logged_to(session, "Interviewing")
    ids |= set(session.exec(select(Interview.job_id)))
    ids |= set(session.exec(select(Job.id).where(Job.status.in_(("Interviewing", "Offer", "Accepted")))))
    return len(ids)


def offer(session: Session, today: date) -> int:
    ids = _logged_to(session, "Offer")
    ids |= set(session.exec(select(Job.id).where(Job.status.in_(("Offer", "Accepted")))))
    return len(ids)


def weekly(session: Session, today: date, weeks: int) -> list[dict]:
    this_monday = today - timedelta(days=today.weekday())
    first = this_monday - timedelta(weeks=weeks - 1)
    counts = {first + timedelta(weeks=i): 0 for i in range(weeks)}
    stamps = session.exec(select(Job.applied_at).where(Job.applied_at >= utc_midnight(first)))
    for stamp in stamps:
        d = utc_date(stamp)
        monday = d - timedelta(days=d.weekday())
        if monday in counts:
            counts[monday] += 1
    return [{"week_start": w.isoformat(), "applied": n} for w, n in counts.items()]


def response(session: Session, today: date) -> dict:
    applied_n, responded = session.exec(
        select(func.count(), func.count(Job.first_response_at)).where(Job.applied_at.is_not(None))).one()
    return {"applied": applied_n, "responded": responded,
            "rate": responded / applied_n if applied_n else None}


def skip_reasons(session: Session, today: date) -> list[dict]:
    rows = session.exec(
        select(Job.skip_reason, func.count()).where(Job.status == "Skipped", Job.skip_reason.is_not(None))
        .group_by(Job.skip_reason).order_by(func.count().desc(), Job.skip_reason)).all()
    return [{"reason": r, "count": n} for r, n in rows]


def sources(session: Session, today: date, cutoff: int) -> list[dict]:
    counts: dict[str, int] = {}
    for job in matched_jobs(session, today, cutoff):
        name = (job.source or "").strip() or UNKNOWN_SOURCE
        counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:MAX_SOURCES]
    return [{"source": s, "count": n} for s, n in ranked]


def followups(session: Session, today: date) -> dict[str, list[FollowUpRow]]:
    base = select(FollowUp).where(FollowUp.status.in_(OPEN_FOLLOWUP)).order_by(FollowUp.due_date, FollowUp.id)
    overdue = session.exec(base.where(FollowUp.due_date < today)).all()
    week = session.exec(base.where(FollowUp.due_date >= today,
                                   FollowUp.due_date <= today + timedelta(days=6))).all()
    return {"overdue": [_followup_row(session, fu, today) for fu in overdue],
            "this_week": [_followup_row(session, fu, today) for fu in week]}


def funnel(session: Session, today: date, cutoff: int) -> dict:
    return {"found": found(session, today), "matched": matched(session, today, cutoff),
            "applied": applied(session, today), "interviewing": interviewing(session, today),
            "offer": offer(session, today)}
