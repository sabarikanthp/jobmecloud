from test_batch import RowsPerCommit

from jobmecloud.db.batch import MAX_ROWS_PER_TX


def _letters(i):
    """A distinct all-letter name: employer names are compared without digits."""
    return "Firm" + "".join(chr(97 + (i // 26**k) % 26) for k in range(3))


def _upload(client, rows):
    data = ("Company,Title\n" + "".join(f"Co{i},Engineer\n" for i in range(rows))).encode()
    up = client.post("/api/import/tracker/preview", files={"file": ("t.csv", data)}).json()
    sheet = up["sheets"][0]
    return {"upload_id": up["upload_id"], "sheet": sheet["name"], "mapping": sheet["suggested_mapping"]}


def test_import_of_3500_rows_commits_in_batches(client):
    body = _upload(client, 3500)
    with RowsPerCommit() as rows:
        result = client.post("/api/import/tracker/commit", json=body).json()
    assert result["imported"] == 3500
    assert 0 < rows.largest <= MAX_ROWS_PER_TX


def test_watchlist_import_of_3500_rows_commits_in_batches(client):
    data = ("Employer,Priority\n" + "".join(f"{_letters(i)},P1\n" for i in range(3500))).encode()
    up = client.post("/api/import/watchlist/preview", files={"file": ("w.csv", data)}).json()
    sheet = up["sheets"][0]
    body = {"upload_id": up["upload_id"], "sheet": sheet["name"], "mapping": sheet["suggested_mapping"]}
    with RowsPerCommit() as rows:
        result = client.post("/api/import/watchlist/commit", json=body).json()
    assert result.get("imported") == 3500, result
    assert rows.largest <= MAX_ROWS_PER_TX


def test_sheet_import_of_3500_job_rows_commits_in_batches(session):
    from datetime import datetime, timezone

    from jobmecloud.importers.sheet_import import SheetImportIn, run_import
    from jobmecloud.importers.tracker import Sheet

    sheet = Sheet("Jobs", ["Employer", "Role"], [[f"Co{i}", "Engineer"] for i in range(3500)])
    body = SheetImportIn(upload_id="u", sheet="Jobs", kind="jobs",
                         mapping={"employer": "Employer", "title": "Role"})
    with RowsPerCommit() as rows:
        report = run_import(session, sheet, body, now=datetime(2026, 11, 12, tzinfo=timezone.utc))
        session.commit()
    assert report["counts"]["new"] == 3500
    assert 0 < rows.largest <= MAX_ROWS_PER_TX
