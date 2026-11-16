import json
from unittest.mock import MagicMock

import pytest

from jobmecloud.jobs.dispatch import LambdaDispatcher


def test_lambda_dispatcher_passes_the_email_key_to_the_run_worker():
    lam = MagicMock()
    LambdaDispatcher(lam, run_function="run-fn").start_run(12, email_key="inbound/x")
    assert json.loads(lam.invoke.call_args.kwargs["Payload"]) == {"task": "run", "run_id": 12, "email_key": "inbound/x"}


def test_a_dispatcher_without_a_docs_function_can_still_start_runs_but_not_documents(monkeypatch):
    monkeypatch.delenv("JOBMECLOUD_DOCS_FUNCTION", raising=False)
    lam = MagicMock()
    d = LambdaDispatcher(lam, run_function="run-fn")
    d.start_run(1)
    with pytest.raises(RuntimeError, match="docs"):
        d.start_docs(1, {})
