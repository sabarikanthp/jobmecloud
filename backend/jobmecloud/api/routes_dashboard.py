from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlmodel import Session

from jobmecloud.config.settings import load_settings
from jobmecloud.jobs import stats

router = APIRouter()


@router.get("/dashboard")
def dashboard(request: Request, weeks: Annotated[int, Query(ge=4, le=52)] = 12) -> dict:
    today = request.app.state.today()
    cutoff = load_settings(request.app.state.data_dir).match_cutoff
    with Session(request.app.state.engine) as session:
        return {
            "funnel": stats.funnel(session, today, cutoff),
            "weekly": stats.weekly(session, today, weeks),
            "response": stats.response(session, today),
            "skip_reasons": stats.skip_reasons(session, today),
            "sources": stats.sources(session, today, cutoff),
            "followups": {k: [r.model_dump() for r in v]
                          for k, v in stats.followups(session, today).items()},
        }
