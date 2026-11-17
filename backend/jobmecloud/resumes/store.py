import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from jobmecloud.config.files import atomic_write_text
from jobmecloud.config.profile import MasterResume, save_resume

if TYPE_CHECKING:
    from jobmecloud.resumes.mapping import ResumeMapping

ResumeKind = Literal["docx", "pdf", "text"]

NOT_FOUND_COPY = "No resume with that id"
REMOVE_DEFAULT_COPY = "Make another resume the default before removing this one."
REMOVE_ONLY_COPY = "This is your only resume. Upload another before removing it."


class ResumeEntry(BaseModel):
    id: str
    name: str
    filename: str
    kind: ResumeKind
    uploaded_at: datetime
    has_mapping: bool = False


class ResumeIndex(BaseModel):
    default_id: str | None = None
    resumes: list[ResumeEntry] = []


def resumes_dir(data_dir: Path) -> Path:
    return data_dir / "profile" / "resumes"


def _index_path(data_dir: Path) -> Path:
    return resumes_dir(data_dir) / "resumes.json"


def _reading_path(data_dir: Path, resume_id: str) -> Path:
    return resumes_dir(data_dir) / f"{resume_id}.json"


def _mapping_path(data_dir: Path, resume_id: str) -> Path:
    return resumes_dir(data_dir) / f"{resume_id}.map.json"


def load_index(data_dir: Path) -> ResumeIndex:
    path = _index_path(data_dir)
    if not path.exists():
        return ResumeIndex()
    return ResumeIndex.model_validate_json(path.read_text(encoding="utf-8"))


def save_index(data_dir: Path, index: ResumeIndex) -> None:
    resumes_dir(data_dir).mkdir(parents=True, exist_ok=True)
    atomic_write_text(_index_path(data_dir), index.model_dump_json(indent=2) + "\n")


def kind_for(filename: str) -> ResumeKind:
    suffix = Path(filename).suffix.lower()
    if suffix == ".docx":
        return "docx"
    if suffix == ".pdf":
        return "pdf"
    return "text"


def _stored_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    return suffix if suffix in (".docx", ".pdf", ".txt", ".md") else ".txt"


def get_entry(data_dir: Path, resume_id: str) -> ResumeEntry:
    for entry in load_index(data_dir).resumes:
        if entry.id == resume_id:
            return entry
    raise KeyError(NOT_FOUND_COPY)


def file_path(data_dir: Path, entry: ResumeEntry) -> Path:
    return resumes_dir(data_dir) / entry.filename


def _write_reading(data_dir: Path, resume_id: str, reading: MasterResume) -> None:
    text = json.dumps(reading.model_dump(mode="json"), indent=2, ensure_ascii=False)
    atomic_write_text(_reading_path(data_dir, resume_id), text + "\n")


def load_reading(data_dir: Path, resume_id: str) -> MasterResume:
    get_entry(data_dir, resume_id)
    return MasterResume.model_validate_json(
        _reading_path(data_dir, resume_id).read_text(encoding="utf-8")
    )


def save_reading(data_dir: Path, resume_id: str, reading: MasterResume) -> None:
    get_entry(data_dir, resume_id)
    _write_reading(data_dir, resume_id, reading)


def add_resume(
    data_dir: Path,
    *,
    name: str,
    filename: str,
    data: bytes,
    reading: MasterResume,
    mapping: "ResumeMapping | None",
    make_default: bool,
    now: datetime,
) -> ResumeEntry:
    folder = resumes_dir(data_dir)
    folder.mkdir(parents=True, exist_ok=True)
    resume_id = uuid.uuid4().hex[:12]
    entry = ResumeEntry(
        id=resume_id,
        name=name,
        filename=f"{resume_id}{_stored_suffix(filename)}",
        kind=kind_for(filename),
        uploaded_at=now,
        has_mapping=mapping is not None,
    )
    (folder / entry.filename).write_bytes(data)
    _write_reading(data_dir, resume_id, reading)
    if mapping is not None:
        atomic_write_text(_mapping_path(data_dir, resume_id), mapping.model_dump_json(indent=2) + "\n")
    index = load_index(data_dir)
    first = not index.resumes
    index.resumes.append(entry)
    save_index(data_dir, index)
    if make_default or first:
        set_default(data_dir, resume_id)
    return entry


def set_default(data_dir: Path, resume_id: str) -> None:
    reading = load_reading(data_dir, resume_id)
    index = load_index(data_dir)
    index.default_id = resume_id
    save_index(data_dir, index)
    save_resume(data_dir, reading)


def default_entry(data_dir: Path) -> ResumeEntry | None:
    index = load_index(data_dir)
    for entry in index.resumes:
        if entry.id == index.default_id:
            return entry
    return None


def remove_resume(data_dir: Path, resume_id: str) -> None:
    entry = get_entry(data_dir, resume_id)
    index = load_index(data_dir)
    if index.default_id == resume_id:
        raise ValueError(REMOVE_ONLY_COPY if len(index.resumes) == 1 else REMOVE_DEFAULT_COPY)
    index.resumes = [r for r in index.resumes if r.id != resume_id]
    save_index(data_dir, index)
    for path in (
        file_path(data_dir, entry),
        _reading_path(data_dir, resume_id),
        _mapping_path(data_dir, resume_id),
    ):
        path.unlink(missing_ok=True)


def load_mapping(data_dir: Path, resume_id: str) -> "ResumeMapping | None":
    get_entry(data_dir, resume_id)
    path = _mapping_path(data_dir, resume_id)
    if not path.exists():
        return None
    from jobmecloud.resumes.mapping import ResumeMapping, realign_mapping

    mapping = ResumeMapping.model_validate_json(path.read_text(encoding="utf-8"))
    try:
        reading = MasterResume.model_validate_json(_reading_path(data_dir, resume_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return mapping
    return realign_mapping(mapping, reading)  # repairs labels the AI drew wrongly, so old saved mappings work too


def save_mapping(data_dir: Path, resume_id: str, mapping: "ResumeMapping") -> None:
    index = load_index(data_dir)
    for entry in index.resumes:
        if entry.id == resume_id:
            entry.has_mapping = True
            break
    else:
        raise KeyError(NOT_FOUND_COPY)
    atomic_write_text(_mapping_path(data_dir, resume_id), mapping.model_dump_json(indent=2) + "\n")
    save_index(data_dir, index)
