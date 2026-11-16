import argparse
import os
import threading
import webbrowser
from datetime import datetime, timezone

import uvicorn

from jobmecloud import __version__
from jobmecloud.agents.jobscout.pipeline import (
    RunDeps,
    RunSetupError,
    execute_run,
    preflight,
    record_failed_run,
    start_run,
)
from jobmecloud.api.app import create_app
from jobmecloud.config import paths
from jobmecloud.config.settings import SettingsError
from jobmecloud.db.engine import make_engine
from jobmecloud.db.migrate import migrate
from jobmecloud.jobs.runlock import RunInProgressError
from jobmecloud.llm.connection import friendly_message
from jobmecloud.llm.factory import build_provider

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
BROWSER_DELAY_SECONDS = 1.5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jobmecloud", description="Local job-search assistant")
    parser.add_argument("--version", action="version", version=f"jobmecloud {__version__}")
    subparsers = parser.add_subparsers(dest="command")
    start = subparsers.add_parser("start", help="Start the local JobMe server")
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    run = subparsers.add_parser("run", help="Run a JobMe task")
    run.add_argument("--data-dir", help="Use this data folder instead of the default one")
    return parser


def _start(port: int, open_browser: bool) -> int:
    url = f"http://{HOST}:{port}"
    print(f"JobMe is running at {url} (press Ctrl+C to stop)")
    if open_browser:
        timer = threading.Timer(BROWSER_DELAY_SECONDS, webbrowser.open, args=[url])
        timer.daemon = True
        timer.start()
    uvicorn.run(create_app(), host=HOST, port=port)
    return 0


def _problem(exc: Exception) -> str:
    return str(exc) if isinstance(exc, (RunSetupError, SettingsError)) else friendly_message(exc)


def _run() -> int:
    """The scheduled run. Nobody is watching, so every failure ends up on a Run row for Today."""
    data_dir = paths.data_dir()
    engine = make_engine(data_dir=data_dir)
    deps = RunDeps(build_provider)
    now = datetime.now(timezone.utc)
    try:
        migrate(engine)
        try:
            preflight(data_dir, deps)
        except Exception as exc:
            # No Run exists yet, so record the failure on one; otherwise it would be silent.
            message = _problem(exc)
            record_failed_run(engine, "schedule", now, message)
            print(message)
            return 1
        try:
            run_id = start_run(engine, "schedule", now)
        except RunInProgressError as exc:
            print(exc)  # another run is going; skipping this one is the right thing, not a failure
            return 0
        except Exception as exc:
            message = _problem(exc)
            try:
                record_failed_run(engine, "schedule", now, message)
            except Exception:
                pass  # nothing more can be done; the message is still printed
            print(message)
            return 1
        try:
            run = execute_run(data_dir, engine, run_id, deps, now)
        except Exception as exc:
            print(_problem(exc))  # execute_run has already recorded this on the Run
            return 1
    finally:
        engine.dispose()
    print(f"Found {run.found} jobs: {run.new} new, {run.matched} matched.")
    for error in run.errors:
        print(f"Problem: {error}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "start":
        return _start(args.port, open_browser=not args.no_browser)
    if getattr(args, "data_dir", None):
        os.environ["JOBMECLOUD_DATA_DIR"] = args.data_dir
    return _run()


if __name__ == "__main__":
    raise SystemExit(main())
