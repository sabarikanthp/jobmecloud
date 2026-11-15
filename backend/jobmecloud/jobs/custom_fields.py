"""Custom job fields: definitions and per-job values.

Every function here mutates, adds and flushes; none commits. The caller commits.
"""

from datetime import date, datetime

from sqlmodel import Session, select

from jobmecloud.db.models import CustomField, CustomValue, Job
from jobmecloud.jobs.tracking import TrackingError, log

FIELD_TYPES = ("text", "number", "date", "choice")
MAX_NAME = 40
NAME_COPY = "Give the field a name of up to 40 characters."
TYPE_COPY = "Choose a type: text, number, date or choice."
CHOICES_COPY = "A choice field needs at least one option."
NUMBER_COPY = "Enter a number."
DATE_COPY = "Enter a date as YYYY-MM-DD."
CHOICE_COPY = "Choose one of the options."
GONE_COPY = "That field no longer exists."


def list_fields(session: Session) -> list[CustomField]:
    return list(session.exec(select(CustomField).order_by(CustomField.position, CustomField.id)))


def _clean_choices(choices: list[str] | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in choices or []:
        item = (raw or "").strip()
        if item and item.casefold() not in seen:
            seen.add(item.casefold())
            out.append(item)
    return out


def _check_name(session: Session, name: str, *, own_id: int | None = None) -> str:
    clean = (name or "").strip()
    if not clean or len(clean) > MAX_NAME:
        raise TrackingError(NAME_COPY)
    for other in session.exec(select(CustomField)):
        if other.id != own_id and other.name.casefold() == clean.casefold():
            raise TrackingError(f"You already have a field called {clean}.")
    return clean


def create_field(session: Session, *, name: str, type: str, choices: list[str] | None = None,
                 at: datetime) -> CustomField:
    if type not in FIELD_TYPES:
        raise TrackingError(TYPE_COPY)
    clean = _check_name(session, name)
    options = _clean_choices(choices) if type == "choice" else []
    if type == "choice" and not options:
        raise TrackingError(CHOICES_COPY)
    last = max((f.position for f in list_fields(session)), default=0)
    field = CustomField(name=clean, type=type, choices=options, position=last + 1)
    session.add(field)
    session.flush()
    return field


def _used(session: Session, field_id: int, value: str | None = None) -> int:
    query = select(CustomValue).where(CustomValue.field_id == field_id)
    if value is not None:
        query = query.where(CustomValue.value == value)
    return len(session.exec(query).all())


def update_field(session: Session, field: CustomField, *, name: str | None = None,
                 choices: list[str] | None = None, position: int | None = None,
                 at: datetime) -> None:
    if name is not None:
        field.name = _check_name(session, name, own_id=field.id)
    if choices is not None and field.type == "choice":
        options = _clean_choices(choices)
        if not options:
            raise TrackingError(CHOICES_COPY)
        for removed in field.choices:
            if removed not in options:
                used = _used(session, field.id, removed)
                if used:
                    raise TrackingError(f"That option is still used by {used} jobs.")
        field.choices = options
    if position is not None:
        field.position = position
    session.add(field)
    session.flush()


def delete_field(session: Session, field: CustomField) -> int:
    values = session.exec(select(CustomValue).where(CustomValue.field_id == field.id)).all()
    for v in values:
        session.delete(v)
    session.flush()  # values first: the foreign key would refuse the field otherwise
    session.delete(field)
    session.flush()
    return len(values)


def normalize_value(field: CustomField, raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    if field.type == "number":
        try:
            number = float(text)
        except ValueError:
            raise TrackingError(NUMBER_COPY) from None
        if number != number or number in (float("inf"), float("-inf")):
            raise TrackingError(NUMBER_COPY)
        return str(int(number)) if number.is_integer() else repr(number)
    if field.type == "date":
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            raise TrackingError(DATE_COPY) from None
    if field.type == "choice":
        for option in field.choices:
            if option.casefold() == text.casefold():
                return option
        raise TrackingError(CHOICE_COPY)
    return text


def set_values(session: Session, job: Job, values: dict[int, str | None], *, at: datetime,
               actor: str = "user") -> None:
    for field_id, raw in values.items():
        field = session.get(CustomField, field_id)
        if field is None:
            raise TrackingError(GONE_COPY)
        new = normalize_value(field, raw)
        row = session.exec(select(CustomValue).where(CustomValue.job_id == job.id,
                                                     CustomValue.field_id == field_id)).first()
        old = row.value if row is not None else None
        if new == old:
            continue
        if new is None:
            session.delete(row)
        elif row is None:
            session.add(CustomValue(job_id=job.id, field_id=field_id, value=new))
        else:
            row.value = new
            session.add(row)
        session.flush()
        log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="field_changed",
            at=at, actor=actor, from_value=old, to_value=new, note=field.name)


def values_for(session: Session, job_ids: list[int]) -> dict[int, dict[int, str]]:
    if not job_ids:
        return {}
    out: dict[int, dict[int, str]] = {}
    for v in session.exec(select(CustomValue).where(CustomValue.job_id.in_(job_ids))):
        out.setdefault(v.job_id, {})[v.field_id] = v.value
    return out
