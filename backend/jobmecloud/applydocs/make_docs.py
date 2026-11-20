"""Make the documents for one job, or use a resume as-is.

make_docs runs every step that can fail (the AI steps, the code check, rendering and
page fitting) before it touches the job folder, so a failure leaves the files there
untouched. Only then does it archive the previous files and write the new ones.
"""

import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session

from jobmecloud.applydocs.check import code_check
from jobmecloud.applydocs.content import Draft, original_content
from jobmecloud.applydocs.links import contact_index, feedback_links, new_links
from jobmecloud.applydocs.output import (
    COVER_NAME,
    COVER_NAMES,
    archive_previous,
    job_folder_name,
    prepare_folder,
    write_job_md,
    write_notes_md,
)
from jobmecloud.applydocs.pages import PageCounter, fit_pages, original_page_count
from jobmecloud.applydocs.render import (
    render_cover_letter,
    render_plain_cover_letter,
    render_plain_resume,
    render_resume,
)
from jobmecloud.applydocs.tailor import draft_documents, revise, self_check
from jobmecloud.config.profile import MasterResume, SearchProfile, UserProfile, load_resume, load_search, load_user
from jobmecloud.config.settings import Settings, load_settings
from jobmecloud.db.models import Job
from jobmecloud.jobs.tracking import change_status, log
from jobmecloud.llm.pricing import CostTracker
from jobmecloud.llm.types import Provider
from jobmecloud.resumes.context import pick_resume, ready_cards
from jobmecloud.resumes.mapping import ResumeMapping, keys_match
from jobmecloud.resumes.store import (
    ResumeEntry,
    default_entry,
    file_path,
    get_entry,
    load_mapping,
    load_reading,
)

NO_RESUME_COPY = "Add your resume in Settings > Your resume to get documents."
PLAIN_LAYOUT_NOTE = "Your default resume isn't a Word file, so JobMe used a plain layout."
NO_MAPPING_NOTE = (
    "JobMe couldn't map the parts of your resume, so it used a plain layout. "
    "Check the mapping in Settings > Your resume."
)
STALE_MAPPING_COPY = (
    "The resume file no longer matches its mapping. Check the mapping again in Settings > Your resume."
)
MISSING_FILE_COPY = "That resume's file is missing. Add it again in Settings > Your resume."
NO_SUCH_RESUME_COPY = "That resume is no longer in your library. Pick another one."
STAGE_WRITING = "Writing documents ({i} of {n})"


class DocsSetupError(Exception):
    """Documents can't be made until the user fixes their setup; the message is user copy."""


@dataclass
class DocsResult:
    folder: Path
    note: str


@dataclass
class _Inputs:
    job: Job
    entry: ResumeEntry
    resume: MasterResume
    template: bytes | None  # the default .docx, when it has a mapping
    mapping: ResumeMapping | None
    profile: SearchProfile
    user: UserProfile
    settings: Settings
    headline: str = ""  # the first paragraph mapped as headline, "" when there is none


@dataclass
class _Rendered:
    resume: bytes
    letter: bytes
    note: str


# ---------------------------------------------------------------- entry points


def make_docs(
    data_dir: Path,
    engine: Engine,
    job_id: int,
    *,
    provider: Provider,
    model: str,
    costs: CostTracker,
    counter: PageCounter,
    now: datetime,
    feedback: str | None = None,
    resume_id: str | None = None,
) -> DocsResult:
    today = now.astimezone().date()
    resume_id, chosen = _choose_resume(data_dir, engine, job_id, provider, model, costs, resume_id)
    inputs = _load_inputs(data_dir, engine, job_id, resume_id)
    draft, problems = _draft(provider, model, inputs, costs, feedback)
    draft, check_notes = code_check(draft, inputs.resume, inputs.profile, inputs.headline)
    links = _links_to_add(inputs, feedback)
    rendered = _render(inputs, draft, counter, today, links)
    rendered.note = _say_what_happened(rendered.note, links, draft.not_applied, chosen, draft.impact)

    folder, _ = _open_folder(data_dir, inputs.settings, inputs.job, today, now)
    (folder / "resume.docx").write_bytes(rendered.resume)
    (folder / COVER_NAME).write_bytes(rendered.letter)
    write_job_md(folder, inputs.job)
    write_notes_md(folder, inputs.job, changes=[*([f"What changed and why it is stronger: {draft.impact}"] if draft.impact.strip() else []), *([chosen] if chosen else []), *draft.changes, *[f"Not applied: {n}" for n in draft.not_applied], *problems], check_notes=check_notes,
                   page_note=rendered.note, resume_name=inputs.entry.name, as_is=False)
    _mark_done(engine, job_id, folder, rendered.note, now)
    return DocsResult(folder, rendered.note)


