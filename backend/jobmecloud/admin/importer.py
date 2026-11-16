"""Move a local JobMe app's data into a deployed JobMeCloud.

Reads a copy of the local database (never the original), so the local app is not changed. Rows keep their
ids, so every link between jobs, runs and the activity log still holds. Everything can be repeated: rows
already in the cloud are skipped and unchanged files are not uploaded again.
"""

import hashlib
import sqlite3
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

import yaml
from botocore.exceptions import ClientError
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel

from jobmecloud import secrets
from jobmecloud.config.settings import Settings
from jobmecloud.db import models  # noqa: F401  (registers the tables)
from jobmecloud.db.batch import chunked
from jobmecloud.db.retry import retry_on_conflict

# Parents before children. runlock is left out on purpose: a lock copied from another machine would only block runs.
TABLES = ["customfield", "watchlistemployer", "run", "job", "runjob", "customvalue", "activitylog"]
KEYRING_SERVICE = "jobme"  # where the local app keeps API keys


def snapshot_db(source: Path, dest_dir: Path) -> Path:
    """Copy a (possibly in-use) SQLite database, including its write-ahead log, without modifying the original."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "jobme-snapshot.db"
    src = sqlite3.connect(f"file:{Path(source).as_posix()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dest


def open_local(snapshot: Path) -> Engine:
    return create_engine(f"sqlite:///{Path(snapshot).as_posix()}")


def map_docs_folder(folder: str | None, apps_dir: Path, cloud_apps_dir: str) -> str | None:
    """Where a job's documents folder lives in the cloud, or None when it no longer exists locally."""
    if not folder:
        return None
    path = Path(folder)
    try:
        rel = path.relative_to(apps_dir)
    except ValueError:
        return None
    if not rel.parts or not path.is_dir():
        return None
    return str(PurePosixPath(cloud_apps_dir, *rel.parts))


def job_folder_names(src: Engine, apps_dir: Path) -> list[str]:
    """Top-level folder names (inside the applications folder) that jobs point at and that still exist."""
    with src.connect() as c:
        folders = [r[0] for r in c.execute(text("select docs_folder from job where docs_folder is not null"))]
    names: dict[str, None] = {}
    for f in folders:
        try:
            rel = Path(f).relative_to(apps_dir)
        except ValueError:
            continue
        if rel.parts and Path(f).is_dir():
            names[rel.parts[0]] = None
    return list(names)


def _existing_ids(dst: Engine, table) -> set[int]:
    with dst.connect() as c:
        return {r[0] for r in c.execute(select(table.c.id))}


def copy_rows(src: Engine, dst: Engine, *, apps_dir: Path, cloud_apps_dir: str, dry_run: bool = False) -> dict[str, int]:
    """Copy every table's rows that the cloud does not have yet. Returns how many rows per table were (or would be) added."""
    counts: dict[str, int] = {}
    src_tables = set(inspect(src).get_table_names())
    reposts: dict[int, int] = {}
    for name in TABLES:
        table = SQLModel.metadata.tables[name]
        if name not in src_tables:
            counts[name] = 0
            continue
        source_columns = {c["name"] for c in inspect(src).get_columns(name)}
        columns = [c for c in table.c if c.name in source_columns]  # older apps lack newer columns; those stay empty
        with src.connect() as c:
            rows = [dict(r._mapping) for r in c.execute(select(*columns).order_by(table.c.id))]
        have = _existing_ids(dst, table)
        rows = [r for r in rows if r["id"] not in have]
        for r in rows:
            if name == "job":
                r["docs_folder"] = map_docs_folder(r.get("docs_folder"), apps_dir, cloud_apps_dir)
                if r.get("repost_of_id") is not None:
                    reposts[r["id"]] = r["repost_of_id"]
                    r["repost_of_id"] = None  # linked afterwards, once every job exists
        counts[name] = len(rows)
        if dry_run:
            continue
        for batch in chunked(rows):
            _insert(dst, table, batch)
    if not dry_run:
        _link_reposts(dst, reposts)
        _restart_counters(dst)
    return counts


@retry_on_conflict()
def _insert(dst: Engine, table, batch: list[dict]) -> None:
    with dst.begin() as c:
        c.execute(table.insert(), batch)


def _link_reposts(dst: Engine, reposts: dict[int, int]) -> None:
    job = SQLModel.metadata.tables["job"]
    for batch in chunked(reposts.items()):
        _set_reposts(dst, job, batch)


@retry_on_conflict()
def _set_reposts(dst: Engine, job, batch: list[tuple[int, int]]) -> None:
    with dst.begin() as c:
        for job_id, original in batch:
            c.execute(update(job).where(job.c.id == job_id).values(repost_of_id=original))


def _restart_counters(dst: Engine) -> None:
    """New rows must number after the imported ones. SQLite does this by itself; Aurora DSQL needs telling."""
    if dst.dialect.name != "postgresql":
        return
    for name in TABLES:
        table = SQLModel.metadata.tables[name]
        with dst.connect() as c:
            top = c.execute(select(table.c.id).order_by(table.c.id.desc()).limit(1)).scalar()
        if top is not None:
            with dst.begin() as c:  # DDL goes in its own transaction on DSQL
                c.execute(text(f'ALTER TABLE "{name}" ALTER COLUMN id RESTART WITH {int(top) + 1}'))


def cloud_settings(raw: dict) -> Settings:
    """The local settings, made right for the cloud: no local folder, and no schedule (EventBridge has none yet)."""
    keep = {k: v for k, v in raw.items() if k not in ("applications_dir", "schedule")}
    return Settings.model_validate(keep)


def plan_files(data_dir: Path, apps_dir: Path, folders: Iterable[str]) -> list[tuple[Path, str]]:
    """(local file, workspace key) for the profile, run logs and the document folders jobs point at."""
    plan: list[tuple[Path, str]] = []
    roots = [(Path(data_dir) / "profile", "profile"), (Path(data_dir) / "logs", "logs")]
    roots += [(Path(apps_dir) / f, f"applications/{f}") for f in folders]
    for root, base in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.name.endswith((".db", ".db-wal", ".db-shm")):
                plan.append((path, f"{base}/{path.relative_to(root).as_posix()}"))
    return plan


def _etag_matches(s3, bucket: str, key: str, body: bytes) -> bool:
    try:
        etag = s3.head_object(Bucket=bucket, Key=key)["ETag"].strip('"')
    except ClientError:
        return False
    return etag == hashlib.md5(body).hexdigest()


def upload_files(s3, bucket: str, prefix: str, files: list[tuple[Path, str]], settings: Settings) -> int:
    """Upload what changed. Returns how many objects were written."""
    written = 0
    uploads = [(path.read_bytes(), key) for path, key in files]
    uploads.append((yaml.safe_dump(settings.model_dump(mode="json"), sort_keys=False).encode("utf-8"), "settings.yaml"))
    for body, key in uploads:
        full = f"{prefix.strip('/')}/{key}"
        if _etag_matches(s3, bucket, full, body):
            continue
        s3.put_object(Bucket=bucket, Key=full, Body=body)
        written += 1
    return written


def _local_key(name: str) -> str | None:
    import keyring  # only the importer needs it, and only when copying keys

    return keyring.get_password(KEYRING_SERVICE, name)


def copy_api_keys(provider_ids: Iterable[str]) -> list[str]:
    """Copy each provider's API key from the local credential store into Parameter Store. Returns provider ids only."""
    moved = []
    for pid in provider_ids:
        key = _local_key(f"provider:{pid}")
        if key:
            secrets.set_secret(f"provider:{pid}", key)
            moved.append(pid)
    return moved
