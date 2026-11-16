"""What every worker Lambda does first: get the data folder and the database ready."""

import logging
import os
from pathlib import Path

from sqlalchemy import Engine

from jobmecloud.config import paths
from jobmecloud.db.engine import make_engine
from jobmecloud.llm.redact import install_log_redaction
from jobmecloud.storage.workspace import Workspace

log = logging.getLogger(__name__)
LAMBDA_MARGIN_MS = 90_000  # stop starting new work when this little time is left


def bootstrap() -> tuple[Path, Engine, Workspace | None]:
    install_log_redaction()
    data_dir = paths.data_dir()
    workspace = None
    if os.environ.get("JOBMECLOUD_BUCKET"):
        workspace = Workspace(os.environ["JOBMECLOUD_BUCKET"], os.environ.get("JOBMECLOUD_PREFIX", "workspace"), data_dir)
        workspace.pull()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, make_engine(data_dir=data_dir), workspace


def time_is_short(context, margin_ms: int = LAMBDA_MARGIN_MS) -> bool:
    return context.get_remaining_time_in_millis() < margin_ms
