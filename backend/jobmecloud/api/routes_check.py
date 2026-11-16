from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session

from jobmecloud.config.profile import load_search
from jobmecloud.config.settings import load_settings
from jobmecloud.jobs.check import CheckError, read_job
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
