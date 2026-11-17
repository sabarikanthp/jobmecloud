from datetime import datetime, timezone

import boto3
from fakes import FakeProvider, add_job, deps, draft_json_for_fixture, ready_profile
from sqlmodel import Session

from jobmecloud.db.models import Job
from jobmecloud.handlers import docs_worker
from jobmecloud.jobs.runlock import acquire_run_lock, run_lock_held


class Ctx:
    def get_remaining_time_in_millis(self):
        return 300_000


def job_of(engine, job_id):
    with Session(engine) as s:
        return s.get(Job, job_id)


def test_docs_worker_marks_ready_and_uploads_files(data_dir, engine, monkeypatch):
    boto3.client("s3").create_bucket(Bucket="jobmecloud-docs-test")
    monkeypatch.setenv("JOBMECLOUD_BUCKET", "jobmecloud-docs-test")
    monkeypatch.setenv("JOBMECLOUD_PREFIX", "ws")
    ready_profile(data_dir)
    job_id = add_job(engine, status="New", match_score=90)
    provider = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    monkeypatch.setattr(docs_worker, "build_deps", lambda context: deps(provider, page_counter=lambda data: 1))

    docs_worker.handler({"task": "docs", "job_id": job_id, "options": {"feedback": None}}, Ctx())

    job = job_of(engine, job_id)
    assert job.docs_status == "ready" and job.docs_error is None and job.docs_note
    listing = boto3.client("s3").list_objects_v2(Bucket="jobmecloud-docs-test", Prefix="ws/applications")
    keys = [o["Key"] for o in listing["Contents"]]
    assert any(k.endswith("resume.docx") for k in keys) and any(k.endswith("cover-letter.docx") for k in keys)
    assert not run_lock_held(engine, datetime.now(timezone.utc))


def test_docs_worker_error_message_has_no_secrets(data_dir, engine, monkeypatch):
    ready_profile(data_dir)
    job_id = add_job(engine, status="New", match_score=90)
    secret = "sk-ant-SECRET-KEY-123"
    provider = FakeProvider(replies=[RuntimeError(f"request failed for {secret}")])
    monkeypatch.setattr(docs_worker, "build_deps", lambda context: deps(provider))

    docs_worker.handler({"task": "docs", "job_id": job_id, "options": {}}, Ctx())

    job = job_of(engine, job_id)
    assert job.docs_status == "error" and job.docs_error
    assert secret not in job.docs_error
    assert not run_lock_held(engine, datetime.now(timezone.utc))


def test_docs_worker_reports_a_run_in_progress(data_dir, engine, monkeypatch):
    ready_profile(data_dir)
    job_id = add_job(engine, status="New", match_score=90)
    monkeypatch.setattr(docs_worker, "build_deps", lambda context: deps(FakeProvider()))
    acquire_run_lock(engine, datetime.now(timezone.utc))

    docs_worker.handler({"task": "docs", "job_id": job_id, "options": {}}, Ctx())

    job = job_of(engine, job_id)
    assert job.docs_status == "error" and job.docs_error == "A run is already in progress."


def test_docs_worker_starts_from_the_resume_it_was_told_to_use(data_dir, engine, monkeypatch):
    from docx_fixtures import FIXTURE_READING, make_resume_docx
    from fakes import NOW, fixture_mapping
    from jobmecloud.resumes.store import add_resume
    boto3.client("s3").create_bucket(Bucket="jobmecloud-docs-test2")
    monkeypatch.setenv("JOBMECLOUD_BUCKET", "jobmecloud-docs-test2")
    monkeypatch.setenv("JOBMECLOUD_PREFIX", "ws")
    ready_profile(data_dir)
    other = FIXTURE_READING.model_copy(update={"summary": "THE OTHER RESUME SUMMARY"})
    chosen = add_resume(data_dir, name="Other", filename="o.docx", data=make_resume_docx(), reading=other,
                        mapping=fixture_mapping(), make_default=False, now=NOW)
    job_id = add_job(engine, status="New", match_score=90)
    provider = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    monkeypatch.setattr(docs_worker, "build_deps", lambda context: deps(provider, page_counter=lambda data: 1))
    docs_worker.handler({"task": "docs", "job_id": job_id, "options": {"resume_id": chosen.id}}, Ctx())
    assert job_of(engine, job_id).docs_status == "ready"
    assert "THE OTHER RESUME SUMMARY" in provider.calls[0]["messages"][0]["content"]
