"""What became of the emailed reports that reached JobMeCloud (shown on the Today screen)."""

from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel

from jobmecloud.inbound import store

router = APIRouter()
LATEST = 5


class InboundOut(BaseModel):
    received_at: datetime
    status: str
    note: str | None
    run_id: int | None


@router.get("/inbound")
def recent_emails(request: Request) -> dict:
    """The newest few emails with their status. The message key and sender address are not exposed."""
    rows = store.recent(request.app.state.engine, LATEST)
    return {"emails": [InboundOut(received_at=r.received_at, status=r.status, note=r.note, run_id=r.run_id).model_dump(mode="json")
                       for r in rows]}
