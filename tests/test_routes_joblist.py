import os
import time
from datetime import date, datetime, timezone

import pytest
from fakes import add_job
from sqlalchemy import event

from jobmecloud.jobs import views
from jobmecloud.jobs.tracking import utc_date


def utc(y, m, d, h=0):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


@pytest.fixture
def five(client):
    e = client.app.state.engine
    return {
        "a": add_job(e, origin="import", employer="Northwind Labs", title="Data Engineer", status="New", match_score=90,
                     source="boards.greenhouse.io", first_seen_at=utc(2026, 3, 1, 23), flags=["Relocation"]),
        "b": add_job(e, origin="import", employer="Contoso Health", title="Analyst", status="Applied", match_score=70,
                     source="www.linkedin.com", first_seen_at=utc(2026, 3, 5), applied_at=utc(2026, 3, 6),
                     apply_url="https://www.linkedin.com/jobs/view/1"),
        "c": add_job(e, origin="import", employer="adatum", title="Platform Engineer", status="Ready", match_score=None,
                     source="jobs.lever.co", first_seen_at=utc(2026, 3, 10), flags=["Visa sponsorship?"]),
        "d": add_job(e, origin="import", employer="Zeta Corp", title="Data Analyst", status="Rejected", match_score=50,
                     source="boards.greenhouse.io", first_seen_at=utc(2026, 3, 12),
                     applied_at=utc(2026, 3, 8), apply_url="https://notlinkedin.com/x"),
        "e": add_job(e, origin="import", employer="Beta Inc", title="Engineer", status="Applied", match_score=80,
                     source="jobs.lever.co", first_seen_at=utc(2026, 3, 15), applied_at=utc(2026, 3, 2)),
    }


def ids_of(client, qs=""):
    r = client.get("/api/jobs" + qs)
    assert r.status_code == 200, r.text
    return [x["id"] for x in r.json()["rows"]]


def order(f, letters):
    return [f[k] for k in letters]


def test_default_order_and_row_shape(client, five):
    r = client.get("/api/jobs").json()
    assert r["total"] == 5
    assert [x["id"] for x in r["rows"]] == order(five, "edcba")
    row = {x["id"]: x for x in r["rows"]}[five["b"]]
    assert row["first_seen_date"] == "2026-03-05" and row["applied_date"] == "2026-03-06"
    assert row["linkedin"] is True and row["docs_ready"] is False
    assert row["has_open_followup"] is False and row["next_followup_due"] is None


def test_filters(client, five):
    f = five
    assert set(ids_of(client, "?status=Applied")) == {f["b"], f["e"]}
    assert set(ids_of(client, "?status=Applied&status=New")) == {f["a"], f["b"], f["e"]}
    assert set(ids_of(client, "?min_score=80")) == {f["a"], f["e"]}
    assert set(ids_of(client, "?q=ANALYST")) == {f["b"], f["d"]}
    assert set(ids_of(client, "?q=contoso")) == {f["b"]}
    assert set(ids_of(client, "?source=jobs.lever.co")) == {f["c"], f["e"]}
    assert set(ids_of(client, "?from=2026-03-05&to=2026-03-12")) == {f["b"], f["c"], f["d"]}
    assert set(ids_of(client, "?to=2026-03-01")) == {f["a"]}
    assert set(ids_of(client, "?flag=visa")) == {f["c"]}
    assert set(ids_of(client, "?status=Applied&source=jobs.lever.co&min_score=75")) == {f["e"]}


def test_has_followup_filter(client, five):
    f = five
    client.post("/api/followups", json={"type": "Other", "due_date": "2026-12-01", "job_id": f["a"]})
    client.post("/api/followups", json={"type": "Other", "due_date": "2026-11-20", "job_id": f["a"]})
    done = client.post("/api/followups", json={"type": "Other", "due_date": "2026-12-01", "job_id": f["b"]}).json()
    client.post(f"/api/followups/{done['id']}/done")
    assert ids_of(client, "?has_followup=true") == [f["a"]]
    assert set(ids_of(client, "?has_followup=false")) == {f["b"], f["c"], f["d"], f["e"]}
    row = client.get("/api/jobs?has_followup=true").json()["rows"][0]
    assert row["has_open_followup"] is True and row["next_followup_due"] == "2026-11-20"


def test_sorts_nulls_last(client, five):
    f = five
    assert ids_of(client, "?sort=match") == order(f, "aebdc")
    assert ids_of(client, "?sort=match&dir=asc") == order(f, "dbeac")
    assert ids_of(client, "?sort=employer") == order(f, "cebad")
    assert ids_of(client, "?sort=employer&dir=desc") == order(f, "dabec")
    assert ids_of(client, "?sort=applied") == order(f, "dbeca")
    assert ids_of(client, "?sort=applied&dir=asc") == order(f, "ebdac")
    assert ids_of(client, "?sort=status&dir=asc") == order(f, "beacd")
    assert ids_of(client, "?sort=first_seen&dir=asc") == order(f, "abcde")


