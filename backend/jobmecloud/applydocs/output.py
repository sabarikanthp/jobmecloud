"""The per-job output folder: naming, archiving the previous files, job.md and notes.md."""

import re
import shutil
from datetime import date, datetime
from pathlib import Path

from jobmecloud.db.models import Job

RESUME_NAMES = ("resume.docx", "resume.pdf", "resume.txt", "resume.md")
COVER_NAME = "cover-letter.docx"
COVER_NAMES = (COVER_NAME, "cover-letter.pdf", "cover-letter.md")
ARCHIVED = (*RESUME_NAMES, *COVER_NAMES, "notes.md")

_ILLEGAL = re.compile(r'[<>:"/\\|?*]')
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_PLACEHOLDER = re.compile(r"\{(date|company|title)\}")


class FileInUseError(Exception):
    def __init__(self, name: str):
        super().__init__(f"Close {name} in Word, then try again.")
        self.name = name


def _clean(value: str) -> str:
    value = _ILLEGAL.sub("", value)
    value = re.sub(r"\s+", " ", value)
    value = _CONTROL.sub("", value).strip()
    return value.replace(" ", "-")[:50]


def job_folder_name(pattern: str, job: Job, today: date) -> str:
    values = {"date": today.isoformat(), "company": _clean(job.employer or ""), "title": _clean(job.title or "")}
    name = _PLACEHOLDER.sub(lambda m: values[m.group(1)], pattern)
    name = _ILLEGAL.sub("", name)
    name = _CONTROL.sub("", re.sub(r"\s+", " ", name)).strip().replace(" ", "-")
    name = name[:120].rstrip(". ")
    if not name:
        return "job"
    if name.split(".")[0].rstrip(" ").upper() in _RESERVED:
        name += "_"
    return name


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return path.resolve() != root.resolve()


def prepare_folder(applications_dir: Path, name: str, existing: str | None) -> Path:
    if existing:
        folder = Path(existing)
        if folder.is_dir() and _inside(folder, applications_dir):
            return folder
    applications_dir.mkdir(parents=True, exist_ok=True)
    name = _ILLEGAL.sub("", name).strip().rstrip(". ")
    if not name or not _inside(applications_dir / name, applications_dir):
        name = "job"
    folder = applications_dir / name
    n = 2
    while folder.exists():
        folder = applications_dir / f"{name}-{n}"
        n += 1
    folder.mkdir()
    return folder


def archive_previous(folder: Path, now: datetime) -> Path | None:
    files = [folder / n for n in ARCHIVED if (folder / n).is_file()]
    if not files:
        return None
    for f in files:
        try:
            with open(f, "ab"):
                pass
        except PermissionError:
            raise FileInUseError(f.name) from None
    stamp = now.astimezone().strftime("%Y-%m-%d_%H%M%S")
    dest = folder / "previous" / stamp
    n = 2
    while dest.exists():
        dest = folder / "previous" / f"{stamp}-{n}"
        n += 1
    dest.mkdir(parents=True)
    for f in files:
        shutil.move(str(f), str(dest / f.name))
    return dest


def _pay(job: Job) -> str:
    if job.pay_min and job.pay_max:
        return f"${job.pay_min:,} to ${job.pay_max:,}"
    if job.pay_min or job.pay_max:
        return f"${(job.pay_min or job.pay_max):,}"
    return "Not listed"


def write_job_md(folder: Path, job: Job) -> None:
    text = (
        f"# {job.title}\n\n"
        f"- Employer: {job.employer}\n"
        f"- Location: {job.location or 'Not listed'}\n"
        f"- Pay: {_pay(job)}\n"
        f"- Apply: {job.apply_url or 'No link'}\n\n"
        f"## Description\n\n{job.description or 'No description saved.'}\n"
    )
    (folder / "job.md").write_text(text, encoding="utf-8")


def write_notes_md(folder: Path, job: Job, *, changes: list[str], check_notes: list[str], page_note: str,
                   resume_name: str, as_is: bool) -> None:
    score = "Not scored" if job.match_score is None else str(job.match_score)
    lines = [f"# Notes: {job.title} at {job.employer}", "", "## Match", "", f"- Score: {score}",
             f"- Reasons: {job.reasons or 'None'}"]
    lines.append(f"- Flags: {', '.join(job.flags) if job.flags else 'None'}")
    lines += ["", "## Resume", "", f"- Resume: {resume_name}"]
    if as_is:
        lines.append("- Used as-is, no changes.")
    else:
        lines += [f"- {c}" for c in changes] or ["- No changes listed."]
    lines += ["", "## Checks", ""]
    lines += [f"- {c}" for c in check_notes] or ["None"]
    lines += ["", "## Page count", "", page_note, "", "## Gaps to prepare for", "", job.gaps or "None", ""]
    (folder / "notes.md").write_text("\n".join(lines), encoding="utf-8")


# Words that end a company name without being the name ("Initech Health" is "Initech" on a file).
_COMPANY_TAIL = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "plc", "lp", "group", "holdings",
                 "health", "healthcare", "financial", "international", "technologies", "technology"}
_TITLE_WORDS = 4


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"[^A-Za-z0-9]+", text or "") if w]


def _camel(words: list[str]) -> str:
    return "".join(w if w[0].isupper() else w[0].upper() + w[1:] for w in words)


def document_filename(person: str, employer: str, title: str, kind: str, suffix: str) -> str:
    """The name a downloaded resume or cover letter is saved under, e.g. Jordan_Example_Initech_LeadDirector.docx."""
    company_words = _words(employer)
    while len(company_words) > 1 and company_words[-1].lower() in _COMPANY_TAIL:
        company_words.pop()
    parts = [*_words(person)]
    if company_words:
        parts.append(_camel(company_words))
    title_words = _words(title)[:_TITLE_WORDS]
    if title_words:
        parts.append(_camel(title_words))
    if not parts:
        return ("Cover_Letter" if kind == "cover_letter" else "Resume") + suffix
    if kind == "cover_letter":
        parts.append("Cover")
    return "_".join(parts)[:80].rstrip("_") + suffix
