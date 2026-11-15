from fastapi import APIRouter, HTTPException, Request, Response

from jobmecloud.config.settings import ProviderConfig, Settings, load_settings, save_settings
from jobmecloud.secrets import delete_secret, get_secret, set_secret

router = APIRouter()


class ProviderIn(ProviderConfig):
    api_key: str | None = None


class ProviderOut(ProviderConfig):
    has_key: bool


def _provider_out(cfg: ProviderConfig) -> ProviderOut:
    return ProviderOut(**cfg.model_dump(), has_key=bool(get_secret(f"provider:{cfg.id}")))


@router.get("/settings")
def get_settings(request: Request) -> Settings:
    return load_settings(request.app.state.data_dir)


@router.put("/settings")
def put_settings(body: Settings, request: Request) -> Settings:
    save_settings(request.app.state.data_dir, body)
    return body


@router.get("/providers")
def list_providers(request: Request) -> list[ProviderOut]:
    return [_provider_out(p) for p in load_settings(request.app.state.data_dir).providers]


@router.put("/providers/{provider_id}")
def put_provider(provider_id: str, body: ProviderIn, request: Request) -> ProviderOut:
    if body.id != provider_id:
        raise HTTPException(422, "The provider id in the body must match the address")
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    cfg = ProviderConfig(**body.model_dump(exclude={"api_key"}))
    previous = next((p for p in settings.providers if p.id == provider_id), None)
    if previous:
        settings.providers = [cfg if p.id == provider_id else p for p in settings.providers]
    else:
        settings.providers = [*settings.providers, cfg]
    save_settings(data_dir, settings)
    new_key = bool(body.api_key and body.api_key.strip())
    if new_key:
        set_secret(f"provider:{provider_id}", body.api_key)
    elif previous and (previous.kind, previous.base_url) != (cfg.kind, cfg.base_url):
        # Never send the old key to a different kind of service or address.
        delete_secret(f"provider:{provider_id}")
    return _provider_out(cfg)


@router.delete("/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: str, request: Request) -> Response:
    data_dir = request.app.state.data_dir
    settings = load_settings(data_dir)
    settings.providers = [p for p in settings.providers if p.id != provider_id]
    settings.steps = {k: v for k, v in settings.steps.items() if v.provider_id != provider_id}
    save_settings(data_dir, settings)
    delete_secret(f"provider:{provider_id}")
    return Response(status_code=204)
