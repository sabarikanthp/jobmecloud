"""Automatic searches: EventBridge Scheduler starts the run-worker at the chosen days and times."""

import json
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import boto3

PREFIX = "jobmecloud-run-"
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _client(client):
    return client or boto3.client("scheduler")


def _validate(days: list[str], times: list[str]) -> None:
    if not days:
        raise ValueError("Choose at least one day.")
    for d in days:
        if d not in DAYS:
            raise ValueError(f"Unknown day: {d}.")
    if not times:
        raise ValueError("Choose at least one time.")
    for t in times:
        if not _TIME.match(t):
            raise ValueError("Times must look like 09:30.")


def _name(time: str) -> str:
    return PREFIX + time.replace(":", "")


def _existing(scheduler) -> list[str]:
    names: list[str] = []
    for page in scheduler.get_paginator("list_schedules").paginate(NamePrefix=PREFIX):
        names += [s["Name"] for s in page["Schedules"]]
    return names


def sync_schedules(days: list[str], times: list[str], tz: str, *, client=None) -> list[str]:
    """Make this account's jobmecloud-run-* schedules match the request: one per time of day."""
    _validate(days, times)
    scheduler = _client(client)
    ordered_days = [d for d in DAYS if d in days]
    wanted = sorted({_name(t): t for t in times}.items())
    for name, time in wanted:
        hour, minute = (int(x) for x in time.split(":"))
        spec = dict(
            Name=name,
            ScheduleExpression=f"cron({minute} {hour} ? * {','.join(d.upper() for d in ordered_days)} *)",
            ScheduleExpressionTimezone=tz,
            FlexibleTimeWindow={"Mode": "OFF"},
            State="ENABLED",
            Target={
                "Arn": os.environ["JOBMECLOUD_RUN_FUNCTION_ARN"],
                "RoleArn": os.environ["JOBMECLOUD_SCHEDULER_ROLE_ARN"],
                "Input": json.dumps({"trigger": "schedule"}),
                "RetryPolicy": {"MaximumRetryAttempts": 0},  # a retry would start a second run
            },
        )
        try:
            scheduler.create_schedule(**spec)
        except scheduler.exceptions.ConflictException:
            scheduler.update_schedule(**spec)
    keep = {name for name, _ in wanted}
    for name in _existing(scheduler):
        if name not in keep:
            scheduler.delete_schedule(Name=name)
    return [name for name, _ in wanted]


def clear_schedules(*, client=None) -> None:
    scheduler = _client(client)
    for name in _existing(scheduler):
        scheduler.delete_schedule(Name=name)


def list_schedules(*, client=None) -> dict:
    names = sorted(_existing(_client(client)))
    return {"enabled": bool(names), "names": names}


def next_run(days: list[str], times: list[str], tz: str, now: datetime | None = None) -> str | None:
    """The soonest chosen day and time after now, in the schedule's time zone, like "Mon 17:30"."""
    zone = ZoneInfo(tz)
    now = (now or datetime.now(zone)).astimezone(zone)
    candidates = []
    for offset in range(8):
        day = now + timedelta(days=offset)
        if DAYS[day.weekday()] not in days:
            continue
        for t in times:
            hour, minute = (int(x) for x in t.split(":"))
            moment = day.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if moment > now:
                candidates.append(moment)
    if not candidates:
        return None
    soonest = min(candidates)
    return f"{soonest.strftime('%a')} {soonest.strftime('%H:%M')}"
