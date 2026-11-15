import json
import os
from pathlib import Path

from platformdirs import user_config_dir

from jobmecloud.config.settings import Settings


def _location_file() -> Path:
    return Path(user_config_dir("JobMe")) / "location.json"


def data_dir() -> Path:
    """Where JobMe keeps its data. Does not create anything."""
    env = os.environ.get("JOBMECLOUD_DATA_DIR")
    if env:
        return Path(env).expanduser()
    try:
        saved = json.loads(_location_file().read_text(encoding="utf-8"))["data_dir"]
        if saved:
            return Path(saved).expanduser()
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return Path.home() / "JobMe"


def set_data_dir(path: Path) -> None:
    f = _location_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"data_dir": str(path)}), encoding="utf-8")


def ensure_dirs(data_dir: Path, settings: Settings) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "profile").mkdir(exist_ok=True)
    settings.applications_path(data_dir).mkdir(parents=True, exist_ok=True)
