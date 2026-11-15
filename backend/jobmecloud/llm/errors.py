class ProviderError(Exception):
    pass


class ProviderAuthError(ProviderError):
    pass


class ProviderUnreachableError(ProviderError):
    pass


class ModelNotFoundError(ProviderError):
    pass


class ProviderRateLimitError(ProviderError):
    pass


class ProviderWrongAddressError(ProviderError):
    pass


def status_message(e: Exception) -> str:
    """The provider's own error text from the response body; never the SDK's repr."""
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and isinstance(err.get("message"), str):
            return err["message"]
        for key in ("message", "detail"):
            if isinstance(body.get(key), str):
                return body[key]
    status = getattr(e, "status_code", None)
    return f"HTTP {status}" if status else "Unknown error"
