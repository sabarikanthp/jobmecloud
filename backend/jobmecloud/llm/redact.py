"""Keep API keys out of messages that are saved or shown."""

import logging
import re
import traceback
from collections.abc import Iterable

_KEY_SHAPES = re.compile(r"\b(?:sk|tvly|BSA)[-_][A-Za-z0-9_\-]{10,}")
HIDDEN = "[hidden]"


def redact(text: str, known_secrets: Iterable[str] = ()) -> str:
    for secret in known_secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, HIDDEN)
    return _KEY_SHAPES.sub(HIDDEN, text)


_installed = False


def install_log_redaction() -> None:
    """Hide key-shaped strings in every log message and traceback (CloudWatch keeps them for 14 days)."""
    global _installed
    if _installed:
        return
    _installed = True
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.msg = redact(record.getMessage())
        record.args = None
        if record.exc_info and record.exc_info[0] is not None:
            record.exc_text = redact("".join(traceback.format_exception(*record.exc_info)).rstrip())
        return record

    logging.setLogRecordFactory(factory)
