from datetime import datetime, timezone

from sqlmodel import Session

from docx_fixtures import make_resume_docx
from fakes import FakeProvider, add_job, deps, draft_json_for_fixture, get_status, ready_profile, set_status, setup_profile
from jobmecloud.db.models import Job
from jobmecloud.jobs.runlock import acquire_run_lock, release_run_lock
from jobmecloud.llm.errors import ProviderError


def _docs_ok(client, **job):
    d, engine = client.app.state.data_dir, client.app.state.engine
    ready_profile(d)
    job_id = add_job(engine, status="New", match_score=90, **job)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    client.app.state.run_deps = deps(p, page_counter=lambda data: 1)
    return job_id


def test_make_docs_route_and_open(client):
    d, engine = client.app.state.data_dir, client.app.state.engine
    ready_profile(d)
    job_id = add_job(engine, status="New", match_score=90)
    p = FakeProvider(replies=[draft_json_for_fixture(), '{"problems": []}'])
    client.app.state.run_deps = deps(p, page_counter=lambda data: 1)
    r = client.post(f"/api/jobs/{job_id}/docs", json={"feedback": None})
    assert r.status_code == 200 and r.json()["note"] == "1 page, same as your resume"
    opened = []
    client.app.state.open_path = opened.append
    assert client.post(f"/api/jobs/{job_id}/open", json={"what": "resume"}).status_code == 204
    assert opened[0].endswith("resume.docx")


def test_docs_route_errors(client):
    from datetime import datetime, timezone
    d, engine = client.app.state.data_dir, client.app.state.engine
    setup_profile(d)
    job_id = add_job(engine, status="New")
    client.app.state.run_deps = deps(FakeProvider())
    assert client.post(f"/api/jobs/{job_id}/docs", json={}).json()["detail"].startswith("Add your resume")
    assert client.post("/api/jobs/999/docs", json={}).status_code == 404
    assert client.post(f"/api/jobs/{job_id}/open", json={"what": "folder"}).status_code == 404
    acquire_run_lock(engine, datetime.now(timezone.utc))
    assert client.post(f"/api/jobs/{job_id}/docs", json={}).status_code == 409


def test_docs_lock_released_and_unknown_job_message(client):
    engine = client.app.state.engine
    setup_profile(client.app.state.data_dir)
    client.app.state.run_deps = deps(FakeProvider())
    r = client.post("/api/jobs/999/docs", json={})
    assert r.status_code == 404 and r.json()["detail"] == "No job with that id"
    job_id = add_job(engine)
    client.post(f"/api/jobs/{job_id}/docs", json={})  # setup error
    acquire_run_lock(engine, datetime.now(timezone.utc))  # would raise if still held
    release_run_lock(engine)


def test_feedback_blank_and_too_long(client):
    job_id = _docs_ok(client)
    long = client.post(f"/api/jobs/{job_id}/docs", json={"feedback": "x" * 2001})
    assert long.status_code == 400 and long.json()["detail"] == "Please keep the feedback under 2,000 characters."
    assert client.post(f"/api/jobs/{job_id}/docs", json={"feedback": "   "}).status_code == 200


def test_unexpected_error_is_502_and_saved_on_job(client):
    d, engine = client.app.state.data_dir, client.app.state.engine
    ready_profile(d)
    job_id = add_job(engine, status="New")
    client.app.state.run_deps = deps(FakeProvider(raises=ProviderError("boom secret")))
    r = client.post(f"/api/jobs/{job_id}/docs", json={})
    assert r.status_code == 502
    with Session(engine) as s:
        assert s.get(Job, job_id).docs_error == r.json()["detail"]
    assert get_status(engine, job_id) == "New"


def test_step_not_configured_is_400(client):
    engine = client.app.state.engine
    job_id = add_job(engine)
    r = client.post(f"/api/jobs/{job_id}/docs", json={})
    assert r.status_code == 400 and r.json()["detail"] == "Connect an AI first."


def test_file_in_use_is_409(client, monkeypatch):
    from jobmecloud.applydocs.output import FileInUseError
    job_id = _docs_ok(client)

    def boom(*a, **k):
        raise FileInUseError("resume.docx")
    monkeypatch.setattr("jobmecloud.api.routes_jobs.make_docs", boom)
    r = client.post(f"/api/jobs/{job_id}/docs", json={})
    assert r.status_code == 409 and r.json()["detail"] == "Close resume.docx in Word, then try again."