def test_paging(client, five):
    f = five
    r = client.get("/api/jobs?limit=2&offset=1").json()
    assert r["total"] == 5 and [x["id"] for x in r["rows"]] == [f["d"], f["c"]]
    assert client.get("/api/jobs?limit=201").status_code == 422


@pytest.mark.parametrize("qs", ["sort=bogus", "dir=up", "from=nope", "to=2026-13-01", "min_score=101"])
def test_bad_params_422(client, five, qs):
    assert client.get("/api/jobs?" + qs).status_code == 422


def test_facets(client, five):
    r = client.get("/api/jobs/facets").json()
    assert r["sources"] == ["boards.greenhouse.io", "jobs.lever.co", "www.linkedin.com"]
    assert r["statuses"] == {"New": 1, "Applied": 2, "Ready": 1, "Rejected": 1}


def test_applied_date_is_utc_date(client):
    jid = add_job(client.app.state.engine, applied_at=utc(2026, 3, 14), status="Applied")
    assert client.get(f"/api/jobs/{jid}").json()["applied_date"] == "2026-03-14"
    if hasattr(time, "tzset"):
        old = os.environ.get("TZ")
        os.environ["TZ"] = "America/Los_Angeles"
        time.tzset()
        try:
            assert client.get(f"/api/jobs/{jid}").json()["applied_date"] == "2026-03-14"
            assert client.get("/api/jobs").json()["rows"][0]["applied_date"] == "2026-03-14"
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()
    # SQLite hands datetimes back naive; the helper treats them as UTC.
    assert utc_date(datetime(2026, 3, 14)) == date(2026, 3, 14)
    assert views.iso(date(2026, 3, 14)) == "2026-03-14" and views.iso(None) is None


def test_linkedin_flag(client):
    e = client.app.state.engine
    ids = [add_job(e, apply_url=u) for u in (
        "https://www.linkedin.com/jobs/view/1", "https://notlinkedin.com/x",
        "https://linkedin.com/x", None, "http://[bad")]
    got = {x["id"]: x["linkedin"] for x in client.get("/api/jobs").json()["rows"]}
    assert [got[i] for i in ids] == [True, False, True, False, False]


def test_detail_404(client):
    r = client.get("/api/jobs/999")
    assert (r.status_code, r.json()["detail"]) == (404, "No job with that id")


def test_detail_from_real_actions(client, five):
    jid = five["a"]
    assert client.post(f"/api/jobs/{jid}/status", json={"status": "Applied"}).status_code == 200
    c = client.post("/api/contacts", json={"name": "Jordan Example", "job_id": jid}).json()
    fu = client.post("/api/followups", json={"type": "Other", "due_date": "2026-12-01", "job_id": jid}).json()
    client.post(f"/api/jobs/{jid}/interviews", json={"date": "2026-12-02", "stage": "Phone"})
    d = client.get(f"/api/jobs/{jid}").json()
    assert d["status"] == "Interviewing"
    assert d["allowed_next"] == ["Offer", "Rejected", "Withdrawn"]
    assert d["description"] == "Build data pipelines." and d["flags"] == ["Relocation"]
    assert [x["id"] for x in d["contacts"]] == [c["id"]]
    assert d["contacts"][0]["name"] == "Jordan Example"
    assert fu["id"] in [x["id"] for x in d["followups"]]
    assert all(x["bucket"] for x in d["followups"])
    assert [i["stage"] for i in d["interviews"]] == ["Phone"]
    assert d["has_open_followup"] is True
    actions = [t["action"] for t in d["timeline"]]
    assert "contact_added" in actions and "interview_added" in actions
    stamps = [t["at"] for t in d["timeline"]]
    assert stamps == sorted(stamps, reverse=True)
    assert set(d["timeline"][0]) == {"at", "actor", "entity_type", "action", "from_value", "to_value", "note"}
    assert d["timeline"][-1]["entity_type"] == "job"


def test_list_query_count(client, five):
    engine = client.app.state.engine
    for j in five.values():
        client.post("/api/followups", json={"type": "Other", "due_date": "2026-12-01", "job_id": j})
    seen = []

    def count(conn, cursor, statement, *a):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", count)
    try:
        assert client.get("/api/jobs").status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(seen) <= 3


@pytest.fixture
def pacific(monkeypatch):
    """Pin the local zone to UTC-8 so these tests do not depend on the machine's time zone."""
    from datetime import timedelta
    from jobmecloud.jobs import tracking
    monkeypatch.setattr(tracking, "_local_tz", lambda: timezone(timedelta(hours=-8)))


