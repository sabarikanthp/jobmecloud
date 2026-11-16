"""Provider rules for structured output, checked on every schema the app sends.

A fake provider accepts any schema, so these rules were first discovered against the real API: Anthropic requires
every object in a schema to set additionalProperties to false. One schema that forgets it fails a whole step.
"""

import importlib

import pytest

MODULES = [
    "jobmecloud.agents.jobscout.extract",
    "jobmecloud.agents.jobscout.liveness",
    "jobmecloud.agents.jobscout.score",
    "jobmecloud.applydocs.content",
    "jobmecloud.resumes.mapping",
    "jobmecloud.setup.ai_import",
    "jobmecloud.inbound.extract",
]


def schemas():
    found = []
    for module in MODULES:
        mod = importlib.import_module(module)
        for name in dir(mod):
            value = getattr(mod, name)
            if name.endswith("SCHEMA") and isinstance(value, dict):
                found.append((f"{module}.{name}", value))
    return found


def objects(node, path="schema"):
    """Every object-typed node in a schema, with where it is."""
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield path, node
        for key, child in node.items():
            yield from objects(child, f"{path}.{key}")
    elif isinstance(node, list):
        for i, child in enumerate(node):
            yield from objects(child, f"{path}[{i}]")


def test_the_sweep_finds_the_schemas_it_is_meant_to_check():
    assert len(schemas()) >= 6  # guards against the module list rotting


@pytest.mark.parametrize("name,schema", schemas(), ids=[n for n, _ in schemas()])
def test_every_object_in_a_schema_forbids_extra_properties(name, schema):
    missing = [path for path, node in objects(schema) if node.get("additionalProperties") is not False]
    assert not missing, f"{name}: additionalProperties must be false at {missing}"
