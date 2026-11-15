import json
import re
from typing import Any

import jsonschema

from jobmecloud.llm.errors import ProviderError
from jobmecloud.llm.types import LLMResponse, Provider, Usage

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class StructuredOutputError(ProviderError):
    pass


def extract_json(text: str) -> Any:
    """Parse JSON from model text: fenced block, else the outermost {...} or [...]."""
    fenced = _FENCE.search(text)
    candidate = fenced.group(1).strip() if fenced else text.strip()
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    for open_, close in (("{", "}"), ("[", "]")):
        start = candidate.find(open_)
        end = candidate.rfind(close)
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("No JSON found in the reply")


def _parse_and_validate(text: str, schema: dict) -> Any:
    data = extract_json(text)
    jsonschema.validate(data, schema)
    return data


def _call(provider: Provider, model: str, system: str, prompt: str,
          output_schema: dict | None) -> LLMResponse:
    return provider.complete(
        model=model,
        system=system,
        messages=[provider.user_message(prompt)],
        output_schema=output_schema,
    )


def _add(total: Usage, usage: Usage) -> None:
    total.input_tokens += usage.input_tokens
    total.output_tokens += usage.output_tokens


def complete_json(
    provider: Provider, *, model: str, system: str, prompt: str, schema: dict
) -> tuple[dict, Usage]:
    total = Usage()

    if provider.supports_native_schema:
        resp = _call(provider, model, system, prompt, schema)
        _add(total, resp.usage)
        if resp.stop in ("refusal", "max_tokens"):
            raise StructuredOutputError(f"The model stopped early ({resp.stop}).")
        try:
            return _parse_and_validate(resp.text, schema), total
        except (ValueError, jsonschema.ValidationError) as exc:
            raise StructuredOutputError(f"The model's reply was not valid: {exc}") from exc

    base = f"{prompt}\n\nReply with only JSON matching this schema:\n{json.dumps(schema)}"
    attempt_prompt = base
    error = ""
    for attempt in range(2):
        resp = _call(provider, model, system, attempt_prompt, None)
        _add(total, resp.usage)
        if resp.stop == "refusal":
            raise StructuredOutputError("The model refused to answer.")
        try:
            return _parse_and_validate(resp.text, schema), total
        except jsonschema.ValidationError as exc:
            error = exc.message[:500]
        except ValueError as exc:
            error = str(exc)
        attempt_prompt = (
            f"{base}\n\nYour previous reply was not valid: {error}\n"
            "Reply again with only the corrected JSON."
        )
    raise StructuredOutputError(f"The model's reply was not valid JSON for the schema: {error}")
