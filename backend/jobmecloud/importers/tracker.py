import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import PurePath
from typing import Any

import openpyxl

from jobmecloud.db.models import Job
from jobmecloud.importers.text import ImportFileError
from jobmecloud.jobs.status import STATUSES

TRACKER_FIELDS = (
    "employer", "title", "requisition_id", "location",
    "status", "applied_date", "url", "notes",
)
MAX_ROWS = 5000
TYPE_COPY = "JobMe can read .xlsx and .csv files."
UNREADABLE_COPY = "JobMe couldn't read that spreadsheet. Is it a valid .xlsx or .csv file?"

_KEYWORDS = {
    "employer": ("company", "employer", "organization"),
    "title": ("title", "role", "position"),
    "requisition_id": ("req", "requisition", "job id"),
    "location": ("location", "city"),
    "status": ("status",),
    "applied_date": ("applied", "date"),
    "url": ("url", "link"),
    "notes": ("notes", "comment"),
}
_SYNONYMS = {
    "interview": "Interviewing", "phone screen": "Interviewing",
    "screening": "Interviewing", "declined": "Rejected",
    "not selected": "Rejected", "withdrew": "Withdrawn",
    "not applying": "Skipped", "pass": "Skipped", "expired": "Closed",
}
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y")


@dataclass
class Sheet:
    name: str
    columns: list[str]
    rows: list[list[Any]]
    left_out: int = 0


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def _build_sheet(name: str, raw_rows: list[list[Any]]) -> Sheet:
    header_at = next(
        (i for i, r in enumerate(raw_rows) if sum(not _blank(c) for c in r) >= 2), None
    )
    if header_at is None:
        return Sheet(name, [], [])
    columns = ["" if c is None else str(c).strip() for c in raw_rows[header_at]]
    rows = [list(r) for r in raw_rows[header_at + 1:] if any(not _blank(c) for c in r)]
    return Sheet(name, columns, rows[:MAX_ROWS], left_out=max(0, len(rows) - MAX_ROWS))


def _read_xlsx(data: bytes) -> list[Sheet]:
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise ImportFileError(UNREADABLE_COPY) from exc
    try:
        return [
            _build_sheet(ws.title, [list(r) for r in ws.iter_rows(values_only=True)])
            for ws in wb.worksheets
        ]
    except Exception as exc:
        raise ImportFileError(UNREADABLE_COPY) from exc
    finally:
        wb.close()


def _read_csv(name: str, data: bytes) -> list[Sheet]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    try:
        raw = [list(r) for r in csv.reader(io.StringIO(text))]
    except csv.Error as exc:
        raise ImportFileError(UNREADABLE_COPY) from exc
    return [_build_sheet(name, raw)]


def read_tracker(filename: str, data: bytes) -> list[Sheet]:
    path = PurePath(filename)
    ext = path.suffix.lower()
    if ext == ".xlsx":
        return _read_xlsx(data)
    if ext == ".csv":
        return _read_csv(path.stem, data)
    raise ImportFileError(TYPE_COPY)


def suggest_mapping(columns: list[str]) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {}
    used: set[int] = set()
    for field in TRACKER_FIELDS:
        mapping[field] = None
        for i, col in enumerate(columns):
            low = col.lower()
            if i not in used and any(k in low for k in _KEYWORDS[field]):
                mapping[field] = col
                used.add(i)
                break
    return mapping


def map_status(raw: str | None) -> str:
    low = (raw or "").strip().lower()
    for s in STATUSES:
        if s.lower() == low:
            return s
    return _SYNONYMS.get(low, "New")


def parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time() else value.isoformat(" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def rows_to_jobs(
    sheet: Sheet, mapping: dict[str, str | None], now: datetime
) -> tuple[list[Job], int]:
    index = {}
    for field, col in mapping.items():
        if col is not None and col in sheet.columns:
            index[field] = sheet.columns.index(col)

    def get(row: list[Any], field: str) -> Any:
        i = index.get(field)
        return row[i] if i is not None and i < len(row) else None

    jobs: list[Job] = []
    skipped = 0
    for row in sheet.rows:
        employer = cell_text(get(row, "employer"))
        title = cell_text(get(row, "title"))
        if not employer or not title:
            skipped += 1
            continue
        notes = cell_text(get(row, "notes"))
        raw_date = get(row, "applied_date")
        applied = parse_date(raw_date)
        if applied is None and not _blank(raw_date):
            extra = f"Applied date in file: {cell_text(raw_date)}"
            notes = f"{notes}\n{extra}" if notes else extra
        applied_at = datetime.combine(applied, time()) if applied else None
        status = map_status(cell_text(get(row, "status")))
        job = Job(
            employer=employer,
            title=title,
            requisition_id=cell_text(get(row, "requisition_id")) or None,
            location=cell_text(get(row, "location")) or None,
            apply_url=cell_text(get(row, "url")) or None,
            notes=notes or None,
            origin="import",
            first_seen_at=applied_at or now,
            applied_at=applied_at,
            status=status,
        )
        if status == "Skipped":
            job.skip_reason = "Other"
            job.skip_note = "Imported"
        jobs.append(job)
    return jobs, skipped
