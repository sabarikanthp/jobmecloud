"""The spreadsheet Import engine.

`run_import` reads one sheet of an uploaded workbook and adds, mutates and flushes rows in the
caller's session; it never commits. The route commits for a real import and rolls back for a dry
run, so the preview is exactly what Import will do.
"""

import re
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel
from sqlmodel import Session, select

from jobmecloud.db.batch import BATCH_ROWS
from jobmecloud.db.models import ActivityLog, Contact, CustomField, FollowUp, Job
from jobmecloud.importers.sheet_helpers import (
    KIND_FIELDS, default_status, guess_field_type, parse_pay, split_location_mode,
)
from jobmecloud.importers.tracker import MAX_ROWS, Sheet, cell_text, parse_date
from jobmecloud.jobs import custom_fields
from jobmecloud.jobs import followups as followup_rules
from jobmecloud.jobs.dedup import normalize_employer
from jobmecloud.jobs.status import STATUSES
from jobmecloud.jobs.tracking import (
    TrackingError, allowed_next, change_status, local_date, log, utc_date, utc_midnight,
)

JOBS_MAPPING_COPY = "Choose which columns hold the employer and the job title."
CONTACT_MAPPING_COPY = "Choose which column holds the contact's name."
SAMPLE_ROWS = 5
IMPORTED_FOLLOWUP = "Imported follow-up"
_ADVANCE = ("Applied", "Interviewing", "Offer", "Accepted", "Rejected", "Withdrawn")
_FLOW = ("Applied", "Interviewing", "Offer", "Accepted")


class ImportFailure(Exception):
    """A problem with the request, in plain words for the user."""


class NewField(BaseModel):
    name: str
    type: str
    choices: list[str] = []


class KeepAs(BaseModel):
    field_id: int | None = None
    new: NewField | None = None


class SheetImportIn(BaseModel):
    upload_id: str
    sheet: str
    kind: Literal["jobs", "applications", "contacts"]
    mapping: dict[str, str | None]
    keep: dict[str, KeepAs] = {}
    status_words: dict[str, str] = {}
    dry_run: bool = False


def _words(text: str) -> str:
    return " ".join(text.lower().split())


def _empty(value: Any) -> bool:
    return value is None or value == ""


class Run:
    """The state of one import: the sheet, the request, the existing jobs and the report."""

    def __init__(self, session: Session, sheet: Sheet, body: SheetImportIn, now: datetime) -> None:
        self.session, self.sheet, self.body, self.now = session, sheet, body, now
        self.idx = {key: sheet.columns.index(col) for key, col in body.mapping.items()
                    if col and col in sheet.columns}
        self.counts: Counter = Counter(new=0, updated=0, unchanged=0)
        self.counts["left_out"] = sheet.left_out
        self.attention: list[dict] = []
        self.words: dict[str, dict] = {}
        self.sample: list[dict] = []
        self.last_status = ""
        self.jobs: list[Job] = list(session.exec(select(Job)))
        self.keep: dict[int, CustomField] = {}  # column index -> field
        self.created: set[int] = set()  # ids of fields created by this import
        self.status_words = {k.strip().lower(): v for k, v in body.status_words.items()}

    def cell(self, row: list[Any], key: str) -> Any:
        i = self.idx.get(key)
        return row[i] if i is not None and i < len(row) else None

    def text(self, row: list[Any], key: str) -> str:
        return cell_text(self.cell(row, key))

    def flag(self, rowno: int, reason: str) -> None:
        self.attention.append({"row": rowno, "reason": reason})

    def left_out(self, rowno: int, reason: str) -> None:
        self.counts["left_out"] += 1
        self.flag(rowno, reason)

    def resolve_status(self, row: list[Any]) -> tuple[str, str]:
        """The status the sheet gives this row, and the word that decided it ("" and "" if none)."""
        raw = self.text(row, "status")
        if not raw:
            return "", ""
        low = raw.strip().lower()
        status = self.status_words[low] if low in self.status_words else default_status(raw)
        seen = self.words.setdefault(low, {"word": raw.strip(), "count": 0, "status": status})
        seen["count"] += 1
        return (status, raw.strip()) if status else ("", "")


