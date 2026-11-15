"""Helpers for keeping each database transaction under Aurora DSQL's row limit."""

from collections.abc import Iterable, Iterator
from typing import TypeVar

T = TypeVar("T")

MAX_ROWS_PER_TX = 3000  # DSQL: one transaction may modify at most this many rows
BATCH_ROWS = 500  # imports commit this often; each source row writes at most a few database rows


def chunked(items: Iterable[T], size: int = BATCH_ROWS) -> Iterator[list[T]]:
    chunk: list[T] = []
    for item in items:
        chunk.append(item)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk
