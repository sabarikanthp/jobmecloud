import boto3
import pytest

from jobmecloud.storage.workspace import Workspace

BUCKET = "jobmecloud-test-data"


@pytest.fixture
def s3():
    client = boto3.client("s3")
    client.create_bucket(Bucket=BUCKET)
    return client


def put(s3, key, body=b"x"):
    s3.put_object(Bucket=BUCKET, Key=key, Body=body)


def test_pull_downloads_nested_files(s3, tmp_path):
    put(s3, "ws/settings.yaml", b"a: 1")
    put(s3, "ws/profile/resume.json", b"{}")
    Workspace(BUCKET, "ws", tmp_path).pull()
    assert (tmp_path / "settings.yaml").read_bytes() == b"a: 1"
    assert (tmp_path / "profile" / "resume.json").read_bytes() == b"{}"


def test_pull_ignores_other_prefixes(s3, tmp_path):
    put(s3, "other/secret.txt")
    Workspace(BUCKET, "ws", tmp_path).pull()
    assert list(tmp_path.rglob("*.txt")) == []


def test_second_pull_skips_unchanged_files(s3, tmp_path):
    put(s3, "ws/a.txt", b"one")
    w = Workspace(BUCKET, "ws", tmp_path)
    w.pull()
    (tmp_path / "a.txt").write_bytes(b"edited locally")
    stamp = (tmp_path / "a.txt").stat().st_mtime_ns
    w.pull()
    assert (tmp_path / "a.txt").stat().st_mtime_ns == stamp  # not re-downloaded


def test_pull_replaces_a_file_changed_in_s3(s3, tmp_path):
    put(s3, "ws/a.txt", b"one")
    w = Workspace(BUCKET, "ws", tmp_path)
    w.pull()
    put(s3, "ws/a.txt", b"two-two")
    w.pull()
    assert (tmp_path / "a.txt").read_bytes() == b"two-two"


def test_push_uploads_only_changed_and_returns_keys(s3, tmp_path):
    put(s3, "ws/keep.txt", b"same")
    w = Workspace(BUCKET, "ws", tmp_path)
    w.pull()
    (tmp_path / "new.txt").write_bytes(b"fresh")
    (tmp_path / "keep.txt").write_bytes(b"changed!")
    keys = sorted(w.push())
    assert keys == ["ws/keep.txt", "ws/new.txt"]
    assert s3.get_object(Bucket=BUCKET, Key="ws/new.txt")["Body"].read() == b"fresh"
    assert w.push() == []  # nothing changed since


def test_push_never_uploads_database_files(s3, tmp_path):
    w = Workspace(BUCKET, "ws", tmp_path)
    (tmp_path / "jobmecloud.db").write_bytes(b"sqlite")
    (tmp_path / "jobmecloud.db-wal").write_bytes(b"wal")
    (tmp_path / "ok.txt").write_bytes(b"ok")
    assert w.push() == ["ws/ok.txt"]


def test_presign_has_expiry(s3, tmp_path):
    url = Workspace(BUCKET, "ws", tmp_path).presign("applications/Acme/resume.docx", expires=300)
    assert "ws/applications/Acme/resume.docx" in url and "Expires=" in url