def _check_request(run: Run) -> None:
    body = run.body
    required = [f.key for f in KIND_FIELDS[body.kind] if f.required]
    if any(not body.mapping.get(k) for k in required):
        raise ImportFailure(CONTACT_MAPPING_COPY if body.kind == "contacts" else JOBS_MAPPING_COPY)
    for col in [c for c in body.mapping.values() if c] + list(body.keep):
        if col not in run.sheet.columns:
            raise ImportFailure(f"That column isn't in the sheet: {col}")
    for word, status in body.status_words.items():
        if status and status not in STATUSES:
            raise ImportFailure(f"{status} isn't a status JobMe knows.")


def _prepare_fields(run: Run) -> None:
    """Resolve every "Keep as..." column to a field, creating the new ones."""
    if run.body.kind == "contacts":
        return  # custom fields belong to jobs
    existing = {f.name.casefold(): f for f in custom_fields.list_fields(run.session)}
    for col, keep in run.body.keep.items():
        i = run.sheet.columns.index(col)
        field: CustomField | None = None
        if keep.field_id is not None:
            field = run.session.get(CustomField, keep.field_id)
            if field is None:
                raise ImportFailure(custom_fields.GONE_COPY)
        elif keep.new is not None:
            field = existing.get(keep.new.name.strip().casefold())
            if field is None:
                options = list(keep.new.choices)
                if keep.new.type == "choice":
                    values = {cell_text(r[i]) for r in run.sheet.rows if i < len(r)} - {""}
                    options += sorted(values, key=str.lower)
                try:
                    field = custom_fields.create_field(
                        run.session, name=keep.new.name, type=keep.new.type, choices=options, at=run.now)
                except TrackingError as e:
                    raise ImportFailure(str(e)) from e
                existing[field.name.casefold()] = field
                run.created.add(field.id)
        if field is not None:
            run.keep[i] = field


def _kept_values(run: Run, rowno: int, row: list[Any]) -> tuple[dict[int, str], list[str]]:
    """The custom values this row gives, and "... in file" lines for cells that did not fit."""
    values: dict[int, str] = {}
    extras: list[str] = []
    for i, field in run.keep.items():
        raw = row[i] if i < len(row) else None
        text = cell_text(raw)
        if not text:
            continue
        if field.type == "date":
            parsed = parse_date(raw)
            text = parsed.isoformat() if parsed else text
        try:
            value = custom_fields.normalize_value(field, text)
        except TrackingError:
            if field.type == "choice":
                run.flag(rowno, f'{field.name}: "{text}" isn\'t one of the options.')
            else:
                extras.append(f"{field.name} in file: {text}")
            continue
        if value is not None:
            values[field.id] = value
    return values, extras


def _find(jobs: list[Job], employer: str, requisition: str, title: str, location: str) -> list[Job]:
    emp = normalize_employer(employer)
    req = requisition.strip().lower()
    out = []
    for j in jobs:
        if normalize_employer(j.employer) != emp:
            continue
        if req and j.requisition_id and j.requisition_id.strip():
            if j.requisition_id.strip().lower() == req:
                out.append(j)
            continue
        if _words(j.title) == _words(title) and (
                not location or not j.location or _words(j.location) == _words(location)):
            out.append(j)
    return out


def _append_once(notes: str | None, line: str) -> str:
    if not line:
        return notes or ""
    if not notes:
        return line
    return notes if line in notes else f"{notes}\n{line}"


def _date_cell(run: Run, row: list[Any], key: str, label: str, extras: list[str]) -> date | None:
    raw = run.cell(row, key)
    text = cell_text(raw)
    if not text:
        return None
    parsed = parse_date(raw)
    if parsed is None or parsed > local_date(run.now):  # unreadable, or not yet happened
        extras.append(f"{label} in file: {text}")
        return None
    return parsed


_MODES = {"remote", "hybrid", "on-site", "onsite", "on site"}


def _is_mode(value: str | None) -> bool:
    return (value or "").strip().lower() in _MODES


def _fill(job: Job, attr: str, value: Any) -> bool:
    if value is None or value == "" or not _empty(getattr(job, attr)):
        return False
    setattr(job, attr, value)
    return True


