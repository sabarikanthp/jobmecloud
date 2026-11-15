"""Keep API keys out of messages that are saved or shown."""

import re
from collections.abc import Iterable

_KEY_SHAPES = re.compile(r"\b(?:sk|tvly|BSA)[-_][A-Za-z0-9_\-]{10,}")
HIDDEN = "[hidden]"


def redact(text: str, known_secrets: Iterable[str] = ()) -> str:
    for secret in known_secrets:
        if secret and len(secret) >= 8:
            text = text.replace(secret, HIDDEN)
    return _KEY_SHAPES.sub(HIDDEN, text)
