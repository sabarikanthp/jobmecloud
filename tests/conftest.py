import keyring
import keyring.backend
import pytest
from fakes import FakeProvider
from fastapi.testclient import TestClient
from sqlmodel import Session

from jobmecloud.api.app import create_app
from jobmecloud.config import paths
from jobmecloud.db.engine import make_engine
from jobmecloud.db.migrate import migrate


class _MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self._store = {}

    def set_password(self, service, username, password):
        self._store[(service, username)] = password

    def get_password(self, service, username):
        return self._store.get((service, username))

    def delete_password(self, service, username):
        try:
            del self._store[(service, username)]
        except KeyError:
            raise keyring.errors.PasswordDeleteError("not found")


@pytest.fixture(autouse=True)
def memory_keyring():
    previous = keyring.get_keyring()
    keyring.set_keyring(_MemoryKeyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("JOBMECLOUD_DATA_DIR", str(d))
    return d


@pytest.fixture(autouse=True)
def isolated_location_file(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "_location_file", lambda: tmp_path / "config" / "location.json")


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
