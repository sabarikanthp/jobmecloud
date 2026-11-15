from jobmecloud.config.settings import ProviderConfig, StepModel

STEP_NAMES = ("search", "extract", "liveness", "score", "tailor")

CLAUDE_DEFAULT_MODELS = {
    "search": "claude-sonnet-5-5",
    "extract": "claude-haiku-5-5",
    "liveness": "claude-haiku-5-5",
    "score": "claude-haiku-5-5",
    "tailor": "claude-sonnet-5-5",
}

RECOMMENDED_MODELS: dict[str, list[str]] = {
    "anthropic": ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
    "openai_compatible": [],
}

STEP_INFO: dict[str, tuple[str, str]] = {
    "search": ("Searching", "Finds job postings on the web. Needs a strong model."),
    "extract": (
        "Reading",
        "Pulls the details out of each posting, and reads the resume and notes you upload.",
    ),
    "liveness": (
        "Checking if still open",
        "Decides whether a posting is still taking applications when the page is unclear.",
    ),
    "score": ("Scoring matches", "Rates how well each job fits you, from 0 to 100."),
    "tailor": (
        "Writing documents",
        "Writes your tailored resume and cover letter. Needs a strong model.",
    ),
}

LOCAL_MODEL_NOTE = (
    "Small local models may do poorly at searching and at checking that your resume stays truthful."
)


def default_steps(cfg: ProviderConfig, model: str | None) -> dict[str, StepModel]:
    if cfg.kind == "anthropic":
        return {
            name: StepModel(provider_id=cfg.id, model=CLAUDE_DEFAULT_MODELS[name])
            for name in STEP_NAMES
        }
    if not model or not model.strip():
        raise ValueError("Enter the model name to use.")
    return {name: StepModel(provider_id=cfg.id, model=model.strip()) for name in STEP_NAMES}
