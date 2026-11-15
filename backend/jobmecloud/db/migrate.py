"""Create missing tables and columns. Runs at deploy time (and at start-up for SQLite)."""

from sqlalchemy import JSON, Engine, inspect
from sqlalchemy.schema import CreateIndex, CreateTable
from sqlmodel import SQLModel

from jobmecloud.db import models  # noqa: F401  (registers tables on SQLModel.metadata)


def migrate(engine: Engine) -> list[str]:
    """Bring the schema up to date; return what changed ("table" or "table.column")."""
    changes: list[str] = []
    existing = set(inspect(engine).get_table_names())
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in existing:
            _create_table(engine, table)
            changes.append(table.name)
            continue
        have = {c["name"] for c in inspect(engine).get_columns(table.name)}
        for col in table.columns:
            if col.name not in have:
                _add_column(engine, table, col)
                changes.append(f"{table.name}.{col.name}")
    return changes


def _create_table(engine: Engine, table) -> None:
    if engine.dialect.name != "postgresql":
        table.create(engine)
        return
    # DSQL: DDL statements each run in their own transaction, and indexes are built asynchronously.
    with engine.begin() as conn:
        conn.execute(CreateTable(table))
    for index in table.indexes:
        sql = str(CreateIndex(index).compile(dialect=engine.dialect))
        sql = sql.replace("CREATE UNIQUE INDEX", "CREATE UNIQUE INDEX ASYNC", 1) if "UNIQUE" in sql[:20] \
            else sql.replace("CREATE INDEX", "CREATE INDEX ASYNC", 1)
        with engine.begin() as conn:
            conn.exec_driver_sql(sql)


def _add_column(engine: Engine, table, col) -> None:
    column_type = col.type.compile(dialect=engine.dialect)
    default = _default_clause(col)
    name, tname = f'"{col.name}"', f'"{table.name}"'
    if engine.dialect.name != "postgresql":
        ddl = f"ALTER TABLE {tname} ADD COLUMN {name} {column_type}"
        if default is not None:
            ddl += f" DEFAULT {default}"
        with engine.begin() as conn:
            conn.exec_driver_sql(ddl)
        return
    # DSQL: ADD COLUMN takes a type only. Apply the default in a second statement, and fill old rows.
    with engine.begin() as conn:
        conn.exec_driver_sql(f"ALTER TABLE {tname} ADD COLUMN {name} {column_type}")
    if default is not None:
        with engine.begin() as conn:
            conn.exec_driver_sql(f"ALTER TABLE {tname} ALTER COLUMN {name} SET DEFAULT {default}")
        with engine.begin() as conn:
            conn.exec_driver_sql(f"UPDATE {tname} SET {name} = {default} WHERE {name} IS NULL")


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
