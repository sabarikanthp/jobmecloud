"""Database engines: SQLite for tests and local development, Aurora DSQL in AWS."""

import os
from collections.abc import Callable
from pathlib import Path

import boto3
import psycopg
from sqlalchemy import Engine, create_engine, event

DSQL_PREFIX = "dsql://"
DB_URL_ENV = "JOBMECLOUD_DB_URL"
SQLITE_FILE = "jobmecloud.db"


def _region_of(endpoint: str) -> str:
    parts = endpoint.split(".")
    if len(parts) >= 3 and parts[1] == "dsql":
        return parts[2]
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"


def dsql_creator(endpoint: str, role: str = "admin") -> Callable[[], psycopg.Connection]:
    """Return a connection factory that signs a short-lived IAM token for every new connection."""
    region = _region_of(endpoint)

    def create() -> psycopg.Connection:
        client = boto3.client("dsql", region_name=region)
        if role == "admin":
            token = client.generate_db_connect_admin_auth_token(endpoint, region)
        else:
            token = client.generate_db_connect_auth_token(endpoint, region)
        return psycopg.connect(
            host=endpoint, port=5432, user=role, dbname="postgres", password=token, sslmode="require"
        )

    return create


def _sqlite_engine(data_dir: Path) -> Engine:
    engine = create_engine(f"sqlite:///{Path(data_dir) / SQLITE_FILE}")

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def make_engine(url: str | None = None, data_dir: Path | None = None) -> Engine:
    """`dsql://<endpoint>` (or JOBMECLOUD_DB_URL) gives Aurora DSQL; otherwise SQLite in `data_dir`."""
    url = url or os.environ.get(DB_URL_ENV)
    if url:
        if not url.startswith(DSQL_PREFIX):
            raise ValueError(f"The database url must start with {DSQL_PREFIX}")
        role = os.environ.get("JOBMECLOUD_DB_ROLE", "admin")
        return create_engine(
            "postgresql+psycopg://",
            creator=dsql_creator(url[len(DSQL_PREFIX):], role),
            pool_recycle=2400,  # DSQL closes connections after an hour
            pool_pre_ping=True,
            use_native_hstore=False,  # the hstore lookup runs inside a SAVEPOINT, which DSQL does not support
        )
    if data_dir is None:
        raise ValueError("Give make_engine a url or a data_dir")
    return _sqlite_engine(data_dir)