def test_as_is_route(client):
    d, engine = client.app.state.data_dir, client.app.state.engine
    ready_profile(d)
    resume_id = client.get("/api/resumes").json()["default_id"]
    job_id = add_job(engine, status="New")
    r = client.post(f"/api/jobs/{job_id}/as-is", json={"resume_id": resume_id})
    assert r.status_code == 200 and r.json()["note"] == "Using Main as-is"
    assert get_status(engine, job_id) == "Ready"
    assert client.post(f"/api/jobs/{job_id}/as-is", json={"resume_id": "nope"}).status_code == 404
    assert client.post("/api/jobs/999/as-is", json={"resume_id": resume_id}).json()["detail"] == "No job with that id"


def test_open_variants_and_refusals(client, tmp_path):
    job_id = _docs_ok(client)
    engine = client.app.state.engine
    opened = []
    client.app.state.open_path = opened.append
    assert client.post(f"/api/jobs/{job_id}/docs", json={}).status_code == 200
    for what, end in (("folder", None), ("cover_letter", "cover-letter.docx")):
        assert client.post(f"/api/jobs/{job_id}/open", json={"what": what}).status_code == 204
        if end:
            assert opened[-1].endswith(end)
    assert client.post(f"/api/jobs/{job_id}/open", json={"what": "../x"}).status_code == 422
    assert client.post("/api/jobs/999/open", json={"what": "folder"}).status_code == 404
    # a folder outside the applications folder is refused
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    with Session(engine) as s:
        job = s.get(Job, job_id)
        job.docs_folder = str(outside)
        s.add(job)
        s.commit()
    n = len(opened)
    r = client.post(f"/api/jobs/{job_id}/open", json={"what": "folder"})
    assert r.status_code == 404 and r.json()["detail"] == "No documents for this job yet."
    assert len(opened) == n


def test_open_missing_file_404(client):
    job_id = _docs_ok(client)
    client.app.state.open_path = lambda p: None
    folder = client.post(f"/api/jobs/{job_id}/docs", json={}).json()["folder"]
    from pathlib import Path
    (Path(folder) / "cover-letter.docx").unlink()
    assert client.post(f"/api/jobs/{job_id}/open", json={"what": "cover_letter"}).status_code == 404


def test_job_out_has_docs_fields(client):
    job_id = _docs_ok(client)
    client.post(f"/api/jobs/{job_id}/docs", json={})
    from jobmecloud.api.routes_runs import JobOut
    with Session(client.app.state.engine) as s:
        out = JobOut.model_validate(s.get(Job, job_id), from_attributes=True)
    assert out.docs_folder and out.docs_note and out.docs_error is None


def test_as_is_takes_the_run_lock(client):
    d, engine = client.app.state.data_dir, client.app.state.engine
    ready_profile(d)
    resume_id = client.get("/api/resumes").json()["default_id"]
    job_id = add_job(engine, status="New")
    acquire_run_lock(engine, datetime.now(timezone.utc))
    r = client.post(f"/api/jobs/{job_id}/as-is", json={"resume_id": resume_id})
    assert r.status_code == 409 and r.json()["detail"] == "A run is already in progress."
    release_run_lock(engine)
    assert client.post(f"/api/jobs/{job_id}/as-is", json={"resume_id": "nope"}).status_code == 404
    assert client.post(f"/api/jobs/{job_id}/as-is", json={"resume_id": resume_id}).status_code == 200
    acquire_run_lock(engine, datetime.now(timezone.utc))  # would raise if still held
    release_run_lock(engine)


def test_missing_docx_with_mapping_is_400_with_friendly_copy(client):
    from jobmecloud.resumes.store import default_entry, file_path
    job_id = _docs_ok(client)
    d = client.app.state.data_dir
    file_path(d, default_entry(d)).unlink()
    r = client.post(f"/api/jobs/{job_id}/docs", json={})
    assert r.status_code == 400
    assert r.json()["detail"] == "That resume's file is missing. Add it again in Settings > Your resume."
