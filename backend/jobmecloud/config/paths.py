import os
from pathlib import Path

from jobmecloud.config.settings import Settings

DEFAULT_DATA_DIR = "/tmp/jobmecloud"  # Lambda's writable scratch space


def data_dir() -> Path:
    """The local working folder (a copy of the S3 workspace). Does not create anything."""
    return Path(os.environ.get("JOBMECLOUD_DATA_DIR") or DEFAULT_DATA_DIR).expanduser()


def ensure_dirs(data_dir: Path, settings: Settings) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "profile").mkdir(exist_ok=True)
    settings.applications_path(data_dir).mkdir(parents=True, exist_ok=True)
