from datetime import datetime, timezone

import pytest
from sqlmodel import select

from jobmecloud.db.models import ActivityLog, CustomValue, Job
from jobmecloud.jobs import custom_fields as cf
from jobmecloud.jobs.tracking import TrackingError

NOW = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)


def make_job(session) -> Job:
    j = Job(employer="Northwind Labs", title="Data Engineer", origin="manual", status="New",
            first_seen_at=NOW)
    session.add(j)
    session.commit()
    return j


def test_create_and_list_in_order(session):
    a = cf.create_field(session, name="Pay band", type="text", at=NOW)
    b = cf.create_field(session, name="Review date", type="date", at=NOW)
    session.commit()
    fields = cf.list_fields(session)
    assert [f.name for f in fields] == ["Pay band", "Review date"]
    assert [f.position for f in fields] == [1, 2]
    assert a.id != b.id


def test_duplicate_name_is_refused_case_insensitively(session):
    cf.create_field(session, name="Pay band", type="text", at=NOW)
    with pytest.raises(TrackingError) as err:
        cf.create_field(session, name="  pay BAND ", type="text", at=NOW)
    assert str(err.value) == "You already have a field called pay BAND."


def test_choice_needs_options_and_dedupes(session):
    with pytest.raises(TrackingError):
        cf.create_field(session, name="Decision", type="choice", at=NOW)
    f = cf.create_field(session, name="Decision", type="choice", choices=["A", "a", " B "], at=NOW)
    assert f.choices == ["A", "B"]


def test_unknown_type_and_bad_names_are_refused(session):
    with pytest.raises(TrackingError):
        cf.create_field(session, name="X", type="money", at=NOW)
    with pytest.raises(TrackingError):
        cf.create_field(session, name="   ", type="text", at=NOW)
    with pytest.raises(TrackingError):
        cf.create_field(session, name="x" * 41, type="text", at=NOW)


def test_normalize_value_per_type(session):
    num = cf.create_field(session, name="Pay", type="number", at=NOW)
    day = cf.create_field(session, name="Day", type="date", at=NOW)
    pick = cf.create_field(session, name="Pick", type="choice", choices=["Yes", "No"], at=NOW)
    assert cf.normalize_value(num, "95000.0") == "95000"
    assert cf.normalize_value(num, "1.5") == "1.5"
    with pytest.raises(TrackingError, match="Enter a number."):
        cf.normalize_value(num, "abc")
    assert cf.normalize_value(day, "2026-03-14") == "2026-03-14"
    with pytest.raises(TrackingError, match="Enter a date as YYYY-MM-DD."):
        cf.normalize_value(day, "3/14/2026")
    assert cf.normalize_value(pick, "Yes") == "Yes"
    with pytest.raises(TrackingError, match="Choose one of the options."):
        cf.normalize_value(pick, "Maybe")
    assert cf.normalize_value(pick, "  ") is None
    assert cf.normalize_value(pick, None) is None


def test_set_values_writes_updates_and_deletes_and_logs(session):
    job = make_job(session)
    f = cf.create_field(session, name="Pay band", type="text", at=NOW)
    cf.set_values(session, job, {f.id: "A"}, at=NOW)
    cf.set_values(session, job, {f.id: "B"}, at=NOW)
    cf.set_values(session, job, {f.id: None}, at=NOW)
    session.commit()
    assert cf.values_for(session, [job.id]) == {}
    logs = session.exec(select(ActivityLog).where(ActivityLog.action == "field_changed")
                        .order_by(ActivityLog.id)).all()
    assert [(r.from_value, r.to_value, r.note) for r in logs] == [
        (None, "A", "Pay band"), ("A", "B", "Pay band"), ("B", None, "Pay band")]
    assert all(r.job_id == job.id and r.actor == "user" for r in logs)


def test_set_values_ignores_unchanged_values(session):
    job = make_job(session)
    f = cf.create_field(session, name="Pay band", type="text", at=NOW)
    cf.set_values(session, job, {f.id: "A"}, at=NOW)
    cf.set_values(session, job, {f.id: "A"}, at=NOW)
    session.commit()
    assert len(session.exec(select(ActivityLog).where(ActivityLog.action == "field_changed")).all()) == 1


def test_set_values_unknown_field_is_refused(session):
    job = make_job(session)
    with pytest.raises(TrackingError, match="That field no longer exists."):
        cf.set_values(session, job, {999: "x"}, at=NOW)


def test_values_for_groups_by_job(session):
    a, b = make_job(session), make_job(session)
    f = cf.create_field(session, name="Pay band", type="text", at=NOW)
    cf.set_values(session, a, {f.id: "A"}, at=NOW)
    cf.set_values(session, b, {f.id: "B"}, at=NOW)
    session.commit()
    assert cf.values_for(session, [a.id, b.id]) == {a.id: {f.id: "A"}, b.id: {f.id: "B"}}
    assert cf.values_for(session, []) == {}


def test_delete_field_removes_values_and_returns_count(session):
    a, b = make_job(session), make_job(session)
    f = cf.create_field(session, name="Pay band", type="text", at=NOW)
    cf.set_values(session, a, {f.id: "A"}, at=NOW)
    cf.set_values(session, b, {f.id: "B"}, at=NOW)
    session.commit()
    assert cf.delete_field(session, f) == 2
    session.commit()
    assert session.exec(select(CustomValue)).all() == []
    assert cf.list_fields(session) == []


def test_cannot_remove_a_choice_option_in_use(session):
    job = make_job(session)
    f = cf.create_field(session, name="Decision", type="choice", choices=["Yes", "No"], at=NOW)
    cf.set_values(session, job, {f.id: "No"}, at=NOW)
    session.commit()
    with pytest.raises(TrackingError, match="That option is still used by 1 jobs."):
        cf.update_field(session, f, choices=["Yes"], at=NOW)
    cf.update_field(session, f, choices=["Yes", "No", "Later"], at=NOW)
    assert f.choices == ["Yes", "No", "Later"]


def test_rename_checks_duplicates_and_keeps_own_name(session):
    a = cf.create_field(session, name="Pay band", type="text", at=NOW)
    cf.create_field(session, name="Other", type="text", at=NOW)
    cf.update_field(session, a, name="PAY BAND", at=NOW)
    assert a.name == "PAY BAND"
    with pytest.raises(TrackingError, match="You already have a field called other."):
        cf.update_field(session, a, name="other", at=NOW)
