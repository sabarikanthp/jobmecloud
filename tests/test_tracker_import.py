import io
from datetime import date, datetime

import openpyxl
from sqlmodel import Session, select

from jobmecloud.db.models import Job
from jobmecloud.importers.tracker import (
    map_status,
    parse_date,
    read_tracker,
    rows_to_jobs,
    suggest_mapping,
)
from jobmecloud.jobs.status import STATUSES


def test_excel_csv_with_bom_cp1252_and_blank_rows():
    data = "\r\n".join(["", "Company,Role,Status,Date Applied,Notes", "Café Co,Engineer,Interview,3/14/2026,",
                        ",,,,", "Beta LLC,Analyst,weird,not a date,x"]).encode("cp1252")
    sheet = read_tracker("jobs.csv", data)[0]
    mapping = suggest_mapping(sheet.columns)
    assert mapping["employer"] == "Company" and mapping["applied_date"] == "Date Applied"
    jobs, skipped = rows_to_jobs(sheet, mapping, datetime(2026, 11, 11))
    assert [j.status for j in jobs] == ["Interviewing", "New"] and skipped == 0
    assert jobs[0].applied_at == datetime(2026, 3, 14) and "Applied date in file: not a date" in jobs[1].notes
    assert jobs[0].employer == "Café Co" and jobs[0].origin == "import"
    assert jobs[1].first_seen_at == datetime(2026, 11, 11)


def test_csv_with_bom_and_sheet_name():
    sheet = read_tracker("My Jobs.csv", "﻿Company,Title\nAcme,Eng\n".encode("utf-8"))[0]
    assert sheet.name == "My Jobs" and sheet.columns == ["Company", "Title"]


def test_xlsx_sheets():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "2025"
    ws.append(["Company", "Title", "Applied"])
    ws.append(["Acme", "Eng", datetime(2025, 5, 6)])
    ws.append([None, None, None])
    ws2 = wb.create_sheet("2026")
    ws2.append(["Employer", "Role"])
    ws2.append(["Beta", "PM"])
    buf = io.BytesIO()
    wb.save(buf)
    sheets = read_tracker("t.xlsx", buf.getvalue())
    assert [s.name for s in sheets] == ["2025", "2026"]
    assert len(sheets[0].rows) == 1
    jobs, _ = rows_to_jobs(sheets[0], suggest_mapping(sheets[0].columns), datetime(2026, 1, 1))
    assert jobs[0].applied_at == datetime(2025, 5, 6)


def test_rejects_other_file_types():
    import pytest
    from jobmecloud.importers.text import ImportFileError

    with pytest.raises(ImportFileError, match=r"JobMe can read .xlsx and .csv files."):
        read_tracker("t.pdf", b"x")


def test_mapping_does_not_reuse_columns():
    m = suggest_mapping(["Company", "Job Title", "Date Applied", "Applied URL"])
    assert m["applied_date"] == "Date Applied"
    assert m["url"] == "Applied URL"
    assert m["location"] is None


def test_status_and_dates():
    assert map_status("applied") == "Applied" and map_status("Phone Screen") == "Interviewing"
    assert map_status("Not Selected") == "Rejected" and map_status(None) == "New"
    assert map_status("pass") == "Skipped" and map_status("expired") == "Closed"
    assert "Closed" in STATUSES
    assert parse_date("2026-03-14") == date(2026, 3, 14)
    assert parse_date("3/14/26") == date(2026, 3, 14)
    assert parse_date("14-Mar-2026") == date(2026, 3, 14)
    assert parse_date("Mar 14, 2026") == date(2026, 3, 14)
    assert parse_date(datetime(2026, 3, 14, 5)) == date(2026, 3, 14)
    assert parse_date("nope") is None and parse_date(None) is None


def test_skipped_rows_and_skipped_status():
    sheet = read_tracker("a.csv", b"Company,Title,Status\nAcme,,New\nBeta,PM,pass\n")[0]
    jobs, skipped = rows_to_jobs(sheet, suggest_mapping(sheet.columns), datetime(2026, 1, 1))
    assert skipped == 1 and len(jobs) == 1
    assert (jobs[0].skip_reason, jobs[0].skip_note) == ("Other", "Imported")


