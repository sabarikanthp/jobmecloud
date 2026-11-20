"""Attach a resume and/or cover letter that was written elsewhere (in a Claude chat) to a job's documents folder."""

import base64
import binascii
import os
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import Session

from jobmecloud.applydocs.output import (
    ARCHIVED,
    COVER_NAMES,
    RESUME_NAMES,
    FileInUseError,
    archive_previous,
    job_folder_name,
    prepare_folder,
)
from jobmecloud.config.settings import load_settings
from jobmecloud.db.models import Job
from jobmecloud.importers.text import ImportFileError, extract_text
from jobmecloud.jobs.tracking import change_status, log

MAX_BYTES = 3_000_000
KINDS = {"resume": ("resume", ("md", "txt", "docx", "pdf"), RESUME_NAMES),
         "cover_letter": ("cover-letter", ("md", "docx", "pdf"), COVER_NAMES)}
_MAGIC = {"docx": b"PK", "pdf": b"%PDF"}
MAX_READ_CHARS = 60_000


class AttachError(Exception):
    """Something wrong with what was sent, worded for the chat."""


def _decode(label: str, doc: object, kinds: tuple[str, ...]) -> tuple[str, bytes]:
    if not isinstance(doc, dict):
        raise AttachError(f"{label}: give an object with a format and text or base64.")
    fmt = doc.get("format")
    if fmt not in kinds:
        raise AttachError(f"{label}: format must be one of {', '.join(kinds)}.")
    text, encoded = doc.get("text"), doc.get("base64")
    if (text is None) == (encoded is None):
        raise AttachError(f"{label}: give exactly one of text or base64.")
    if fmt in ("md", "txt"):
        if not isinstance(text, str) or not text.strip():
            raise AttachError(f"{label}: a {fmt} document needs non-empty text.")
        data = text.encode("utf-8")
    else:
        if not isinstance(encoded, str) or not encoded:
            raise AttachError(f"{label}: a {fmt} document needs base64 content.")
        if len(encoded) > MAX_BYTES * 4 // 3 + 8:
            raise AttachError(f"{label}: that file is too big (limit about 3 MB).")
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise AttachError(f"{label}: the base64 content is not valid.") from None
        if not data.startswith(_MAGIC[fmt]):
            raise AttachError(f"{label}: the content is not a real {fmt} file.")
    if len(data) > MAX_BYTES:
        raise AttachError(f"{label}: that document is too big (limit about 3 MB).")
    return fmt, data


def _write(path: Path, data: bytes) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def attach_documents(engine: Engine, data_dir: Path, job_id: int, *, resume: object | None, cover_letter: object | None,
                     source: str, now: datetime, today) -> dict:
    """Save the documents into the job's folder (previous files archived first) and mark the job's documents ready.

    Returns the file names written: {"resume": name or None, "cover_letter": name or None}."""
    given = {"resume": resume, "cover_letter": cover_letter}
    if resume is None and cover_letter is None:
        raise AttachError("Give a resume, a cover letter, or both.")
    decoded = {kind: _decode(kind.replace("_", " "), doc, KINDS[kind][1]) for kind, doc in given.items() if doc is not None}
    settings = load_settings(data_dir)
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise AttachError("No job with that id")
        folder = prepare_folder(settings.applications_path(data_dir),
                                job_folder_name(settings.folder_pattern, job, today), job.docs_folder)
        try:
            archived = archive_previous(folder, now)
        except FileInUseError as e:
            raise AttachError(str(e)) from None
        replaced = {n for kind in decoded for n in KINDS[kind][2]}
        if archived is not None:  # what this call does not replace stays where it was
            for name in ARCHIVED:
                if name not in replaced and (archived / name).is_file():
                    shutil.copy2(archived / name, folder / name)
        written: dict[str, str | None] = {"resume": None, "cover_letter": None}
        for kind, (fmt, data) in decoded.items():
            name = f"{KINDS[kind][0]}.{fmt}"
            _write(folder / name, data)
            written[kind] = name
        job.docs_folder = str(folder)
        job.docs_status = "ready"
        job.docs_note = f"Attached from Claude ({source})"
        job.docs_error = None
        session.add(job)
        change_status(session, job, "Ready", actor="system", at=now)  # a no-op unless the job is New
        log(session, entity_type="job", entity_id=job.id, job_id=job.id, action="docs_attached", at=now,
            note=", ".join(n for n in written.values() if n))
        session.commit()
    return written


def read_documents(engine: Engine, data_dir: Path, job_id: int) -> dict[str, tuple[str, str]]:
    """The job's resume and cover letter as text: {"resume": (file name, text), ...}; only those that exist."""
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise AttachError("No job with that id")
        docs_folder = job.docs_folder
    apps = load_settings(data_dir).applications_path(data_dir).resolve()
    folder = Path(docs_folder).resolve() if docs_folder else None
    if folder is None or not folder.is_relative_to(apps) or not folder.is_dir():
        return {}
    found: dict[str, tuple[str, str]] = {}
    for kind, (_, _, names) in KINDS.items():
        for name in names:
            path = folder / name
            if path.is_file():
                try:
                    found[kind] = (name, extract_text(name, path.read_bytes())[:MAX_READ_CHARS])
                except ImportFileError as e:
                    found[kind] = (name, f"(could not read this file: {e})")
                break
    return found
