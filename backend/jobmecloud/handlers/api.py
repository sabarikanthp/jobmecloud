"""Lambda entry point for the API (API Gateway HTTP API, payload format 2.0)."""

from mangum import Mangum

from jobmecloud.api.app import create_app

_handler: Mangum | None = None


def handler(event: dict, context) -> dict:
    global _handler
    if _handler is None:  # built on first use, then reused while the Lambda stays warm
        _handler = Mangum(create_app(), lifespan="off")
    return _handler(event, context)
