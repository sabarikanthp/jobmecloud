"""Pure helpers for the spreadsheet Import: field lists, guessing, and parsing.

Nothing here touches the database or the file system.
"""

import re
from dataclasses import dataclass

from jobmecloud.importers.tracker import _SYNONYMS, parse_date
from jobmecloud.jobs.status import STATUSES


@dataclass(frozen=True)
class FieldDef:
    key: str
    label: str
    help: str
    required: bool = False


KIND_FIELDS: dict[str, tuple[FieldDef, ...]] = {
    "jobs": (
        FieldDef("employer", "Employer", "The company.", True),
        FieldDef("title", "Title", "The job title.", True),
        FieldDef("requisition", "Requisition", "The job's requisition or posting ID."),
        FieldDef("location", "Location / work mode",
                 "Where the job is. A word like Remote, Hybrid or On-site in the same column becomes the work mode."),
        FieldDef("pay", "Pay", "Posted pay, such as $150,000 - $180,000."),
        FieldDef("status", "Status", "Where the job stands. You can match each word in the next step."),
        FieldDef("applied_date", "Applied date", "The day you applied."),
        FieldDef("first_response_date", "First response date", "The day you first heard back."),
        FieldDef("url", "Link", "The link to the posting."),
        FieldDef("notes", "Notes", "Anything you want to keep with the job."),
    ),
    "applications": (
        FieldDef("employer", "Employer", "The company.", True),
        FieldDef("title", "Title", "The job title.", True),
        FieldDef("requisition", "Requisition", "The job's requisition or posting ID."),
        FieldDef("status", "Status", "Where the application stands."),
        FieldDef("applied_date", "Applied date", "The day you applied."),
        FieldDef("first_response_date", "First response date", "The day you first heard back."),
        FieldDef("contact", "Recruiter or contact", "Added as a contact on the job."),
        FieldDef("last_outreach", "Last outreach", "Added to the job's timeline."),
        FieldDef("next_followup", "Next follow-up", "Becomes an open follow-up."),
        FieldDef("interview_stage", "Interview stage", "Kept in the job's notes."),
        FieldDef("notes", "Notes", "Added to the job's notes."),
    ),
    "contacts": (
        FieldDef("name", "Name", "The contact's name.", True),
        FieldDef("employer", "Employer", "Where they work."),
        FieldDef("related_role", "Related role", "Links the contact to a matching job."),
        FieldDef("outreach_date", "Outreach date", "Kept in the contact's notes."),
        FieldDef("status_text", "Status", "Kept in the contact's notes."),
        FieldDef("next_action", "Next action", "Becomes an open follow-up."),
        FieldDef("source", "Source", "Kept in the contact's notes."),
        FieldDef("notes", "Notes", "Anything you want to keep with the contact."),
    ),
}

_KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "jobs": {
        "employer": ("employer", "company"), "title": ("role", "title", "position"),
        "requisition": ("requisition", "req", "job id", "linkedin id"), "location": ("location",),
        "pay": ("pay", "salary", "compensation"),
        "status": ("application status", "status"),
        "applied_date": ("applied",), "first_response_date": ("response",),
        "url": ("url", "link"), "notes": ("notes", "assessment"),
    },
    "applications": {
        "employer": ("employer", "company"), "title": ("role", "title", "position"),
        "requisition": ("requisition", "req", "job id"), "status": ("current status", "status"),
        "applied_date": ("applied",), "first_response_date": ("response",),
        "contact": ("recruiter", "contact"), "last_outreach": ("outreach",),
        "next_followup": ("follow",), "interview_stage": ("interview",), "notes": ("notes",),
    },
    "contacts": {
        "name": ("contact", "name"), "employer": ("employer", "company", "network"),
        "related_role": ("related role", "role"), "outreach_date": ("outreach date", "outreach"),
        "status_text": ("status",), "next_action": ("next action",), "source": ("source",),
        "notes": ("notes",),
    },
}


def guess_kind(sheet_name: str, columns: list[str]) -> str:
    name = sheet_name.lower()
    if "contact" in name or "referral" in name:
        return "contacts"
    if "follow" in name or "application" in name:
        return "applications"
    low = [c.lower() for c in columns]
    if any("next follow" in c or "last outreach" in c for c in low):
        return "applications"
    has_job = any("role" in c or "title" in c or "position" in c for c in low)
    if any("contact" in c for c in low) and not has_job:
        return "contacts"
    return "jobs"


def suggest_for(kind: str, columns: list[str]) -> dict[str, str | None]:
    keywords = _KEYWORDS[kind]
    mapping: dict[str, str | None] = {f.key: None for f in KIND_FIELDS[kind]}
    used: set[int] = set()
    for exact in (True, False):  # a column named exactly like a keyword wins over a partial match
        for field in KIND_FIELDS[kind]:
            if mapping[field.key] is not None:
                continue
            for i, col in enumerate(columns):
                low = col.strip().lower()
                if i in used:
                    continue
                if any(low == k if exact else k in low for k in keywords[field.key]):
                    mapping[field.key] = col
                    used.add(i)
                    break
    return mapping


_NUMBER = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?")
_HOURLY = re.compile(r"/\s*h(ou)?r|per\s+h(ou)?r|hourly", re.IGNORECASE)


def parse_pay(text: str) -> tuple[int, int] | None:
    raw = (text or "").strip()
    if not raw or _HOURLY.search(raw):
        return None
    found = [(float(m.group(1).replace(",", "")), bool(m.group(2))) for m in _NUMBER.finditer(raw)]
    if not found:
        return None
    values = [n * 1000 if k else n for n, k in found[:2]]
    if len(values) == 2 and found[1][1] and not found[0][1] and found[0][0] < 1000:
        values[0] = found[0][0] * 1000  # "150-180k"
    if any(v < 1000 for v in values):
        return None
    return int(min(values)), int(max(values))


_MODE = re.compile(r"\b(remote|hybrid|on[\s-]?site)\b", re.IGNORECASE)
_MODE_NAMES = {"remote": "Remote", "hybrid": "Hybrid", "onsite": "On-site"}


def split_location_mode(text: str) -> tuple[str | None, str | None]:
    raw = (text or "").strip()
    m = _MODE.search(raw)
    if not m:
        return (raw or None), None
    mode = _MODE_NAMES[re.sub(r"[\s-]", "", m.group(1).lower())]
    rest = (raw[:m.start()] + " " + raw[m.end():]).strip(" \t,/;-()")
    rest = re.sub(r"\s{2,}", " ", rest)
    return (rest or None), mode


def guess_field_type(values: list[str]) -> tuple[str, list[str]]:
    clean = [v.strip() for v in values if v and v.strip()]
    if not clean:
        return "text", []
    if all(parse_date(v) is not None for v in clean):
        return "date", []
    if all(_is_number(v) for v in clean):
        return "number", []
    distinct = sorted(set(clean), key=str.lower)
    if len(distinct) <= 12 and len(clean) > len(distinct) and all(len(v) <= 30 for v in distinct):
        return "choice", distinct
    return "text", []


def _is_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False


_SKIP_START = ("skip recommended", "recommended skip", "deprioritized")


def default_status(word: str) -> str:
    low = (word or "").strip().lower()
    if not low:
        return ""
    for status in STATUSES:
        if status.lower() == low:
            return status
    if low == "pass" or low.startswith(_SKIP_START):
        return "Skipped"
    return _SYNONYMS.get(low, "")
