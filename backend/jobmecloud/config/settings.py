from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator

from jobmecloud.config.files import atomic_write_text

Day = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAYS: tuple[Day, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class SettingsError(Exception):
    pass


class ProviderConfig(BaseModel):
    id: str
    kind: Literal["anthropic", "openai_compatible"]
    label: str
    base_url: str | None = None
    structured_output: Literal["native", "prompt"] = "native"


class StepModel(BaseModel):
    provider_id: str
    model: str


class Caps(BaseModel):
    max_searches_per_run: int = Field(default=20, ge=0)
    max_spend_per_run_usd: float = Field(default=2.0, ge=0)
    max_applications_per_run: int = Field(default=10, ge=0)


class Price(BaseModel):
    input_per_mtok: float
    output_per_mtok: float


class Schedule(BaseModel):
    enabled: bool = False
    days: list[Day] = []
    times: list[Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")]] = []


def _default_prices() -> dict[str, Price]:
    return {
        "claude-opus-5-5": Price(input_per_mtok=4, output_per_mtok=20),
        "claude-sonnet-5-5": Price(input_per_mtok=2, output_per_mtok=10),
        "claude-haiku-5-5": Price(input_per_mtok=0.10, output_per_mtok=0.50),
    }


class Settings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    applications_dir: str | None = None
    folder_pattern: str = "{date}_{company}_{title}"
    match_cutoff: int = Field(default=75, ge=0, le=100)
    providers: list[ProviderConfig] = []
    steps: dict[Literal["search", "extract", "liveness", "score", "tailor"], StepModel] = {}
    search_backend: Literal["builtin", "tavily", "brave"] = "builtin"
    caps: Caps = Field(default_factory=Caps)
    prices: dict[str, Price] = Field(default_factory=_default_prices)
    skip_reasons: list[str] = [
        "Pay too low",
        "Location",
        "Not a fit",
        "Skill gap",
        "Applied elsewhere",
        "Other",
    ]
    followup_default_days: int | None = Field(default=7, ge=0)
    schedule: Schedule = Field(default_factory=Schedule)
    setup_completed_steps: list[int] = []
    setup_skipped_steps: list[int] = []
    cover_letter_tone: Literal["formal", "warm", "direct"] = "warm"

    @field_validator("skip_reasons")
    @classmethod
    def _check_skip_reasons(cls, value: list[str]) -> list[str]:
        reasons = [r.strip() for r in value]
        if not reasons:
            raise ValueError("Add at least one skip reason.")
        if any(not r for r in reasons):
            raise ValueError("A skip reason can't be blank.")
        if any(len(r) > 40 for r in reasons):
            raise ValueError("Each skip reason must be 40 characters or fewer.")
        lowered = [r.lower() for r in reasons]
        if len(set(lowered)) != len(lowered):
            raise ValueError("A skip reason is listed more than once.")
        if "other" not in lowered:
            reasons.append("Other")
        return reasons

    def applications_path(self, data_dir: Path) -> Path:
        if self.applications_dir:
            return Path(self.applications_dir).expanduser()
        return data_dir / "applications"


def format_validation_error(path: Path, e: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(p) for p in err['loc'])} - {err['msg']}" for err in e.errors()
    )
    return f"Problem in {path}: {problems}"


def _settings_file(data_dir: Path) -> Path:
    return data_dir / "settings.yaml"


def save_settings(data_dir: Path, s: Settings) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(s.model_dump(mode="json"), sort_keys=False)
    atomic_write_text(_settings_file(data_dir), text)


def load_settings(data_dir: Path) -> Settings:
    f = _settings_file(data_dir)
    if not f.exists():
        s = Settings()
        save_settings(data_dir, s)
        return s
    try:
        raw = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise SettingsError(f"settings.yaml is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise SettingsError("settings.yaml must contain settings written as `name: value` lines")
    try:
        return Settings.model_validate(raw)
    except ValidationError as e:
        raise SettingsError(format_validation_error(f, e)) from e
