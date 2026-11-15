import json
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3
import pytest

from jobmecloud.scheduling import eventbridge as eb

RUN_ARN = "arn:aws:lambda:us-east-1:123456789012:function:run-worker"
ROLE_ARN = "arn:aws:iam::123456789012:role/scheduler-invoke"


@pytest.fixture(autouse=True)
def scheduler_env(monkeypatch):
    monkeypatch.setenv("JOBMECLOUD_RUN_FUNCTION_ARN", RUN_ARN)
    monkeypatch.setenv("JOBMECLOUD_SCHEDULER_ROLE_ARN", ROLE_ARN)


@pytest.fixture
def scheduler():
    return boto3.client("scheduler")


def names(scheduler):
    return sorted(s["Name"] for s in scheduler.list_schedules(NamePrefix="jobmecloud-run-")["Schedules"])


def test_creates_one_schedule_per_time(scheduler):
    created = eb.sync_schedules(["mon", "wed"], ["09:00", "17:30"], "America/Chicago", client=scheduler)
    assert created == ["jobmecloud-run-0900", "jobmecloud-run-1730"]
    assert names(scheduler) == created


def test_cron_uses_selected_days_and_the_time_zone(scheduler):
    eb.sync_schedules(["mon", "wed", "fri"], ["09:05"], "America/Chicago", client=scheduler)
    s = scheduler.get_schedule(Name="jobmecloud-run-0905")
    assert s["ScheduleExpression"] == "cron(5 9 ? * MON,WED,FRI *)"
    assert s["ScheduleExpressionTimezone"] == "America/Chicago"
    assert s["Target"]["Arn"] == RUN_ARN and s["Target"]["RoleArn"] == ROLE_ARN
    assert json.loads(s["Target"]["Input"]) == {"trigger": "schedule"}
    assert s["Target"]["RetryPolicy"]["MaximumRetryAttempts"] == 0


def test_updating_changes_existing_schedules(scheduler):
    eb.sync_schedules(["mon"], ["09:00"], "UTC", client=scheduler)
    eb.sync_schedules(["tue", "thu"], ["09:00"], "UTC", client=scheduler)
    assert scheduler.get_schedule(Name="jobmecloud-run-0900")["ScheduleExpression"] == "cron(0 9 ? * TUE,THU *)"
    assert names(scheduler) == ["jobmecloud-run-0900"]


def test_removes_stale_schedules_and_leaves_others_alone(scheduler):
    scheduler.create_schedule(Name="someone-elses", ScheduleExpression="rate(1 day)",
                              FlexibleTimeWindow={"Mode": "OFF"},
                              Target={"Arn": RUN_ARN, "RoleArn": ROLE_ARN})
    eb.sync_schedules(["mon"], ["09:00", "10:00"], "UTC", client=scheduler)
    eb.sync_schedules(["mon"], ["10:00"], "UTC", client=scheduler)
    assert names(scheduler) == ["jobmecloud-run-1000"]
    assert scheduler.get_schedule(Name="someone-elses")["Name"] == "someone-elses"


def test_clear_removes_all_of_ours(scheduler):
    eb.sync_schedules(["mon"], ["09:00", "10:00"], "UTC", client=scheduler)
    eb.clear_schedules(client=scheduler)
    assert names(scheduler) == []


def test_status_reports_whether_schedules_exist(scheduler):
    assert eb.list_schedules(client=scheduler) == {"enabled": False, "names": []}
    eb.sync_schedules(["mon"], ["09:00"], "UTC", client=scheduler)
    assert eb.list_schedules(client=scheduler) == {"enabled": True, "names": ["jobmecloud-run-0900"]}


@pytest.mark.parametrize("days,times,message", [
    ([], ["09:00"], "Choose at least one day."),
    (["mon"], [], "Choose at least one time."),
    (["funday"], ["09:00"], "Unknown day: funday."),
    (["mon"], ["9am"], "Times must look like 09:30."),
    (["mon"], ["25:00"], "Times must look like 09:30."),
])
def test_bad_input_is_refused_before_touching_aws(scheduler, days, times, message):
    with pytest.raises(ValueError, match=message):
        eb.sync_schedules(days, times, "UTC", client=scheduler)
    assert names(scheduler) == []


def test_next_run_is_the_soonest_chosen_time_in_the_zone():
    now = datetime(2026, 11, 16, 10, 0, tzinfo=ZoneInfo("America/Chicago"))  # a Monday
    assert eb.next_run(["mon", "wed"], ["09:00", "17:30"], "America/Chicago", now) == "Mon 17:30"
    later = datetime(2026, 11, 16, 18, 0, tzinfo=ZoneInfo("America/Chicago"))
    assert eb.next_run(["mon", "wed"], ["09:00", "17:30"], "America/Chicago", later) == "Wed 09:00"
    assert eb.next_run([], ["09:00"], "UTC", now) is None