def _advance(run: Run, job: Job, status: str, applied: date | None, rowno: int) -> bool:
    """Move an existing job forward to the sheet's status, stepping through Applied if needed.

    Never backwards or sideways (Skipped and Reopen are the user's own), and never inventing a
    first-response or outcome date: change_status writes today's date there, so those are restored.
    """
    if status not in _ADVANCE or status == job.status:
        return False
    if status not in _FLOW and status not in allowed_next(job):
        return False
    if status in _FLOW and job.status in _FLOW and _FLOW.index(status) <= _FLOW.index(job.status):
        return False
    first_response, outcome = job.first_response_at, job.outcome_at
    on = applied or (utc_date(job.applied_at) if job.applied_at else None)
    moved = False
    try:
        for _ in range(len(_FLOW) + 1):
            if job.status == status:
                break
            options = allowed_next(job)
            if status in options:
                step = status
            else:
                reach = _FLOW.index(status) if status in _FLOW else -1
                step = next((s for s in _FLOW[:reach + 1] if s in options), None)
            if step is None:
                break
            change_status(run.session, job, step, actor="user", at=run.now, on=on,
                          note="Imported from a spreadsheet")
            moved = True
    except TrackingError as e:
        run.flag(rowno, f"Status not changed: {e}")
    if moved:
        job.first_response_at, job.outcome_at = first_response, outcome
    return moved


def _job_core(run: Run, rowno: int, row: list[Any]) -> tuple[str, Job | None]:
    """Create or update the job a row describes; returns the action and the job (None if left out)."""
    applications = run.body.kind == "applications"
    employer, title = run.text(row, "employer"), run.text(row, "title")
    if not employer or not title:
        run.left_out(rowno, "No employer or title.")
        return "left out", None
    requisition = run.text(row, "requisition")
    extras: list[str] = []

    location, mode = split_location_mode(run.text(row, "location"))

    pay_text = run.text(row, "pay")
    pay = parse_pay(pay_text) if pay_text else None
    if pay_text and pay is None:
        extras.append(f"Pay in file: {pay_text}")

    applied = _date_cell(run, row, "applied_date", "Applied date", extras)
    responded = _date_cell(run, row, "first_response_date", "First response date", extras)
    if applications:
        stage = run.text(row, "interview_stage")
        if stage:
            extras.append(f"Interview stage: {stage}")
        for key, label in (("next_followup", "Next follow-up"), ("last_outreach", "Last outreach")):
            text = run.text(row, key)
            if text and parse_date(run.cell(row, key)) is None:
                extras.append(f"{label} in file: {text}")
    status, word = run.resolve_status(row)
    values, kept_extras = _kept_values(run, rowno, row)
    extras += kept_extras
    url = run.text(row, "url") or None
    notes = run.text(row, "notes")

    matches = _find(run.jobs, employer, requisition, title, location or "")
    if len(matches) > 1:
        run.left_out(rowno, "More than one job matches.")
        return "left out", None

    if not matches:
        extra_text = "\n".join(extras)
        job = Job(
            employer=employer, title=title, requisition_id=requisition or None, location=location,
            work_mode=mode, pay_min=pay[0] if pay else None, pay_max=pay[1] if pay else None,
            apply_url=url, notes="\n".join(p for p in (notes, extra_text) if p) or None,
            origin="import", status=status or "New",
            first_seen_at=utc_midnight(applied) if applied else run.now,
            applied_at=utc_midnight(applied) if applied else None,
            first_response_at=utc_midnight(responded) if responded else None,
            flags=[], hard_rules=[])
        if job.status == "Skipped":
            job.skip_reason, job.skip_note = "Other", word or "Imported"
        run.session.add(job)
        run.session.flush()
        log(run.session, entity_type="job", entity_id=job.id, job_id=job.id, action="imported",
            at=run.now, actor="user", to_value=job.status)
        custom_fields.set_values(run.session, job, values, at=run.now)
        run.jobs.append(job)
        run.counts["new"] += 1
        run.last_status = job.status
        return "new", job

    job = matches[0]
    changed = False
    for attr, value in (("requisition_id", requisition or None), ("location", location),
                        ("apply_url", url)):
        changed |= _fill(job, attr, value)
    # A work mode that is not a mode (an earlier import put a place there) is replaced; real ones stay.
    if mode and _empty(job.work_mode) or (job.work_mode and not _is_mode(job.work_mode)):
        if job.work_mode != mode:
            job.work_mode = mode
            changed = True
    if pay and _empty(job.pay_min) and _empty(job.pay_max):
        job.pay_min, job.pay_max = pay
        changed = True
    if applied is not None and job.applied_at is None:
        job.applied_at = utc_midnight(applied)
        changed = True
    if responded is not None and job.first_response_at is None:
        job.first_response_at = utc_midnight(responded)
        changed = True
    new_notes = _append_once(job.notes, notes) if applications else (job.notes or notes)
    for line in extras:
        new_notes = _append_once(new_notes, line)
    if (new_notes or None) != job.notes:
        job.notes = new_notes or None
        changed = True
    if status and status != job.status and job.status != "Skipped":
        changed |= _advance(run, job, status, applied, rowno)
    have = custom_fields.values_for(run.session, [job.id]).get(job.id, {})
    missing = {k: v for k, v in values.items() if k not in have}
    if missing:
        custom_fields.set_values(run.session, job, missing, at=run.now)
        changed = True
    run.last_status = job.status
    if changed:
        run.session.add(job)
        run.session.flush()
        run.counts["updated"] += 1
        return "updated", job
    run.counts["unchanged"] += 1
    return "unchanged", job


