"""Read-side views of a job: list rows, the detail with its timeline, and the list query."""

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy import Float, and_, cast, func, text
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from jobmecloud.api.routes_contacts import _row as _contact_row
from jobmecloud.api.routes_followups import _ORDER as _BUCKET_ORDER
from jobmecloud.api.routes_followups import _row as _followup_row
from jobmecloud.db.models import ActivityLog, Contact, CustomField, CustomValue, FollowUp, Interview, Job
from jobmecloud.jobs import custom_fields, followups as fu_rules
from jobmecloud.jobs.tracking import allowed_next, local_date, local_midnight, utc_date, utc_midnight

OPEN_FOLLOWUP = ("Open", "Snoozed")
Sort = Literal["first_seen", "match", "employer", "status", "applied"]
_FLAG_SQL = (
    "EXISTS (SELECT 1 FROM json_each(job.flags) WHERE lower(json_each.value) LIKE :flag ESCAPE '\\')"
)


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def iso_dt(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def is_linkedin(url: str | None) -> bool:
    if not url:
        return False
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return False
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def _row(job: Job, next_due: date | None) -> dict:
    return {
        "id": job.id, "employer": job.employer, "title": job.title, "status": job.status,
        "match_score": job.match_score, "source": job.source, "location": job.location,
        "work_mode": job.work_mode, "requisition_id": job.requisition_id, "pay_min": job.pay_min, "pay_max": job.pay_max,
        "pay_verified": job.pay_verified,
        "first_seen_date": iso(utc_date(job.first_seen_at) if job.origin == "import" else local_date(job.first_seen_at)),
        "applied_date": iso(utc_date(job.applied_at)),
        "first_response_date": iso(utc_date(job.first_response_at)),
        "outcome_date": iso(utc_date(job.outcome_at)),
        "flags": list(job.flags or []), "apply_url": job.apply_url,
        "linkedin": is_linkedin(job.apply_url), "docs_ready": bool(job.docs_folder),
        "has_open_followup": next_due is not None, "next_followup_due": iso(next_due),
    }


def _next_due(session: Session, job_ids: list[int]) -> dict[int, date]:
    if not job_ids:
        return {}
    rows = session.exec(
        select(FollowUp.job_id, func.min(FollowUp.due_date))
        .where(FollowUp.job_id.in_(job_ids), FollowUp.status.in_(OPEN_FOLLOWUP))
        .group_by(FollowUp.job_id)).all()
    return {job_id: due for job_id, due in rows}


def job_row(session: Session, job: Job, today: date) -> dict:
    return _row(job, _next_due(session, [job.id]).get(job.id))


def job_detail(session: Session, job: Job, today: date) -> dict:
    out = job_row(session, job, today)
    contacts = session.exec(select(Contact).where(Contact.job_id == job.id)
                            .order_by(Contact.id.desc())).all()
    fus = [(fu, fu_rules.bucket(fu, today)) for fu in session.exec(
        select(FollowUp).where(FollowUp.job_id == job.id))]
    fus.sort(key=lambda r: (_BUCKET_ORDER[r[1]], r[0].due_date.toordinal(), r[0].id))
    interviews = session.exec(select(Interview).where(Interview.job_id == job.id)
                              .order_by(Interview.date.is_(None), Interview.date, Interview.id)).all()
    timeline = session.exec(select(ActivityLog).where(ActivityLog.job_id == job.id)
                            .order_by(ActivityLog.at.desc(), ActivityLog.id.desc())).all()
    out.update({
        "description": job.description, "reasons": job.reasons, "gaps": job.gaps,
        "hard_rules": job.hard_rules, "notes": job.notes, "skip_reason": job.skip_reason,
        "skip_note": job.skip_note, "liveness": job.liveness, "repost_of_id": job.repost_of_id,
        "docs_folder": job.docs_folder, "docs_note": job.docs_note, "docs_error": job.docs_error,
        "allowed_next": allowed_next(job),
        "fields": {str(k): v for k, v in custom_fields.values_for(session, [job.id]).get(job.id, {}).items()},
        "contacts": [_contact_row(session, c).model_dump() for c in contacts],
        "followups": [_followup_row(session, fu, today).model_dump() for fu, _ in fus],
        "interviews": [{"id": i.id, "date": iso_dt(i.date), "stage": i.stage, "notes": i.notes}
                       for i in interviews],
        "timeline": [{"at": iso_dt(t.at), "actor": t.actor, "action": t.action,
                      "entity_type": t.entity_type, "from_value": t.from_value,
                      "to_value": t.to_value, "note": t.note} for t in timeline],
    })
    return out


def _like(value: str) -> str:
    escaped = value.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_jobs(session: Session, *, status: list[str] | None, min_score: int | None, q: str | None,
              source: str | None, from_: date | None, to_: date | None, flag: str | None,
              has_followup: bool | None, sort: Sort | str, direction: Literal["asc", "desc"],
              limit: int, offset: int, fields: list[int] | None = None,
              cf: list[tuple[int, str]] | None = None) -> tuple[int, list[dict]]:
    filters = []
    known = {f.id for f in session.exec(select(CustomField))} if cf else set()
    for field_id, value in cf or []:
        if field_id not in known:
            continue  # a deleted field's filter is ignored
        filters.append(Job.id.in_(select(CustomValue.job_id).where(
            CustomValue.field_id == field_id, CustomValue.value == value)))
    if status:
        filters.append(Job.status.in_(status))
    if min_score is not None:
        filters.append(Job.match_score >= min_score)
    needle = (q or "").strip()
    if needle:
        pattern = _like(needle)
        filters.append(func.lower(Job.employer).like(pattern, escape="\\")
                       | func.lower(Job.title).like(pattern, escape="\\"))
    if source:
        filters.append(Job.source == source)
    if from_ is not None or to_ is not None:
        # Imports are calendar days at UTC midnight; real instants are found on their local day.
        imported = Job.origin == "import"
        real = Job.origin != "import"
        for_import, for_real = [imported], [real]
        if from_ is not None:
            for_import.append(Job.first_seen_at >= utc_midnight(from_))
            for_real.append(Job.first_seen_at >= local_midnight(from_))
        if to_ is not None:
            for_import.append(Job.first_seen_at < utc_midnight(to_ + timedelta(days=1)))
            for_real.append(Job.first_seen_at < local_midnight(to_ + timedelta(days=1)))
        filters.append(and_(*for_import) | and_(*for_real))
    needle = (flag or "").strip()
    if needle:
        filters.append(text(_FLAG_SQL).bindparams(flag=_like(needle)))
    if has_followup is not None:
        open_fu = select(FollowUp.id).where(FollowUp.job_id == Job.id,
                                            FollowUp.status.in_(OPEN_FOLLOWUP)).exists()
        filters.append(open_fu if has_followup else ~open_fu)

    custom = None
    if sort.startswith("field:"):
        custom = session.get(CustomField, int(sort[6:]))
    if custom is not None:
        cv = aliased(CustomValue)
        key = cast(cv.value, Float) if custom.type == "number" else func.lower(cv.value)
        base = select(Job, func.count().over()).join(
            cv, and_(cv.job_id == Job.id, cv.field_id == custom.id), isouter=True)
    else:
        key = {"first_seen": Job.first_seen_at, "match": Job.match_score, "employer": func.lower(Job.employer),
               "status": Job.status, "applied": Job.applied_at}.get(sort, Job.first_seen_at)
        base = select(Job, func.count().over())
    ordered = key.asc() if direction == "asc" else key.desc()
    id_order = Job.id.asc() if direction == "asc" else Job.id.desc()
    query = (base.where(*filters)
             .order_by(key.is_(None), ordered, id_order).limit(limit).offset(offset))

    found = session.exec(query).all()
    if found:
        total = found[0][1]
    elif offset:  # a page past the end carries no window count
        total = session.exec(select(func.count()).select_from(Job).where(*filters)).one()
    else:
        total = 0
    jobs = [j for j, _ in found]
    due = _next_due(session, [j.id for j in jobs])
    rows = [_row(j, due.get(j.id)) for j in jobs]
    if fields:
        values = custom_fields.values_for(session, [j.id for j in jobs])
        wanted = set(fields)
        for j, row in zip(jobs, rows):
            row["fields"] = {str(k): v for k, v in values.get(j.id, {}).items() if k in wanted}
    return total, rows
