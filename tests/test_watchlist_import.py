from jobmecloud.importers.tracker import read_tracker
from jobmecloud.importers.watchlist import (
    map_day,
    map_priority,
    rows_to_employers,
    suggest_watchlist_mapping,
)

CSV = (
    "Search Rotation,Employer,Priority,Last Verified,Audit Result / Link\n"
    "Monday - Springfield,Northwind Labs,P1,2026-01-01,see https://northwind.example/careers ok\n"
    "Thu,Contoso Health,Conditional,,checked\n"
    "Anytime,Fabrikam,,,\n"
    ",,P2,,\n"
)


def test_suggested_mapping_and_rows():
    sheet = read_tracker("w.csv", CSV.encode())[0]
    mapping = suggest_watchlist_mapping(sheet.columns)
    assert mapping == {
        "name": "Employer", "priority": "Priority",
        "rotation_day": "Search Rotation", "careers_url": "Audit Result / Link",
    }
    employers, skipped = rows_to_employers(sheet, mapping)
    assert skipped == 1
    assert [(e.name, e.priority, e.rotation_day, e.careers_url) for e in employers] == [
        ("Northwind Labs", 1, "mon", "https://northwind.example/careers"),
        ("Contoso Health", 3, "thu", None),
        ("Fabrikam", 2, None, None),
    ]


def test_priority_and_day_values():
    assert [map_priority(v) for v in ["P1", "high", "1", "P2", "Medium", "p3", "Low", "Conditional", "", "maybe"]] == [
        1, 1, 1, 2, 2, 3, 3, 3, 2, 2]
    assert [map_day(v) for v in ["Monday – Portland", "tue", "Wednesday", "weekly", "", "Sun."]] == [
        "mon", "tue", "wed", None, None, "sun"]


def _preview(client, data: bytes):
    return client.post("/api/import/watchlist/preview", files={"file": ("w.csv", data)}).json()


def test_commit_skips_existing_and_repeated_names(client):
    client.post("/api/watchlist", json={"name": "Contoso Health", "priority": 1})
    up = _preview(client, b"Employer,Priority\nNorthwind Labs Inc.,P1\nnorthwind labs,P2\nContoso Health,P2\n,P1\n")
    sheet = up["sheets"][0]
    assert sheet["suggested_mapping"]["name"] == "Employer"
    r = client.post("/api/import/watchlist/commit", json={
        "upload_id": up["upload_id"], "sheet": sheet["name"], "mapping": sheet["suggested_mapping"]}).json()
    assert r == {"imported": 1, "duplicates": 2, "skipped": 1,
                 "message": "Added 1 employer. 2 were already on your list. 1 row had no employer name and was left out."}
    names = [e["name"] for e in client.get("/api/watchlist").json()]
    assert sorted(names) == ["Contoso Health", "Northwind Labs Inc."]


def test_commit_errors(client):
    r = client.post("/api/import/watchlist/commit", json={"upload_id": "nope", "sheet": "x", "mapping": {}})
    assert r.status_code == 404
    up = _preview(client, b"Employer,Priority\nA,P1\n")
    sheet = up["sheets"][0]["name"]
    r = client.post("/api/import/watchlist/commit", json={"upload_id": up["upload_id"], "sheet": sheet, "mapping": {}})
    assert r.status_code == 400 and r.json()["detail"] == "Choose which column holds the employer's name."
