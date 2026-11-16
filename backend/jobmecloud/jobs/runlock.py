import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy import Engine, insert, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from jobmecloud.db.models import RunLock
from jobmecloud.db.retry import is_conflict

HEARTBEAT_SECONDS = 30
STALE_AFTER = timedelta(minutes=10)
IN_PROGRESS_COPY = "A run is already in progress."

_lock = RunLock.__table__


class RunInProgressError(Exception):
    def __init__(self) -> None:
        super().__init__(IN_PROGRESS_COPY)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _is_stale(acquired_at: datetime, heartbeat_at: datetime | None, now: datetime) -> bool:
    """A lock is stale when its last sign of life, the heartbeat or else the acquire, is old."""
    return _aware(now) - _aware(heartbeat_at or acquired_at) >= STALE_AFTER


def _current_holder(conn):
    return conn.execute(select(_lock.c.acquired_at, _lock.c.heartbeat_at, _lock.c.owner)
                        .where(_lock.c.id == 1)).first()


def acquire_run_lock(engine: Engine, now: datetime) -> str:
    """Take the run lock and return this holder's owner token.

    No SAVEPOINT (Aurora DSQL has none): each attempt is its own transaction, and a write conflict
    (DSQL reports them at commit) means somebody else got there first.
    """
    owner = uuid.uuid4().hex
    for _ in range(2):  # a second pass covers a lock that was released between the two steps
        try:
            with engine.begin() as conn:
                conn.execute(insert(_lock).values(id=1, acquired_at=now, owner=owner, heartbeat_at=None))
            return owner
        except IntegrityError:
            pass  # held by someone: look at it below
        except DBAPIError as exc:
            if is_conflict(exc):
                raise RunInProgressError from None
            raise
        try:
            with engine.begin() as conn:
                row = _current_holder(conn)
                if row is None:
                    continue  # released since the insert failed: try the insert again
                if not _is_stale(row.acquired_at, row.heartbeat_at, now):
                    raise RunInProgressError
                result = conn.execute(
                    update(_lock).where(_lock.c.id == 1, _lock.c.owner == row.owner)
                    .values(acquired_at=now, owner=owner, heartbeat_at=None)
                )
                if result.rowcount != 1:
                    raise RunInProgressError
            return owner
        except DBAPIError as exc:
            if is_conflict(exc):
                raise RunInProgressError from None
            raise
    raise RunInProgressError


def touch_run_lock(engine: Engine, owner: str, now: datetime) -> bool:
    """Record a sign of life, but only while this owner still holds the lock."""
    with engine.begin() as conn:
        result = conn.execute(
            update(_lock).where(_lock.c.id == 1, _lock.c.owner == owner).values(heartbeat_at=now)
        )
    return result.rowcount == 1


def release_run_lock(engine: Engine, owner: str | None = None) -> None:
    """Free the lock. With an owner token, only if that owner still holds it."""
    with engine.begin() as conn:
        stmt = _lock.delete().where(_lock.c.id == 1)
        if owner is not None:
            stmt = stmt.where(_lock.c.owner == owner)
        conn.execute(stmt)


def run_lock_held(engine: Engine, now: datetime) -> bool:
    with engine.connect() as conn:
        row = conn.execute(select(_lock.c.acquired_at, _lock.c.heartbeat_at).where(_lock.c.id == 1)).first()
    return row is not None and not _is_stale(row.acquired_at, row.heartbeat_at, now)


class Heartbeat:
    def __init__(self, engine: Engine, owner: str, interval: float) -> None:
        self._stop = threading.Event()
        self.lost = threading.Event()  # set when the lock was taken over: someone else owns it now
        self.thread = threading.Thread(target=self._beat, args=(engine, owner, interval), daemon=True)

    def _beat(self, engine: Engine, owner: str, interval: float) -> None:
        while not self._stop.wait(interval):
            try:
                if not touch_run_lock(engine, owner, datetime.now(timezone.utc)):
                    self.lost.set()  # a run that was asleep too long: another run took over
                    return
            except Exception:
                pass  # a missed beat is harmless; the next one tries again

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.thread.join(timeout=5)


@contextmanager
def lock_heartbeat(engine: Engine, owner: str, interval: float = HEARTBEAT_SECONDS):
    """Keep the lock alive from a background thread for as long as the block runs."""
    beat = Heartbeat(engine, owner, interval)
    beat.start()
    try:
        yield beat
    finally:
        beat.stop()
