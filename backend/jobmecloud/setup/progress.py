from pathlib import Path

from jobmecloud.config.profile import load_resume, load_search, load_user
from jobmecloud.config.settings import Settings, load_settings
from jobmecloud.secrets import get_secret

STEPS: dict[int, str] = {
    1: "Welcome",
    2: "Connect an AI",
    3: "About you",
    4: "Your resume",
    5: "What you're looking for",
    6: "Employers to watch",
    7: "Import past jobs",
    8: "Schedule and match cutoff",
    9: "Done",
}
REQUIRED = {1, 2, 3, 4, 5}
OPTIONAL = {6, 7, 8}
_STEP_NAMES = ("search", "extract", "liveness", "score", "tailor")


def _unmet_ai(data_dir: Path) -> str | None:
    settings = load_settings(data_dir)
    provider_kinds = {p.id: p.kind for p in settings.providers}
    if not provider_kinds or any(
        name not in settings.steps or settings.steps[name].provider_id not in provider_kinds
        for name in _STEP_NAMES
    ):
        return "Add an AI connection and choose its models first."
    search_kind = provider_kinds[settings.steps["search"].provider_id]
    if search_kind != "anthropic" and (
        settings.search_backend == "builtin"
        or not get_secret(f"search:{settings.search_backend}")
    ):
        return "This AI has no built-in search. Choose Tavily or Brave and save its key."
    return None


def unmet_requirement(step: int, data_dir: Path) -> str | None:
    if step == 2:
        return _unmet_ai(data_dir)
    if step == 3:
        user = load_user(data_dir)
        if not (user.name.strip() and user.email.strip()):
            return "Please enter your name and email."
    elif step == 4:
        resume = load_resume(data_dir)
        if resume is None or not resume.roles:
            return "Add your resume first. It needs at least one job."
    elif step == 5:
        if not load_search(data_dir).target_roles:
            return "Add at least one job title you're looking for."
    elif step == 9:
        completed = set(load_settings(data_dir).setup_completed_steps)
        for n in sorted(REQUIRED):
            if n not in completed:
                return f'Finish the "{STEPS[n]}" step first.'
    return None


def setup_state(settings: Settings) -> dict:
    completed = sorted(set(settings.setup_completed_steps))
    skipped = sorted(set(settings.setup_skipped_steps))
    next_step = next((n for n in STEPS if n not in completed and n not in skipped), 9)
    return {
        "completed": completed,
        "skipped": skipped,
        "next_step": next_step,
        "finished": 9 in completed,
    }
