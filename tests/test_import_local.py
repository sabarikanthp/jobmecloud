import json
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pytest
import yaml
from sqlalchemy import text
from sqlmodel import Session, select

from jobmecloud.admin import importer
from jobmecloud.config.settings import Settings
from jobmecloud.db.engine import SQLITE_FILE, make_engine
from jobmecloud.db.migrate import migrate
from jobmecloud.db.models import ActivityLog, Job, RunJob, Run


def make_local_app(root: Path) -> Path:
    """A data folder shaped like the local JobMe app's: database, settings, profile, logs, and an applications
    folder that is the PARENT of the data folder (as in a real Dropbox setup)."""
    apps = root / "Jobs"
    data = apps / "Profile"
    (data / "profile" / "resumes").mkdir(parents=True)
    (data / "logs").mkdir()
    (data / "profile" / "resumes" / "base.docx").write_bytes(b"resume")
    (data / "logs" / "run-1.log").write_text("log", encoding="utf-8")
    (apps / "2026-01-01_Acme_Dev").mkdir()
    (apps / "2026-01-01_Acme_Dev" / "cover.docx").write_bytes(b"cover")
    (apps / "Unrelated folder").mkdir()
    (apps / "Unrelated folder" / "x.txt").write_text("x", encoding="utf-8")

    engine = make_engine(data_dir=data)
    migrate(engine)
    with Session(engine) as s:
        s.add(Run(id=1, trigger="manual", started_at=datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)))
        s.commit()
        s.add(Job(id=1, origin="search", employer="Acme", title="Dev", first_seen_at=datetime(2026, 1, 1, tzinfo=timezone.utc), status="Applied",
                  docs_folder=str(apps / "2026-01-01_Acme_Dev")))
        s.commit()
        s.add(Job(id=2, origin="search", status="New", employer="Beta", title="Ops", first_seen_at=datetime(2026, 1, 2, tzinfo=timezone.utc), repost_of_id=1,
                  docs_folder=str(apps / "missing folder")))
        s.commit()
        s.add(RunJob(id=1, run_id=1, job_id=1, outcome="new"))
        s.add(ActivityLog(id=1, entity_type="job", entity_id=1, job_id=1, action="created", at=datetime(2026, 1, 1, tzinfo=timezone.utc)))
        s.commit()
    with engine.begin() as c:
        c.execute(text("ALTER TABLE job DROP COLUMN docs_status"))  # older app version: lacks newer columns
    engine.dispose()
    (data / SQLITE_FILE).rename(data / "jobme.db")  # the local app calls its database jobme.db
    (data / "settings.yaml").write_text(yaml.safe_dump({
        "applications_dir": str(apps), "folder_pattern": "{company}", "match_cutoff": 80,
        "providers": [{"id": "claude", "kind": "anthropic", "label": "Claude"}],
        "schedule": {"enabled": True, "days": ["mon"], "times": ["16:06"], "wake": True},
        "setup_completed_steps": [1, 2],
    }), encoding="utf-8")
    return data


@pytest.fixture
def local(tmp_path):
    return make_local_app(tmp_path / "local")


@pytest.fixture
def cloud_engine(tmp_path):
    (tmp_path / "cloud").mkdir()
    engine = make_engine(data_dir=tmp_path / "cloud")
    migrate(engine)
    return engine


def test_snapshot_copies_a_database_without_touching_the_original(local, tmp_path):
    before = (local / "jobme.db").read_bytes()
    snap = importer.snapshot_db(local / "jobme.db", tmp_path / "snap")
    assert (local / "jobme.db").read_bytes() == before
    with importer.open_local(snap).connect() as c:
        assert c.execute(text("select count(*) from job")).scalar() == 2


