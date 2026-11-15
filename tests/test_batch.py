from sqlalchemy import event
from sqlalchemy.orm import Session as OrmSession

from jobmecloud.db.batch import MAX_ROWS_PER_TX, chunked


def test_chunked_sizes():
    sizes = [len(c) for c in chunked(range(1201), 500)]
    assert sizes == [500, 500, 201]


def test_chunked_empty():
    assert list(chunked([], 500)) == []


def test_limit_constant_matches_dsql():
    assert MAX_ROWS_PER_TX == 3000


class RowsPerCommit:
    """Counts rows written between commits, as DSQL counts them (max 3,000 per transaction)."""

    def __init__(self):
        self.current = 0
        self.largest = 0

    def _flush(self, session, _ctx):
        self.current += len(session.new) + len(session.dirty) + len(session.deleted)

    def _commit(self, _session):
        self.largest = max(self.largest, self.current)
        self.current = 0

    def __enter__(self):
        event.listen(OrmSession, "after_flush", self._flush)
        event.listen(OrmSession, "after_commit", self._commit)
        return self

    def __exit__(self, *exc):
        event.remove(OrmSession, "after_flush", self._flush)
        event.remove(OrmSession, "after_commit", self._commit)