def use_as_is(data_dir: Path, engine: Engine, job_id: int, resume_id: str, now: datetime) -> DocsResult:
    entry = get_entry(data_dir, resume_id)
    source = file_path(data_dir, entry)
    if not source.is_file():
        raise DocsSetupError(MISSING_FILE_COPY)  # checked before archiving, so nothing moves
    job = _load_job(engine, job_id)
    today = now.astimezone().date()

    folder, archived = _open_folder(data_dir, load_settings(data_dir), job, today, now)
    for cover in COVER_NAMES:
        if archived is not None and (archived / cover).is_file():
            shutil.copy2(archived / cover, folder / cover)  # the cover letter stays in use
    shutil.copyfile(source, folder / f"resume{Path(entry.filename).suffix}")
    write_job_md(folder, job)
    write_notes_md(folder, job, changes=[], check_notes=[], page_note="", resume_name=entry.name, as_is=True)

    note = f"Using {entry.name} as-is"
    _mark_done(engine, job_id, folder, note, now, action="docs_as_is", log_note=entry.name)
    return DocsResult(folder, note)


# ---------------------------------------------------------------- 1. inputs


def _load_job(engine: Engine, job_id: int) -> Job:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise KeyError(f"No job with id {job_id}")
        return job


def _load_inputs(data_dir: Path, engine: Engine, job_id: int, resume_id: str | None = None) -> _Inputs:
    """The job, and the resume to start from: the one asked for, else the default."""
    job = _load_job(engine, job_id)
    if resume_id:
        try:
            entry = get_entry(data_dir, resume_id)
            resume = load_reading(data_dir, resume_id)
        except (KeyError, OSError):
            raise DocsSetupError(NO_SUCH_RESUME_COPY) from None
    else:
        entry = default_entry(data_dir)
        resume = load_resume(data_dir)
    if entry is None or resume is None:
        raise DocsSetupError(NO_RESUME_COPY)
    template, mapping = None, None
    if entry.kind == "docx":
        mapping = load_mapping(data_dir, entry.id)
        if mapping is not None and not mapping.mapped():
            mapping = None  # every paragraph is Keep: nothing to tailor in the file, so a plain layout
        if mapping is not None:
            # Bullet labels name jobs by position: never render with labels made for other jobs.
            if mapping.stale or not keys_match(mapping, resume):
                raise DocsSetupError(STALE_MAPPING_COPY)
            source = file_path(data_dir, entry)
            if not source.is_file():
                raise DocsSetupError(MISSING_FILE_COPY)
            template = source.read_bytes()
    headline = next((p.text.strip() for p in mapping.paragraphs if p.label == "headline"), "") if mapping else ""
    return _Inputs(job=job, entry=entry, resume=resume, template=template, mapping=mapping,
                   profile=load_search(data_dir), user=load_user(data_dir), settings=load_settings(data_dir),
                   headline=headline)


# ---------------------------------------------------------------- 2. AI steps


def _draft(provider: Provider, model: str, inputs: _Inputs, costs: CostTracker,
           feedback: str | None) -> tuple[Draft, list[str]]:
    """Draft, self-check, and revise once if the check found problems; return the problems too."""
    common = dict(job=inputs.job, profile=inputs.profile, resume=inputs.resume, user=inputs.user,
                  tone=inputs.settings.cover_letter_tone, costs=costs, headline=inputs.headline)
    draft = draft_documents(provider, model, feedback=feedback, **common)
    problems = self_check(provider, model, draft=draft, resume=inputs.resume, profile=inputs.profile, costs=costs,
                         headline=inputs.headline)
    if problems:
        draft = revise(provider, model, draft=draft, problems=problems, feedback=feedback, **common)
    return draft, problems


# ---------------------------------------------------------------- 3. render


def _render(inputs: _Inputs, draft: Draft, counter: PageCounter, today: date, links: list[str]) -> _Rendered:
    original = original_content(inputs.resume, inputs.headline)
    if inputs.template is None or inputs.mapping is None:
        user = inputs.user.model_copy(update={"links": [*inputs.user.links, *new_links(" ".join(inputs.user.links), links)]})
        fit = fit_pages(lambda c: render_plain_resume(inputs.resume, c, user),
                        draft.content, original, None, counter)
        letter = render_plain_cover_letter(draft.letter, user, today)
        layout = NO_MAPPING_NOTE if inputs.entry.kind == "docx" else PLAIN_LAYOUT_NOTE
        return _Rendered(fit.docx, letter, f"{layout} {fit.note}")

    template, mapping = inputs.template, inputs.mapping
    try:
        fit = fit_pages(lambda c: render_resume(template, mapping, c, links),
                        draft.content, original, original_page_count(template), counter)
        letter = render_cover_letter(template, mapping, draft.letter, inputs.user, today, links)
    except ValueError as e:
        raise DocsSetupError(STALE_MAPPING_COPY) from e
    return _Rendered(fit.docx, letter, fit.note)


AUTO = "auto"


def _choose_resume(data_dir: Path, engine: Engine, job_id: int, provider: Provider, model: str, costs: CostTracker,
                   resume_id: str | None) -> tuple[str | None, str | None]:
    """The resume to start from. A named resume is used as is. With none named, or "auto", the resume whose profile
    is closest to the job is picked when profiles exist, and otherwise the default is used."""
    if resume_id and resume_id != AUTO:
        return resume_id, None
    cards = ready_cards(data_dir)
    if len(cards) < 2:
        return None, None
    entry = default_entry(data_dir)
    try:
        pick = pick_resume(provider, model, _load_job(engine, job_id), cards, entry.id if entry else None, costs)
    except Exception:  # choosing is a convenience: if it fails the default is used
        return None, None
    if pick is None:
        return None, None
    name = next((e.name for e, _ in cards if e.id == pick.resume_id), pick.resume_id)
    return pick.resume_id, f"Started from {name} (best match: {pick.reason.rstrip('.')})."


def _links_to_add(inputs: _Inputs, feedback: str | None) -> list[str]:
    """The links the user typed that belong on the contact line and are not there yet."""
    links = feedback_links(feedback)
    if not links:
        return []
    if inputs.template is None or inputs.mapping is None:
        return links  # a plain layout builds its own contact line, so every link can go in
    paragraphs = [(p.text, p.label) for p in inputs.mapping.paragraphs]
    at = contact_index(paragraphs)
    return [] if at is None else new_links(paragraphs[at][0], links)


def _say_what_happened(note: str, links: list[str], not_applied: list[str], chosen: str | None = None,
                       impact: str = "") -> str:
    parts = [impact.strip(), note]
    if chosen:
        parts.append(chosen)
    if links:
        parts.append(f"Added to your contact line: {', '.join(links)}.")
    if not_applied:
        parts.append("Couldn't apply: " + "; ".join(n.rstrip(".") for n in not_applied) + ".")
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------- 4. folder and job


def _open_folder(data_dir: Path, settings: Settings, job: Job, today: date,
                 now: datetime) -> tuple[Path, Path | None]:
    """The job's folder and where its previous files went (FileInUseError moves nothing)."""
    folder = prepare_folder(settings.applications_path(data_dir),
                            job_folder_name(settings.folder_pattern, job, today), job.docs_folder)
    return folder, archive_previous(folder, now)


def _mark_done(engine: Engine, job_id: int, folder: Path, note: str, now: datetime,
               action: str | None = None, log_note: str | None = None) -> None:
    with Session(engine) as session:
        job = session.get(Job, job_id)
        first = job.docs_folder is None
        job.docs_folder = str(folder)
        job.docs_note = note
        job.docs_error = None
        session.add(job)
        change_status(session, job, "Ready", actor="system", at=now)  # a no-op unless the job is New
        log(session, entity_type="job", entity_id=job.id, job_id=job.id,
            action=action or ("docs_ready" if first else "docs_regenerated"), at=now, actor="system",
            note=log_note if action else note)
        session.commit()
