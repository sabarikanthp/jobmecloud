"""Who made a change, when it was made through an API key instead of the website."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

ACTOR: ContextVar[str | None] = ContextVar("jobmecloud_actor", default=None)


@contextmanager
def acting_as(label: str) -> Iterator[None]:
    """Inside this block, activity that would be logged as the user is logged as `label` (e.g. "claude:Desktop")."""
    token = ACTOR.set(label)
    try:
        yield
    finally:
        ACTOR.reset(token)


def resolve(actor: str) -> str:
    """The user's own changes take the label while one is set; automatic (system) changes never do."""
    label = ACTOR.get()
    return label if label and actor == "user" else actor
