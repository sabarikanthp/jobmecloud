from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from jobmecloud.config.profile import load_resume, load_search
from jobmecloud.config.settings import load_settings
from jobmecloud.db.models import Job
from jobmecloud.jobs.check import CheckError, fit_job, model_choices, read_job
from jobmecloud.jobs.tracking import allowed_next
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.errors import ProviderError
from jobmecloud.llm.steps import StepNotConfiguredError, provider_for_step

router = APIRouter()


class CheckIn(BaseModel):
    input: str = ""


def summary(job) -> dict:
    return {"id": job.id, "employer": job.employer, "title": job.title, "status": job.status,
            "match_score": job.match_score, "apply_url": job.apply_url, "allowed_next": allowed_next(job)}


@router.post("/jobs/check")
def check_job(body: CheckIn, request: Request) -> dict:
    state = request.app.state
    settings = load_settings(state.data_dir)
    try:
        provider, model = provider_for_step(settings, "extract", state.provider_builder)
    except StepNotConfiguredError as e:
        raise HTTPException(400, str(e))
    today = state.today()
    now = datetime.combine(today, datetime.now().time()).astimezone().astimezone(timezone.utc)
    with Session(state.engine) as session:
        try:
            result = read_job(
                session, raw=body.input, provider=provider, model=model, fetch=state.check_fetch,
                profile=load_search(state.data_dir), today=today, now=now, prices=settings.prices,
                cap=settings.caps.max_spend_per_run_usd,
            )
        except CheckError as e:
            raise HTTPException(e.status, e.message)
        except ProviderError as e:
            raise HTTPException(502, friendly_message(e))
        return {"status": result["status"], "truncated": result["truncated"], "job": summary(result["job"])}


@router.get("/jobs/check/models")
def check_models(request: Request) -> dict:
    return {"choices": model_choices(load_settings(request.app.state.data_dir))}


class FitIn(BaseModel):
    model: str = "score"


@router.post("/jobs/{job_id}/fit")
def fit(job_id: int, body: FitIn, request: Request) -> dict:
    state = request.app.state
    settings = load_settings(state.data_dir)
    today = state.today()
    now = datetime.combine(today, datetime.now().time()).astimezone().astimezone(timezone.utc)
    with Session(state.engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "That job was not found.")
        try:
            result = fit_job(
                session, job, step=body.model, settings=settings, builder=state.provider_builder,
                profile=load_search(state.data_dir), resume=load_resume(state.data_dir), today=today, now=now,
            )
        except CheckError as e:
            raise HTTPException(e.status, e.message)
        except StepNotConfiguredError as e:
            raise HTTPException(400, str(e))
        except ProviderError as e:
            raise HTTPException(502, friendly_message(e))
        return {
            "fit": {
                "score": result.score, "cutoff": settings.match_cutoff,
                "above_cutoff": result.score >= settings.match_cutoff, "reasons": result.reasons,
                "gaps": result.gaps, "warnings": result.warnings, "rules": result.rules,
                "model": result.model, "cost_usd": round(result.cost, 4),
            },
            "job": {"id": job.id, "status": job.status, "allowed_next": allowed_next(job),
                    "match_score": job.match_score},
        }
