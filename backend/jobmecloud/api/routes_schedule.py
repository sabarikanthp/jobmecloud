import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from jobmecloud.config.settings import load_settings, save_settings
from jobmecloud.db.models import Run
from jobmecloud.scheduling import eventbridge as eb

router = APIRouter()


class ScheduleIn(BaseModel):
    days: list[str]
    times: list[str]


def _tz() -> str:
    return os.environ.get("JOBMECLOUD_TIMEZONE") or os.environ.get("TZ") or "UTC"


def _client(request: Request):
    return getattr(request.app.state, "scheduler", None)  # None: boto3 makes its own


def _last_run(request: Request) -> dict | None:
    with Session(request.app.state.engine) as session:
        run = session.exec(select(Run).where(Run.trigger == "schedule")
                           .order_by(Run.started_at.desc(), Run.id.desc())).first()
        if run is None:
            return None
        return {"started_at": run.started_at.isoformat(),
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "found": run.found, "new": run.new, "matched": run.matched,
                "errors": list(run.errors or [])}


@router.get("/schedule")
def get_schedule(request: Request) -> dict:
    settings = load_settings(request.app.state.data_dir)
    days, times = list(settings.schedule.days), list(settings.schedule.times)
    enabled = eb.list_schedules(client=_client(request))["enabled"]  # what AWS says, not what was saved
    return {"supported": True, "enabled": enabled, "days": days, "times": times,
            "next_run": eb.next_run(days, times, _tz()) if enabled else None,
            "last_run": _last_run(request)}


@router.post("/schedule/on")
def turn_on(body: ScheduleIn, request: Request) -> dict:
    try:
        eb.sync_schedules(body.days, body.times, _tz(), client=_client(request))
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    settings.schedule.days = [d for d in eb.DAYS if d in body.days]
    settings.schedule.times = sorted(set(body.times))
    settings.schedule.enabled = True
    save_settings(data_dir, settings)
    return {"enabled": True}


@router.post("/schedule/off")
def turn_off(request: Request) -> dict:
    eb.clear_schedules(client=_client(request))
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    settings.schedule.enabled = False
    save_settings(data_dir, settings)
    return {"enabled": False}