def _jobs_row(run: Run, rowno: int, row: list[Any]) -> str:
    return _job_core(run, rowno, row)[0]


def _applications_row(run: Run, rowno: int, row: list[Any]) -> str:
    action, job = _job_core(run, rowno, row)
    if job is None:
        return action
    if action == "new":
        run.flag(rowno, "New from this sheet.")
    changed = False
    due = parse_date(run.cell(row, "next_followup"))
    if due is not None:
        seen = run.session.exec(select(FollowUp).where(
            FollowUp.job_id == job.id, FollowUp.due_date == due)).first()  # any status: it is already there
        if seen is None:
            followup_rules.create_followup(run.session, type="Other", due=due, at=run.now, job_id=job.id,
                                           note=IMPORTED_FOLLOWUP)
            changed = True
    outreach = parse_date(run.cell(row, "last_outreach"))
    if outreach is not None:
        when = utc_midnight(outreach)
        seen = run.session.exec(select(ActivityLog).where(
            ActivityLog.job_id == job.id, ActivityLog.action == "note", ActivityLog.note == "Outreach",
            ActivityLog.at == when)).first()
        if seen is None:
            log(run.session, entity_type="job", entity_id=job.id, job_id=job.id, action="note",
                at=when, actor="user", note="Outreach")
            changed = True
    name = run.text(row, "contact")
    if name and not any((c.name or "").casefold() == name.casefold() for c in run.session.exec(
            select(Contact).where(Contact.job_id == job.id))):
        contact = Contact(job_id=job.id, name=name, employer=job.employer)
        run.session.add(contact)
        run.session.flush()
        log(run.session, entity_type="contact", entity_id=contact.id, job_id=job.id,
            action="contact_added", at=run.now, actor="user")
        changed = True
    if changed and action == "unchanged":
        run.counts["unchanged"] -= 1
        run.counts["updated"] += 1
        return "updated"
    return action


def _contact_status(text: str) -> str | None:
    low = text.lower()
    for word, status in (("replied", "Replied"), ("contacted", "Contacted")):
        if re.search(rf"\b{word}\b", low):
            return status
    return None


