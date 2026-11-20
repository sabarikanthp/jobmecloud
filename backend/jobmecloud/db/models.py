from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from jobmecloud.db.columns import fk, pk_column


class Job(SQLModel, table=True):
    id: int | None = pk_column()
    employer: str
    title: str
    requisition_id: str | None = None
    location: str | None = None
    work_mode: str | None = None
    pay_min: int | None = None
    pay_max: int | None = None
    pay_verified: bool | None = None
    posted_date: date | None = None
    apply_url: str | None = None
    source: str | None = None
    description: str | None = None
    origin: str  # scout / import / manual
    first_seen_at: datetime
    last_checked_at: datetime | None = None
    liveness: str | None = None  # active / closed / unknown
    match_score: int | None = None
    hard_rules: Any = Field(default_factory=list, sa_column=Column(JSON))
    flags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    reasons: str | None = None
    gaps: str | None = None
    status: str
    skip_reason: str | None = None
    skip_note: str | None = None
    applied_at: datetime | None = None
    first_response_at: datetime | None = None
    outcome_at: datetime | None = None
    docs_folder: str | None = None
    docs_note: str | None = None  # the page note shown on Today
    docs_error: str | None = None  # last Make docs failure, friendly text; cleared on success
    docs_status: str | None = None  # generating / ready / error: set while a docs worker writes the files
    docs_started_at: datetime | None = None  # when the current docs job was handed to a worker
    repost_of_id: int | None = fk("job.id", optional=True)
    notes: str | None = None


class Run(SQLModel, table=True):
    id: int | None = pk_column()
    trigger: str  # schedule / manual
    started_at: datetime
    finished_at: datetime | None = None
    found: int = 0
    new: int = 0
    excluded: int = 0
    matched: int = 0
    prepared: int = 0
    errors: list[Any] = Field(default_factory=list, sa_column=Column(JSON))
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost: float = 0.0
    stage: str | None = None
    lock_owner: str | None = None


class RunLock(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    acquired_at: datetime
    owner: str | None = None
    heartbeat_at: datetime | None = None


class RunJob(SQLModel, table=True):
    id: int | None = pk_column()
    run_id: int = fk("run.id")
    job_id: int = fk("job.id")
    outcome: str  # new / duplicate / excluded / matched / prepared / closed


class Interview(SQLModel, table=True):
    id: int | None = pk_column()
    job_id: int = fk("job.id")
    date: datetime | None = None
    stage: str | None = None
    notes: str | None = None


class Contact(SQLModel, table=True):
    id: int | None = pk_column()
    job_id: int | None = fk("job.id", optional=True)
    employer: str | None = None
    name: str | None = None
    role: str | None = None
    link: str | None = None
    relationship: str | None = None
    status: str | None = None
    notes: str | None = None


class FollowUp(SQLModel, table=True):
    id: int | None = pk_column()
    job_id: int | None = fk("job.id", optional=True)
    contact_id: int | None = fk("contact.id", optional=True)
    type: str = Field(sa_column_kwargs={"nullable": True})
    due_date: date = Field(sa_column_kwargs={"nullable": True})
    status: str = Field(sa_column_kwargs={"nullable": True})
    created_at: datetime = Field(sa_column_kwargs={"nullable": True})
    completed_at: datetime | None = None
    outcome_note: str | None = None
    note: str | None = None


class ActivityLog(SQLModel, table=True):
    id: int | None = pk_column()
    entity_type: str = Field(sa_column_kwargs={"nullable": True})  # job / followup / contact / interview
    entity_id: int = Field(sa_column_kwargs={"nullable": True})
    job_id: int | None = fk("job.id", optional=True)
    action: str = Field(sa_column_kwargs={"nullable": True})
    from_value: str | None = None
    to_value: str | None = None
    at: datetime = Field(sa_column_kwargs={"nullable": True})
    actor: str = Field(sa_column_kwargs={"nullable": True})  # user / system
    note: str | None = None


class WatchlistEmployer(SQLModel, table=True):
    id: int | None = pk_column()
    name: str
    priority: int = 2
    careers_url: str | None = None
    rotation_day: str | None = None  # a Day value: mon..sun
    last_checked_at: datetime | None = None


class CustomField(SQLModel, table=True):
    id: int | None = pk_column()
    name: str
    type: str  # text / number / date / choice
    choices: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    position: int = 0


class CustomValue(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("job_id", "field_id"),)

    id: int | None = pk_column()
    job_id: int = fk("job.id")
    field_id: int = fk("customfield.id")
    value: str


class InboundEmail(SQLModel, table=True):
    """One emailed report that reached the mail bucket, and what became of it. The key makes ingestion idempotent."""

    __table_args__ = (UniqueConstraint("s3_key"),)

    id: int | None = pk_column()
    s3_key: str
    received_at: datetime
    sender: str | None = None
    status: str  # received / processing / started / rejected / skipped / waiting / done / failed
    run_id: int | None = fk("run.id", optional=True)
    note: str | None = None
    claimed_at: datetime | None = None  # when an invocation took it; a stale claim (a crash) can be taken over


class ApiKey(SQLModel, table=True):
    """A key that lets Claude Desktop reach the app. Only a hash of the key is kept."""

    id: int | None = pk_column()
    name: str = Field(sa_column_kwargs={"nullable": True})
    prefix: str = Field(sa_column_kwargs={"nullable": True})
    key_hash: str = Field(sa_column_kwargs={"nullable": True, "unique": True})
    scope: str = Field(sa_column_kwargs={"nullable": True})  # read / readwrite
    created_at: datetime = Field(sa_column_kwargs={"nullable": True})
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    ai_day: date | None = None  # the day ai_count counts, for the daily cap on AI-cost tools
    ai_count: int = Field(default=0, sa_column_kwargs={"nullable": True})