def test_found_date_is_local_for_real_instants_and_utc_for_imports(client, pacific):
    e = client.app.state.engine
    real = add_job(e, origin="scout", first_seen_at=utc(2026, 3, 2, 3))   # 2026-03-01 19:00 local
    imported = add_job(e, origin="import", first_seen_at=utc(2026, 3, 2))  # calendar day, never shifted
    got = {x["id"]: x["first_seen_date"] for x in client.get("/api/jobs").json()["rows"]}
    assert got == {real: "2026-03-01", imported: "2026-03-02"}
    assert client.get(f"/api/jobs/{real}").json()["first_seen_date"] == "2026-03-01"
    assert client.get(f"/api/jobs/{imported}").json()["first_seen_date"] == "2026-03-02"


def test_found_between_matches_the_displayed_date(client, pacific):
    e = client.app.state.engine
    real = add_job(e, origin="scout", first_seen_at=utc(2026, 3, 2, 3))   # shown 03-01
    imported = add_job(e, origin="import", first_seen_at=utc(2026, 3, 2))  # shown 03-02
    late = add_job(e, origin="manual", first_seen_at=utc(2026, 3, 2, 9))  # 01:00 local, shown 03-02
    assert set(ids_of(client, "?from=2026-03-01&to=2026-03-01")) == {real}
    assert set(ids_of(client, "?from=2026-03-02&to=2026-03-02")) == {imported, late}
    assert set(ids_of(client, "?from=2026-03-02")) == {imported, late}
    assert set(ids_of(client, "?to=2026-03-01")) == {real}


def test_local_helpers(pacific):
    from jobmecloud.jobs.tracking import local_date, local_midnight
    assert local_date(utc(2026, 3, 2, 7, )) == date(2026, 3, 1)
    assert local_date(datetime(2026, 3, 2, 8)) == date(2026, 3, 2)  # naive means UTC
    assert local_date(None) is None
    assert local_midnight(date(2026, 3, 1)) == utc(2026, 3, 1, 8)


def _field(client, **body):
    r = client.post("/api/job-fields", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _set(client, jid, fid, value):
    r = client.put(f"/api/jobs/{jid}/fields", json={"values": {str(fid): value}})
    assert r.status_code == 200, r.text


def test_rows_include_custom_values_only_for_requested_fields(client, five):
    pay = _field(client, name="Pay", type="number")
    note = _field(client, name="Note", type="text")
    _set(client, five["a"], pay, "100")
    _set(client, five["a"], note, "x")
    rows = {r["id"]: r for r in client.get(f"/api/jobs?fields={pay}").json()["rows"]}
    assert rows[five["a"]]["fields"] == {str(pay): "100"}
    assert rows[five["b"]]["fields"] == {}
    plain = client.get("/api/jobs").json()["rows"][0]
    assert "fields" not in plain


def test_cf_filters_by_exact_value(client, five):
    pick = _field(client, name="Decision", type="choice", choices=["Yes", "No"])
    _set(client, five["a"], pick, "Yes")
    _set(client, five["b"], pick, "No")
    _set(client, five["c"], pick, "Yes")
    assert set(ids_of(client, f"?cf={pick}:Yes")) == {five["a"], five["c"]}
    assert ids_of(client, f"?cf={pick}:No") == [five["b"]]
    assert len(ids_of(client, "?cf=999:Yes")) == 5  # an unknown field is ignored


def test_sort_by_number_field_is_numeric_with_missing_last(client, five):
    pay = _field(client, name="Pay", type="number")
    _set(client, five["a"], pay, "100")
    _set(client, five["b"], pay, "9")
    _set(client, five["c"], pay, "10")
    asc = ids_of(client, f"?sort=field:{pay}&dir=asc")
    assert asc[:3] == [five["b"], five["c"], five["a"]]
    desc = ids_of(client, f"?sort=field:{pay}&dir=desc")
    assert desc[:3] == [five["a"], five["c"], five["b"]]
    assert set(asc[3:]) == set(desc[3:]) == {five["d"], five["e"]}


def test_sort_by_text_field_is_case_insensitive(client, five):
    tag = _field(client, name="Tag", type="text")
    _set(client, five["a"], tag, "beta")
    _set(client, five["b"], tag, "Alpha")
    assert ids_of(client, f"?sort=field:{tag}&dir=asc")[:2] == [five["b"], five["a"]]


def test_unknown_sort_is_422(client, five):
    assert client.get("/api/jobs?sort=colour").status_code == 422
    assert client.get("/api/jobs?sort=field:abc").status_code == 422


def test_rows_carry_the_requisition_id(client):
    jid = add_job(client.app.state.engine, requisition_id="R-77")
    rows = {r["id"]: r for r in client.get("/api/jobs").json()["rows"]}
    assert rows[jid]["requisition_id"] == "R-77"
