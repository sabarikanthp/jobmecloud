from pathlib import Path

from jobmecloud.config import paths


def test_data_dir_env_expands_user(monkeypatch):
    monkeypatch.setenv("JOBMECLOUD_DATA_DIR", "~/JM")
    assert paths.data_dir() == Path.home() / "JM"


def test_data_dir_defaults_to_lambda_scratch(monkeypatch):
    monkeypatch.delenv("JOBMECLOUD_DATA_DIR", raising=False)
    assert paths.data_dir() == Path("/tmp/jobmecloud")


def test_data_dir_does_not_create_folder(tmp_path, monkeypatch):
    d = tmp_path / "nope"
    monkeypatch.setenv("JOBMECLOUD_DATA_DIR", str(d))
    assert paths.data_dir() == d
    assert not d.exists()
