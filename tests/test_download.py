import boto3
import pytest
from fakes import add_job, ready_profile
from fastapi.testclient import TestClient
from sqlmodel import Session

from jobmecloud.api.app import create_app
from jobmecloud.config.settings import load_settings
from jobmecloud.db.models import Job


@pytest.fixture
def cloud_client(data_dir, monkeypatch):
    boto3.client("s3").create_bucket(Bucket="jobmecloud-dl-test")
    monkeypatch.setenv("JOBMECLOUD_BUCKET", "jobmecloud-dl-test")
    monkeypatch.setenv("JOBMECLOUD_PREFIX", "ws")
    with TestClient(create_app(data_dir)) as c:
        yield c


def make_docs_folder(client, name="Acme"):
    d = client.app.state.data_dir
    ready_profile(d)
    job_id = add_job(client.app.state.engine, status="New", match_score=90)
    folder = load_settings(d).applications_path(d) / name
    folder.mkdir(parents=True)
    (folder / "resume.docx").write_bytes(b"resume")
    with Session(client.app.state.engine) as s:
        job = s.get(Job, job_id)
        job.docs_folder = str(folder)
        s.add(job)
        s.commit()
    return job_id


def test_download_returns_a_short_lived_link_to_the_file(cloud_client):
    job_id = make_docs_folder(cloud_client)
    r = cloud_client.post(f"/api/jobs/{job_id}/download", json={"what": "resume"})
    assert r.status_code == 200
    body = r.json()
    assert "ws/applications/Acme/resume.docx" in body["url"].replace("%2F", "/") and "Expires=" in body["url"]
    assert body["filename"] == "resume.docx"


def test_download_missing_file_is_404(cloud_client):
    job_id = make_docs_folder(cloud_client)
    r = cloud_client.post(f"/api/jobs/{job_id}/download", json={"what": "cover_letter"})
    assert r.status_code == 404 and r.json()["detail"] == "No documents for this job yet."


def test_download_refuses_folders_outside_the_applications_folder(cloud_client, tmp_path):
    job_id = make_docs_folder(cloud_client)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "resume.docx").write_bytes(b"x")
    with Session(cloud_client.app.state.engine) as s:
        job = s.get(Job, job_id)
        job.docs_folder = str(outside)
        s.add(job)
        s.commit()
    assert cloud_client.post(f"/api/jobs/{job_id}/download", json={"what": "resume"}).status_code == 404


def test_download_is_unavailable_without_a_workspace(client):
    job_id = make_docs_folder(client)
    r = client.post(f"/api/jobs/{job_id}/download", json={"what": "resume"})
    assert r.status_code == 400