def test_sample_rows_are_strings(client):
    up = client.post("/api/import/tracker/preview", files={"file": ("t.csv", b"Company,Title\nAcme,Eng\n")}).json()
    assert up["sheets"][0]["sample_rows"] == [["Acme", "Eng"]]


def test_commit_twice_imports_nothing_new(client):
    up = client.post("/api/import/tracker/preview", files={"file": ("t.csv", b"Company,Title\nAcme,Eng\nAcme,Eng\nBeta,PM\n")}).json()
    body = {"upload_id": up["upload_id"], "sheet": up["sheets"][0]["name"], "mapping": up["sheets"][0]["suggested_mapping"]}
    first = client.post("/api/import/tracker/commit", json=body).json()
    assert (first["imported"], first["duplicates"]) == (2, 1)
    up2 = client.post("/api/import/tracker/preview", files={"file": ("t.csv", b"Company,Title\nAcme,Eng\nBeta,PM\n")}).json()
    second = client.post("/api/import/tracker/commit", json={**body, "upload_id": up2["upload_id"]}).json()
    assert second == {"imported": 0, "duplicates": 2, "skipped": 0, "message": "Imported 0 jobs. 2 were already in JobMe."}
    with Session(client.app.state.engine) as s:
        assert len(s.exec(select(Job)).all()) == 2


def test_message_singular_forms(client):
    up = client.post("/api/import/tracker/preview", files={"file": ("t.csv", b"Company,Title\nAcme,Eng\nAcme,Eng\n,PM\n")}).json()
    body = {"upload_id": up["upload_id"], "sheet": up["sheets"][0]["name"], "mapping": up["sheets"][0]["suggested_mapping"]}
    r = client.post("/api/import/tracker/commit", json=body).json()
    assert r["message"] == ("Imported 1 job. 1 was already in JobMe. "
                            "1 row had no employer or title and was left out.")


def test_commit_errors(client):
    r = client.post("/api/import/tracker/commit", json={"upload_id": "nope", "sheet": "x", "mapping": {}})
    assert r.status_code == 404 and r.json()["detail"] == "That upload expired. Please upload the file again."
    up = client.post("/api/import/tracker/preview", files={"file": ("t.csv", b"Company,Title\nAcme,Eng\n")}).json()
    sheet = up["sheets"][0]["name"]
    r = client.post("/api/import/tracker/commit", json={"upload_id": up["upload_id"], "sheet": sheet, "mapping": {"employer": "Company"}})
    assert r.status_code == 400 and r.json()["detail"] == "Choose which columns hold the employer and the job title."
    r = client.post("/api/import/tracker/commit", json={"upload_id": up["upload_id"], "sheet": sheet, "mapping": {"employer": "Company", "title": "Nope"}})
    assert r.status_code == 400 and r.json()["detail"] == "That column isn't in the sheet: Nope"
    r = client.post("/api/import/tracker/preview", files={"file": ("t.pdf", b"x")})
    assert r.status_code == 400 and r.json()["detail"] == "JobMe can read .xlsx and .csv files."


def test_keeps_only_five_uploads(client):
    ids = [client.post("/api/import/tracker/preview", files={"file": ("t.csv", b"Company,Title\nA,B\n")}).json()["upload_id"] for _ in range(6)]
    assert list(client.app.state.tracker_uploads) == ids[1:]


def test_unreadable_xlsx_and_unknown_sheet(client):
    r = client.post("/api/import/tracker/preview", files={"file": ("t.xlsx", b"not a zip")})
    assert r.status_code == 400
    assert r.json()["detail"] == "JobMe couldn't read that spreadsheet. Is it a valid .xlsx or .csv file?"
    up = client.post("/api/import/tracker/preview", files={"file": ("t.csv", b"Company,Title\nAcme,Eng\n")}).json()
    r = client.post("/api/import/tracker/commit", json={
        "upload_id": up["upload_id"], "sheet": "No such sheet",
        "mapping": {"employer": "Company", "title": "Title"}})
    assert r.status_code == 404
    assert r.json()["detail"] == "That upload expired. Please upload the file again."


