import os

import pytest
from moto import mock_aws
from fakes import FakeProvider
from fastapi.testclient import TestClient
from sqlmodel import Session

from jobmecloud.api.app import create_app
from jobmecloud.db.engine import make_engine
from jobmecloud.db.migrate import migrate


@pytest.fixture(autouse=True)
def aws():
    """Fake AWS (SSM, S3, ...) so no test ever touches a real account."""
    keep = {k: os.environ.get(k) for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_DEFAULT_REGION",
                                           "AWS_REGION", "AWS_PROFILE")}
    os.environ.update({"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
                       "AWS_DEFAULT_REGION": "us-east-1", "AWS_REGION": "us-east-1"})
    os.environ.pop("AWS_PROFILE", None)
    with mock_aws():
        yield
    for k, v in keep.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("JOBMECLOUD_DATA_DIR", str(d))
    return d


@pytest.fixture
def client(data_dir):
    app = create_app(data_dir, provider_builder=lambda c: FakeProvider(replies=["OK"]))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def engine(data_dir):
    e = make_engine(data_dir=data_dir)
    migrate(e)
    yield e
    e.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s
