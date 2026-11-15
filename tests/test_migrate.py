from sqlalchemy import inspect

from jobmecloud.db.engine import make_engine
from jobmecloud.db.migrate import migrate


def test_creates_all_tables(tmp_path):
    e = make_engine(data_dir=tmp_path)
    changes = migrate(e)
    names = set(inspect(e).get_table_names())
    assert {"job", "runjob", "interview", "contact", "followup",
            "activitylog", "run", "watchlistemployer", "runlock"} <= names
    assert "job" in changes
    e.dispose()


def test_adds_missing_column_with_default(tmp_path):
    e = make_engine(data_dir=tmp_path)
    with e.begin() as c:
        c.exec_driver_sql("CREATE TABLE run (id INTEGER PRIMARY KEY, trigger VARCHAR NOT NULL, "
                          "started_at DATETIME NOT NULL)")
    changes = migrate(e)
    cols = {c["name"] for c in inspect(e).get_columns("run")}
    assert {"stage", "found", "errors"} <= cols
    assert "run.found" in changes
    e.dispose()


def test_migrate_idempotent_returns_empty(tmp_path):
    e = make_engine(data_dir=tmp_path)
    migrate(e)
    assert migrate(e) == []
    e.dispose()
