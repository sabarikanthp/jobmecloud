"""The custom resource that activates the SES receipt rule set (infra/rules_handler/index.py)."""

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "rules_handler_index", Path(__file__).resolve().parents[1] / "infra" / "rules_handler" / "index.py")
index = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(index)


class FakeSes:
    def __init__(self, active=None):
        self.active, self.calls = active, []

    def describe_active_receipt_rule_set(self):
        return {"Metadata": {"Name": self.active}} if self.active else {}

    def set_active_receipt_rule_set(self, **kwargs):
        self.calls.append(kwargs)
        self.active = kwargs.get("RuleSetName")


def event(kind, name="mine"):
    return {"RequestType": kind, "ResourceProperties": {"RuleSetName": name}}


@pytest.mark.parametrize("kind", ["Create", "Update"])
def test_activates_our_rule_set_when_none_is_active(kind):
    ses = FakeSes()
    result = index.on_event(event(kind), None, ses=ses)
    assert ses.calls == [{"RuleSetName": "mine"}] and result["PhysicalResourceId"] == "mine"


def test_leaves_it_alone_when_ours_is_already_active():
    ses = FakeSes(active="mine")
    index.on_event(event("Update"), None, ses=ses)
    assert ses.calls == []


def test_refuses_to_replace_another_active_rule_set():
    ses = FakeSes(active="someone-elses")
    with pytest.raises(Exception, match="someone-elses"):
        index.on_event(event("Create"), None, ses=ses)
    assert ses.calls == []  # nothing was changed


def test_delete_deactivates_ours_so_it_can_be_removed():
    ses = FakeSes(active="mine")
    index.on_event(event("Delete"), None, ses=ses)
    assert ses.calls == [{}] and ses.active is None


def test_delete_leaves_a_different_active_rule_set_alone():
    ses = FakeSes(active="someone-elses")
    index.on_event(event("Delete"), None, ses=ses)
    assert ses.calls == []
