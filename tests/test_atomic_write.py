import os

import pytest

from jobmecloud.config import files
from jobmecloud.config.files import atomic_write_text


def _flaky_replace(real, failures):
    calls = {"n": 0}

    def replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= failures:
            raise PermissionError(5, "Access is denied")  # a sync tool holds the file for a moment
        return real(src, dst)

    return replace, calls


def test_a_briefly_locked_file_is_written_after_a_retry(tmp_path, monkeypatch):
    target = tmp_path / "settings.yaml"
    target.write_text("old", encoding="utf-8")
    replace, calls = _flaky_replace(os.replace, 2)
    monkeypatch.setattr(files.os, "replace", replace)
    monkeypatch.setattr(files.time, "sleep", lambda s: None)
    atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new" and calls["n"] == 3
    assert not (tmp_path / "settings.yaml.tmp").exists()


def test_a_file_that_stays_locked_still_fails_and_leaves_the_old_content(tmp_path, monkeypatch):
    target = tmp_path / "settings.yaml"
    target.write_text("old", encoding="utf-8")
    replace, _ = _flaky_replace(os.replace, 10**6)
    monkeypatch.setattr(files.os, "replace", replace)
    monkeypatch.setattr(files.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError):
        atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old"
