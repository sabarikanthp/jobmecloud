import json
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError

from jobmecloud.config.files import atomic_write_text
from jobmecloud.config.settings import Day, SettingsError, format_validation_error


def _clean(items: list[str]) -> list[str]:
    return [s.strip() for s in items if s.strip()]


CleanList = Annotated[list[str], AfterValidator(_clean)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class UserProfile(_Model):
    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin_url: str = ""
    links: CleanList = []


class SearchProfile(_Model):
    target_roles: CleanList = []
    positioning: str = ""
    locations: CleanList = []
    radius_miles: int | None = Field(default=None, ge=0)
    work_modes: list[Literal["remote", "hybrid", "onsite"]] = ["remote", "hybrid", "onsite"]
    min_base_pay: int | None = Field(default=None, ge=0)
    excluded_employers: CleanList = []
    deal_breakers: CleanList = []
    warnings: CleanList = []
    max_commute_miles: int | None = Field(default=None, ge=0)
    max_posted_days: int | None = Field(default=None, ge=0)
    do_not_claim: CleanList = []
    rotation: dict[Day, str] = {}


class ResumeRole(_Model):
    employer: str
    title: str
    start: str = ""
    end: str = ""
    location: str = ""
    bullets: CleanList = []


class Education(_Model):
    school: str
    degree: str = ""
    field: str = ""
    year: str = ""


class Certification(_Model):
    name: str
    issuer: str = ""
    year: str = ""


class MasterResume(_Model):
    summary: str = ""
    roles: list[ResumeRole] = []
    skills: CleanList = []
    education: list[Education] = []
    certifications: list[Certification] = []


def _profile_file(data_dir: Path, name: str) -> Path:
    return data_dir / "profile" / name


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)


def _dump_yaml(model: BaseModel) -> str:
    return yaml.safe_dump(model.model_dump(mode="json"), sort_keys=False, allow_unicode=True)


def _load_yaml[M: BaseModel](path: Path, cls: type[M]) -> M:
    if not path.exists():
        return cls()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
        raise SettingsError(f"{path.name} could not be read: {e}") from e
    try:
        return cls.model_validate(raw)
    except ValidationError as e:
        raise SettingsError(format_validation_error(path, e)) from e


def load_user(data_dir: Path) -> UserProfile:
    return _load_yaml(_profile_file(data_dir, "user.yaml"), UserProfile)


def save_user(data_dir: Path, u: UserProfile) -> None:
    _write(_profile_file(data_dir, "user.yaml"), _dump_yaml(u))


def load_search(data_dir: Path) -> SearchProfile:
    return _load_yaml(_profile_file(data_dir, "search.yaml"), SearchProfile)


def save_search(data_dir: Path, s: SearchProfile) -> None:
    _write(_profile_file(data_dir, "search.yaml"), _dump_yaml(s))


def load_resume(data_dir: Path) -> MasterResume | None:
    path = _profile_file(data_dir, "resume.json")
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as e:
        raise SettingsError(f"{path.name} could not be read: {e}") from e
    try:
        return MasterResume.model_validate(raw)
    except ValidationError as e:
        raise SettingsError(format_validation_error(path, e)) from e


def save_resume(data_dir: Path, r: MasterResume) -> None:
    text = json.dumps(r.model_dump(mode="json"), indent=2, ensure_ascii=False)
    _write(_profile_file(data_dir, "resume.json"), text + "\n")
