"""Start long work (a search run, writing documents) somewhere other than the web request.

In AWS the work goes to a worker Lambda. In tests and local development it runs in a thread of this process.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Protocol

import boto3

log = logging.getLogger(__name__)


class Dispatcher(Protocol):
    synchronous_docs: bool  # True: "Make docs" finishes inside the request (tests, local use)

    def start_run(self, run_id: int, email_key: str | None = None) -> None: ...

    def start_docs(self, job_id: int, options: dict) -> None: ...


class LambdaDispatcher:
    """Invoke the worker Lambdas asynchronously: the request returns while they work."""

    synchronous_docs = False

    def __init__(self, client=None, run_function: str | None = None, docs_function: str | None = None):
        self._client = client or boto3.client("lambda")
        self.run_function = run_function or os.environ["JOBMECLOUD_RUN_FUNCTION"]
        self.docs_function = docs_function or os.environ.get("JOBMECLOUD_DOCS_FUNCTION")  # the ingest function starts runs only

    def _invoke(self, function: str, payload: dict) -> None:
        self._client.invoke(FunctionName=function, InvocationType="Event", Payload=json.dumps(payload).encode())

    def start_run(self, run_id: int, email_key: str | None = None) -> None:
        payload = {"task": "run", "run_id": run_id}
        if email_key:
            payload["email_key"] = email_key  # the run worker takes its candidates from this stored email
        self._invoke(self.run_function, payload)

    def start_docs(self, job_id: int, options: dict) -> None:
        if not self.docs_function:
            raise RuntimeError("No docs worker is configured (JOBMECLOUD_DOCS_FUNCTION).")
        self._invoke(self.docs_function, {"task": "docs", "job_id": job_id, "options": options})


class ThreadDispatcher:
    """Run a search in a background thread of this process. Documents are written inside the request."""

    synchronous_docs = True

    def __init__(self, state):
        self.state = state

    def start_run(self, run_id: int, email_key: str | None = None) -> None:
        from jobmecloud.agents.jobscout.pipeline import execute_run

        state = self.state

        def work() -> None:
            try:
                execute_run(state.data_dir, state.engine, run_id, state.run_deps, datetime.now(timezone.utc))
            except Exception:
                log.exception("Background run failed")  # execute_run already recorded the failure on the Run

        state.run_thread = threading.Thread(target=work, daemon=True)
        state.run_thread.start()

    def start_docs(self, job_id: int, options: dict) -> None:
        raise NotImplementedError("Documents are written inside the request when synchronous_docs is true")
