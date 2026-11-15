"""Keep the local working folder and the S3 workspace in step around each request."""

import time

from starlette.concurrency import run_in_threadpool

from jobmecloud.storage.workspace import Workspace

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
PULL_EVERY_SECONDS = 10  # other Lambdas (workers) write files too; re-check S3 at most this often


class WorkspaceSyncMiddleware:
    def __init__(self, app, workspace: Workspace):
        self.app = app
        self.workspace = workspace
        self._last_pull = time.monotonic()  # create_app pulled once already

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if time.monotonic() - self._last_pull > PULL_EVERY_SECONDS:
            await run_in_threadpool(self.workspace.pull)
            self._last_pull = time.monotonic()

        status = 500

        async def tracking_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        await self.app(scope, receive, tracking_send)
        if scope["method"] not in _SAFE_METHODS and status < 400:
            await run_in_threadpool(self.workspace.push)