def test_imported_dates_round_trip_through_db(client):
    data = b"Company,Title,Date Applied\nAcme,Eng,3/14/2026\nBeta,PM,\n"
    up = client.post("/api/import/tracker/preview", files={"file": ("t.csv", data)}).json()
    s = up["sheets"][0]
    client.post("/api/import/tracker/commit", json={
        "upload_id": up["upload_id"], "sheet": s["name"], "mapping": s["suggested_mapping"]})
    with Session(client.app.state.engine) as session:
        acme = session.exec(select(Job).where(Job.employer == "Acme")).one()
        beta = session.exec(select(Job).where(Job.employer == "Beta")).one()
    assert acme.applied_at.date() == date(2026, 3, 14)
    assert (acme.applied_at.hour, acme.applied_at.minute) == (0, 0)
    assert acme.first_seen_at.date() == date(2026, 3, 14)
    assert beta.applied_at is None
    assert abs((datetime.now().date() - beta.first_seen_at.date()).days) <= 1


def _commit(client, data):
    up = client.post("/api/import/tracker/preview", files={"file": ("t.csv", data)}).json()
    body = {"upload_id": up["upload_id"], "sheet": up["sheets"][0]["name"], "mapping": up["sheets"][0]["suggested_mapping"]}
    return client.post("/api/import/tracker/commit", json=body).json()


def test_rows_over_limit_are_reported(client, monkeypatch):
    monkeypatch.setattr("jobmecloud.importers.tracker.MAX_ROWS", 2)
    r = _commit(client, b"Company,Title\nA,B\nC,D\nE,F\nG,H\n")
    assert r["imported"] == 2
    assert r["message"] == "Imported 2 jobs. 2 rows over the 5,000-row limit were left out."
    r = _commit(client, b"Company,Title\nI,J\nK,L\nM,N\n")
    assert r["message"].endswith(" 1 row over the 5,000-row limit was left out.")


def test_corrupt_sheet_while_iterating_is_unreadable(client, monkeypatch):
    import openpyxl.worksheet._read_only as ro

    def boom(self, *a, **k):
        raise ValueError("corrupt")

    monkeypatch.setattr(ro.ReadOnlyWorksheet, "iter_rows", boom)
    buf = io.BytesIO()
    wb = openpyxl.Workbook()
    wb.active.append(["Company", "Title"])
    wb.save(buf)
    r = client.post("/api/import/tracker/preview", files={"file": ("t.xlsx", buf.getvalue())})
    assert r.status_code == 400
    assert r.json()["detail"] == "JobMe couldn't read that spreadsheet. Is it a valid .xlsx or .csv file?"


def test_import_logs_one_imported_row_per_new_job_and_none_for_duplicates(client):
    from jobmecloud.db.models import ActivityLog
    csv = b"Company,Title\nAcme,Eng\nAcme,Eng\nBeta,PM\n"
    up = client.post("/api/import/tracker/preview", files={"file": ("t.csv", csv)}).json()
    body = {"upload_id": up["upload_id"], "sheet": up["sheets"][0]["name"], "mapping": up["sheets"][0]["suggested_mapping"]}
    client.post("/api/import/tracker/commit", json=body)
    up2 = client.post("/api/import/tracker/preview", files={"file": ("t.csv", csv)}).json()
    client.post("/api/import/tracker/commit", json={**body, "upload_id": up2["upload_id"]})
    with Session(client.app.state.engine) as s:
        jobs = s.exec(select(Job)).all()
        rows = s.exec(select(ActivityLog)).all()
        assert len(jobs) == 2 and len(rows) == 2
        assert {r.job_id for r in rows} == {j.id for j in jobs}
        assert all((r.action, r.actor, r.entity_type) == ("imported", "user", "job") for r in rows)
        assert {r.to_value for r in rows} == {j.status for j in jobs}
