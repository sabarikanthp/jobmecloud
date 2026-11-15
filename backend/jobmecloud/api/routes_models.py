from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from jobmecloud.config.defaults import (
    LOCAL_MODEL_NOTE,
    RECOMMENDED_MODELS,
    STEP_INFO,
    STEP_NAMES,
    default_steps,
)
from jobmecloud.config.settings import load_settings, save_settings

router = APIRouter()


class DefaultsIn(BaseModel):
    provider_id: str
    model: str | None = None


@router.get("/models")
def get_models() -> dict:
    return {
        "steps": [
            {"id": name, "label": STEP_INFO[name][0], "help": STEP_INFO[name][1]}
            for name in STEP_NAMES
        ],
        "recommended": RECOMMENDED_MODELS,
        "local_note": LOCAL_MODEL_NOTE,
    }


@router.post("/steps/defaults")
def apply_defaults(body: DefaultsIn, request: Request) -> dict:
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    cfg = next((p for p in settings.providers if p.id == body.provider_id), None)
    if cfg is None:
        raise HTTPException(404, "No provider with that id")
    try:
        steps = default_steps(cfg, body.model)
    except ValueError:
        raise HTTPException(400, "Enter the model name to use.") from None
    settings.steps = steps
    save_settings(data_dir, settings)
    return {name: sm.model_dump() for name, sm in steps.items()}
