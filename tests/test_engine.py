from unittest.mock import MagicMock

import pytest

from jobmecloud.db import engine as engine_mod
from jobmecloud.db.engine import dsql_creator, make_engine


def test_sqlite_when_no_url(tmp_path, monkeypatch):
    monkeypatch.delenv("JOBMECLOUD_DB_URL", raising=False)
    e = make_engine(data_dir=tmp_path)
    assert e.dialect.name == "sqlite"
    assert "jobmecloud.db" in str(e.url)
    e.dispose()


def test_dsql_url_builds_postgres_engine(monkeypatch):
    monkeypatch.delenv("JOBMECLOUD_DB_URL", raising=False)
    e = make_engine("dsql://abc123.dsql.us-east-1.on.aws")
    assert e.dialect.name == "postgresql"
    e.dispose()


def test_dsql_creator_uses_iam_token_as_password(monkeypatch):
    dsql = MagicMock()
    dsql.generate_db_connect_admin_auth_token.return_value = "TOKEN"
    monkeypatch.setattr(engine_mod.boto3, "client", lambda *a, **k: dsql)
    connect = MagicMock(return_value="CONN")
    monkeypatch.setattr(engine_mod.psycopg, "connect", connect)

    conn = dsql_creator("abc123.dsql.us-east-1.on.aws")()

    assert conn == "CONN"
    kwargs = connect.call_args.kwargs
    assert kwargs["password"] == "TOKEN"
    assert kwargs["host"] == "abc123.dsql.us-east-1.on.aws"
    assert kwargs["user"] == "admin" and kwargs["dbname"] == "postgres"
    assert kwargs["sslmode"] == "require"
    assert dsql.generate_db_connect_admin_auth_token.call_args.args[1] == "us-east-1"


def test_env_var_overrides_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBMECLOUD_DB_URL", "dsql://abc123.dsql.us-west-2.on.aws")
    e = make_engine(data_dir=tmp_path)
    assert e.dialect.name == "postgresql"
    e.dispose()


def test_unknown_url_scheme_rejected():
    with pytest.raises(ValueError, match="dsql://"):
        make_engine("mysql://nope")
