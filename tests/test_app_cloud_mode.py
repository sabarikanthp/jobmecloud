from unittest.mock import MagicMock

import boto3
import pytest
from fastapi.testclient import TestClient

from jobmecloud.api.app import create_app
from jobmecloud.config.settings import load_settings

BUCKET = "jobmecloud-test-data"


@pytest.fixture
def cloud(monkeypatch):
    boto3.client("s3").create_bucket(Bucket=BUCKET)
    monkeypatch.setenv("JOBMECLOUD_BUCKET", BUCKET)
    monkeypatch.setenv("JOBMECLOUD_PREFIX", "ws")


def test_allowed_hosts_from_env(data_dir, monkeypatch):
    monkeypatch.setenv("JOBMECLOUD_ALLOWED_HOSTS", "app.example.com, other.example.com")
    app = create_app(data_dir)
    with TestClient(app, base_url="http://app.example.com") as c:
        assert c.get("/api/health").status_code == 200


def test_unknown_host_rejected(data_dir, monkeypatch):
    monkeypatch.setenv("JOBMECLOUD_ALLOWED_HOSTS", "app.example.com")
    app = create_app(data_dir)
    with TestClient(app, base_url="http://evil.example.net") as c:
        assert c.get("/api/health").status_code == 400


def test_default_hosts_are_local_only(data_dir):
    app = create_app(data_dir)
    with TestClient(app, base_url="http://evil.example.net") as c:
        assert c.get("/api/health").status_code == 400


def test_no_migrate_on_dsql_startup(data_dir, monkeypatch):
    monkeypatch.setenv("JOBMECLOUD_DB_URL", "dsql://abc.dsql.us-east-1.on.aws")
    migrate = MagicMock()
    monkeypatch.setattr("jobmecloud.api.app.migrate", migrate)
    create_app(data_dir)
    migrate.assert_not_called()


def test_workspace_pulled_at_startup(cloud, data_dir):
    boto3.client("s3").put_object(Bucket=BUCKET, Key="ws/settings.yaml", Body=b"followup_default_days: 9\n")
    create_app(data_dir)
    assert load_settings(data_dir).followup_default_days == 9


def test_workspace_pushed_after_write_request(cloud, data_dir):
    app = create_app(data_dir)
    with TestClient(app) as c:
        body = c.get("/api/settings").json()
        body["followup_default_days"] = 12
        assert c.put("/api/settings", json=body).status_code == 200
    stored = boto3.client("s3").get_object(Bucket=BUCKET, Key="ws/settings.yaml")["Body"].read()
    assert b"followup_default_days: 12" in stored


def test_workspace_not_pushed_for_reads(cloud, data_dir):
    app = create_app(data_dir)
    with TestClient(app) as c:
        c.get("/api/settings")
    listing = boto3.client("s3").list_objects_v2(Bucket=BUCKET, Prefix="ws/")
    assert listing.get("KeyCount", 0) == 0
