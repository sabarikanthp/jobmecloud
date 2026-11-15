"""Retry writes that Aurora DSQL rejects at commit time (optimistic concurrency conflicts)."""

import functools
import json
import random
import time
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import DBAPIError

T = TypeVar("T")

CONFLICT_SQLSTATE = "40001"  # serialization_failure
CONFLICT_CODES = ("OC000", "OC001")  # DSQL's own codes for data and schema conflicts


def is_conflict(exc: BaseException) -> bool:
    if not isinstance(exc, DBAPIError):
        return False
    orig = exc.orig
    state = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
    text = str(orig)
    return state == CONFLICT_SQLSTATE or any(code in text for code in CONFLICT_CODES)


def retry_on_conflict(attempts: int = 5, base_delay: float = 0.05):
    """Re-run the function when the database reports a write conflict. It must open its own session."""

    def decorate(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            for attempt in range(attempts):
                try:
                    return fn(*args, **kwargs)
                except DBAPIError as exc:
                    if not is_conflict(exc) or attempt == attempts - 1:
                        raise
                    time.sleep(base_delay * (2**attempt) * (0.5 + random.random()))
            raise AssertionError("unreachable")

        return wrapper

    return decorate


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_BUSY = {"detail": "Please try again."}


class ConflictRetryMiddleware:
    """Replays a write request once if it hit a database conflict, then answers 409."""

    def __init__(self, app, delay: float = 0.1):
        self.app = app
        self.delay = delay

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in _SAFE_METHODS:
            return await self.app(scope, receive, send)

        chunks = []
        while True:
            message = await receive()
            chunks.append(message)
            if message["type"] != "http.request" or not message.get("more_body"):
                break

        for attempt in range(2):
            started = False
            replay = iter(chunks)

            async def replay_receive():
                try:
                    return next(replay)
                except StopIteration:
                    return await receive()

            async def tracking_send(message):
                nonlocal started
                started = started or message["type"] == "http.response.start"
                await send(message)

            try:
                return await self.app(scope, replay_receive, tracking_send)
            except DBAPIError as exc:
                if started or not is_conflict(exc):
                    raise
                if attempt == 0:
                    time.sleep(self.delay)
        body = json.dumps(_BUSY).encode()
        await send({"type": "http.response.start", "status": 409,
                    "headers": [(b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})
