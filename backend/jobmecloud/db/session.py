from pathlib import Path

from sqlalchemy import JSON, Engine, event
from sqlmodel import SQLModel, create_engine

from jobmecloud.db import models  # noqa: F401  (registers tables on SQLModel.metadata)


def get_engine(data_dir: Path) -> Engine:
    engine = create_engine(f"sqlite:///{Path(data_dir) / 'jobmecloud.db'}")

    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    return engine


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    add_missing_columns(engine)


def add_missing_columns(engine: Engine) -> list[str]:
    """Add model columns missing from existing tables; return "table.column" names."""
    added: list[str] = []
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            existing = {r[1] for r in conn.exec_driver_sql(f'PRAGMA table_info("{table.name}")')}
            for col in table.columns:
                if col.name in existing:
                    continue
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" '                       f"{col.type.compile(dialect=engine.dialect)}"
                default = _default_clause(col)
                if default is not None:
                    ddl += f" DEFAULT {default}"
                conn.exec_driver_sql(ddl)
                added.append(f"{table.name}.{col.name}")
    return added


def _default_clause(col) -> str | None:
    if isinstance(col.type, JSON):
        return "'[]'"
    if col.nullable:
        return None
    default = col.default.arg if col.default is not None and col.default.is_scalar else None
    if isinstance(default, bool):
        return str(int(default))
    if isinstance(default, (int, float)):
        return repr(default)
    if isinstance(default, str):
        return "'" + default.replace("'", "''") + "'"
    return None
