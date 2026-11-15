import os
import time
from pathlib import Path

REPLACE_TRIES = 8
REPLACE_WAIT = 0.25  # seconds; about two seconds in all


def atomic_write_text(path: Path, text: str) -> None:
    """Write text so a crash never leaves a half-written file.

    On Windows a sync tool (Dropbox, OneDrive) or a virus scanner can hold the file for a moment
    right after it was saved, which makes the final rename fail with "access denied". Retry briefly.
    """
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == REPLACE_TRIES - 1:
                raise
            time.sleep(REPLACE_WAIT)