def _same_employer(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return True  # a blank employer does not tell the two apart
    return normalize_employer(a) == normalize_employer(b)


def _contacts_row(run: Run, rowno: int, row: list[Any]) -> str:
    name = run.text(row, "name")
    if not name:
        run.left_out(rowno, "No name.")
        return "left out"
    employer = run.text(row, "employer") or None
    role = run.text(row, "related_role")
    job = None
    if role:
        found = _find(run.jobs, employer, "", role, "") if employer else []
        if len(found) == 1:
            job = found[0]
        else:
            run.flag(rowno, f'No single job matches "{role}".')

    lines = []
    status_text = run.text(row, "status_text")
    if status_text:
        lines.append(f"Status: {status_text}")
    outreach_text = run.text(row, "outreach_date")
    if outreach_text:
        day = parse_date(run.cell(row, "outreach_date"))
        lines.append(f"Outreach: {day.isoformat()}" if day else f"Outreach in file: {outreach_text}")
    source = run.text(row, "source")
    if source:
        lines.append(f"Source: {source}")
    note = run.text(row, "notes")
    status = _contact_status(status_text) if status_text else None

    contact = next((c for c in run.session.exec(select(Contact))
                    if _words(c.name or "") == _words(name) and _same_employer(c.employer, employer)), None)
    created = contact is None
    changed = False
    if created:
        contact = Contact(name=name, employer=employer, job_id=job.id if job else None, status=status,
                          notes="\n".join(p for p in (note, *lines) if p) or None)
        run.session.add(contact)
        run.session.flush()
        log(run.session, entity_type="contact", entity_id=contact.id, job_id=contact.job_id,
            action="contact_added", at=run.now, actor="user")
    else:
        before = (contact.job_id, contact.status, contact.employer, contact.notes)
        if contact.job_id is None and job is not None:
            contact.job_id = job.id
        if contact.status is None and status:
            contact.status = status
        if not contact.employer and employer:
            contact.employer = employer
        notes = contact.notes
        for line in (note, *lines):
            notes = _append_once(notes, line)
        contact.notes = notes or None
        if before != (contact.job_id, contact.status, contact.employer, contact.notes):
            run.session.add(contact)
            run.session.flush()
            changed = True
    action = run.text(row, "next_action")
    if action:
        seen = run.session.exec(select(FollowUp).where(
            FollowUp.contact_id == contact.id, FollowUp.note == action)).first()
        if seen is None:
            followup_rules.create_followup(run.session, type="Other", due=local_date(run.now), at=run.now,
                                           contact_id=contact.id, job_id=contact.job_id, note=action)
            changed = True
    run.last_status = contact.status or ""
    if created:
        run.counts["new"] += 1
        return "new"
    run.counts["updated" if changed else "unchanged"] += 1
    return "updated" if changed else "unchanged"


_HANDLERS: dict[str, Callable[[Run, int, list[Any]], str]] = {
    "jobs": _jobs_row, "applications": _applications_row, "contacts": _contacts_row,
}


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def _message(c: Counter, kind: str = "jobs") -> str:
    noun = ("contact", "contacts") if kind == "contacts" else ("job", "jobs")
    return (f"Imported {c['new']} new {_plural(c['new'], *noun)}, updated {c['updated']}, "
            f"{c['unchanged']} already in JobMe, {c['left_out']} left out.")


def run_import(session: Session, sheet: Sheet, body: SheetImportIn, *, now: datetime) -> dict:
    run = Run(session, sheet, body, now)
    handler = _HANDLERS.get(body.kind)
    if handler is None:
        raise ImportFailure("That kind of sheet can't be imported yet.")
    _check_request(run)
    _prepare_fields(run)
    if sheet.left_out:
        run.flag(0, f"{sheet.left_out} {_plural(sheet.left_out, 'row', 'rows')} over the "
                    f"{MAX_ROWS:,}-row limit {_plural(sheet.left_out, 'was', 'were')} left out.")
    for rowno, row in enumerate(sheet.rows, start=1):
        action = handler(run, rowno, row)
        if rowno % BATCH_ROWS == 0 and not body.dry_run:
            session.commit()  # keep each transaction under the database's row limit
        if len(run.sample) < SAMPLE_ROWS and action != "left out":
            run.sample.append({"row": rowno, "employer": run.text(row, "employer"),
                               "title": run.text(row, "title") or run.text(row, "name"), "action": action,
                               "status": run.last_status or ("" if body.kind == "contacts" else "New")})
    words = sorted(run.words.values(), key=lambda w: (-w["count"], w["word"].lower()))
    return {"counts": dict(run.counts), "attention": run.attention, "words": words,
            "sample": run.sample, "message": _message(run.counts, body.kind)}