def test_copy_rows_keeps_ids_and_links_and_maps_docs_folders(local, tmp_path, cloud_engine):
    snap = importer.snapshot_db(local / "jobme.db", tmp_path / "snap")
    src = importer.open_local(snap)
    apps = local.parent
    counts = importer.copy_rows(src, cloud_engine, apps_dir=apps, cloud_apps_dir="/tmp/jobmecloud/applications")
    assert counts["job"] == 2 and counts["activitylog"] == 1 and counts["runjob"] == 1
    with Session(cloud_engine) as s:
        jobs = {j.id: j for j in s.exec(select(Job))}
        assert jobs[1].docs_folder == "/tmp/jobmecloud/applications/2026-01-01_Acme_Dev"
        assert jobs[2].docs_folder is None  # the folder no longer exists, so no dangling link
        assert jobs[2].repost_of_id == 1
        assert jobs[1].docs_status is None  # a column the old app never had
        assert s.get(RunJob, 1).job_id == 1


def test_copy_rows_twice_adds_nothing_the_second_time(local, tmp_path, cloud_engine):
    src = importer.open_local(importer.snapshot_db(local / 'jobme.db', tmp_path / 'snap'))
    kw = dict(apps_dir=local.parent, cloud_apps_dir="/x")
    importer.copy_rows(src, cloud_engine, **kw)
    again = importer.copy_rows(src, cloud_engine, **kw)
    assert again["job"] == 0 and again["activitylog"] == 0
    with Session(cloud_engine) as s:
        assert len(s.exec(select(Job)).all()) == 2


def test_dry_run_writes_nothing(local, tmp_path, cloud_engine):
    src = importer.open_local(importer.snapshot_db(local / 'jobme.db', tmp_path / 'snap'))
    counts = importer.copy_rows(src, cloud_engine, apps_dir=local.parent, cloud_apps_dir="/x", dry_run=True)
    assert counts["job"] == 2
    with Session(cloud_engine) as s:
        assert s.exec(select(Job)).all() == []


def test_cloud_settings_drop_the_local_folder_and_the_schedule():
    raw = {"applications_dir": "C:\\x", "match_cutoff": 80, "schedule": {"enabled": True, "times": ["16:06"]},
           "providers": [{"id": "claude", "kind": "anthropic", "label": "Claude"}]}
    s = importer.cloud_settings(raw)
    assert isinstance(s, Settings) and s.applications_dir is None
    assert s.match_cutoff == 80 and s.providers[0].id == "claude"
    assert s.schedule.enabled is False  # EventBridge has no schedule yet; the app sets it up from Settings


def test_plan_files_takes_profile_logs_and_only_the_job_folders(local):
    files = importer.plan_files(local, local.parent, ["2026-01-01_Acme_Dev"])
    keys = sorted(key for _, key in files)
    assert keys == ["applications/2026-01-01_Acme_Dev/cover.docx", "logs/run-1.log", "profile/resumes/base.docx"]


def test_upload_files_is_repeatable_and_puts_settings_in_the_workspace(local, tmp_path):
    s3 = boto3.client("s3")
    s3.create_bucket(Bucket="data")
    files = importer.plan_files(local, local.parent, ["2026-01-01_Acme_Dev"])
    first = importer.upload_files(s3, "data", "workspace", files, Settings(match_cutoff=80))
    second = importer.upload_files(s3, "data", "workspace", files, Settings(match_cutoff=80))
    assert first == 4 and second == 0  # three files and the settings, then nothing changed
    body = s3.get_object(Bucket="data", Key="workspace/settings.yaml")["Body"].read().decode()
    assert yaml.safe_load(body)["match_cutoff"] == 80
    assert s3.get_object(Bucket="data", Key="workspace/profile/resumes/base.docx")["Body"].read() == b"resume"


def test_api_key_moves_to_parameter_store_without_being_returned(monkeypatch):
    monkeypatch.setattr(importer, "_local_key", lambda name: "sk-secret" if name == "provider:claude" else None)
    moved = importer.copy_api_keys(["claude", "other"])
    assert moved == ["claude"]  # names only, never values
    value = boto3.client("ssm").get_parameter(Name="/jobmecloud/provider/claude", WithDecryption=True)
    assert value["Parameter"]["Value"] == "sk-secret"
    assert "sk-secret" not in json.dumps(moved)
