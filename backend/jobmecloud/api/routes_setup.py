from fastapi import APIRouter, HTTPException, Request

from jobmecloud.config.settings import load_settings, save_settings
from jobmecloud.setup.progress import OPTIONAL, STEPS, setup_state, unmet_requirement

router = APIRouter()


def _check_step(step: int) -> None:
    if step not in STEPS:
        raise HTTPException(404, "No such setup step")


@router.get("/setup")
def get_setup(request: Request) -> dict:
    return setup_state(load_settings(request.app.state.data_dir))


@router.post("/setup/{step}/complete")
def complete_step(step: int, request: Request) -> dict:
    _check_step(step)
    data_dir = request.app.state.data_dir
    problem = unmet_requirement(step, data_dir)
    if problem:
        raise HTTPException(400, problem)
    settings = load_settings(data_dir)
    settings.setup_completed_steps = sorted({*settings.setup_completed_steps, step})
    settings.setup_skipped_steps = sorted(set(settings.setup_skipped_steps) - {step})
    save_settings(data_dir, settings)
    return setup_state(settings)


@router.post("/setup/{step}/skip")
def skip_step(step: int, request: Request) -> dict:
    _check_step(step)
    if step not in OPTIONAL:
        raise HTTPException(400, "This step can't be skipped.")
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    settings.setup_skipped_steps = sorted({*settings.setup_skipped_steps, step})
    save_settings(data_dir, settings)
    return setup_state(settings)
