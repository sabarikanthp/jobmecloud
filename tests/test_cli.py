import jobmecloud.cli as cli
from jobmecloud import __version__
from jobmecloud.cli import main


def test_version_flag(capsys):
    assert main(["--version"]) == 0
    assert __version__ in capsys.readouterr().out


class _ImmediateTimer:
    """Stands in for threading.Timer: records the delay and runs the function on start()."""

    created = []

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args or []
        self.kwargs = kwargs or {}
        self.daemon = False
        _ImmediateTimer.created.append(self)

    def start(self):
        self.function(*self.args, **self.kwargs)


def _patch_server(monkeypatch):
    runs = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: runs.append((app, kwargs)))
    return runs


def _dispose(runs):
    for app, _ in runs:
        app.state.engine.dispose()


def test_start_runs_server_on_port_without_browser(data_dir, monkeypatch, capsys):
    runs = _patch_server(monkeypatch)
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))

    assert main(["start", "--port", "8123", "--no-browser"]) == 0

    assert len(runs) == 1
    _, kwargs = runs[0]
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8123
    assert opened == []
    assert "JobMe is running at http://127.0.0.1:8123 (press Ctrl+C to stop)" in capsys.readouterr().out
    _dispose(runs)


def test_start_opens_browser_after_delay(data_dir, monkeypatch):
    runs = _patch_server(monkeypatch)
    _ImmediateTimer.created = []
    monkeypatch.setattr(cli.threading, "Timer", _ImmediateTimer)
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))

    assert main(["start", "--port", "8123"]) == 0

    assert len(runs) == 1
    assert len(_ImmediateTimer.created) == 1
    assert _ImmediateTimer.created[0].interval == 1.5
    assert opened == ["http://127.0.0.1:8123"]
    _dispose(runs)


def test_run_without_ai_explains(data_dir, capsys):
    assert main(["run"]) == 1
    assert "Connect an AI first." in capsys.readouterr().out



def test_run_bad_settings_prints_message_not_traceback(data_dir, capsys):
    (data_dir / "settings.yaml").write_text("match_cutoff: 500\n", encoding="utf-8")
    assert main(["run"]) == 1
    out = capsys.readouterr()
    assert "settings.yaml" in out.out and "Traceback" not in out.out + out.err


def test_run_unexpected_error_is_friendly(data_dir, monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(cli, "preflight", boom)
    assert main(["run"]) == 1
    assert capsys.readouterr().out.strip() == "Something went wrong: disk full"


# ------------------------------------------------------------ jobmecloud run, unattended

import pytest
from sqlmodel import Session, select

from jobmecloud.agents.jobscout.pipeline import RunSetupError, start_run
from jobmecloud.db.models import Run
from jobmecloud.db.session import get_engine, init_db
from jobmecloud.jobs.runlock import RunInProgressError, release_run_lock


def _runs(data_dir):
    engine = get_engine(data_dir)
    init_db(engine)
    try:
        with Session(engine) as s:
            return list(s.exec(select(Run).order_by(Run.id)))
    finally:
        engine.dispose()


def test_run_while_another_run_is_in_progress_is_quiet(data_dir, monkeypatch, capsys):
    monkeypatch.setattr(cli, "preflight", lambda *a, **k: None)

    def busy(*a, **k):
        raise RunInProgressError

    monkeypatch.setattr(cli, "start_run", busy)
    assert main(["run"]) == 0
    assert "A run is already in progress." in capsys.readouterr().out
    assert _runs(data_dir) == []


def test_run_that_cannot_start_records_a_failed_scheduled_run(data_dir, monkeypatch, capsys):
    def no_roles(*a, **k):
        raise RunSetupError("Add at least one job title to search for.")

    monkeypatch.setattr(cli, "preflight", no_roles)
    assert main(["run"]) == 1
    assert "Add at least one job title to search for." in capsys.readouterr().out
    [run] = _runs(data_dir)
    assert run.trigger == "schedule" and run.finished_at is not None
    assert run.errors == ["Add at least one job title to search for."]


def test_an_unexpected_setup_error_is_recorded_in_plain_words(data_dir, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "preflight", boom)
    assert main(["run"]) == 1
    [run] = _runs(data_dir)
    assert len(run.errors) == 1 and run.errors[0]


def test_a_failure_after_the_run_started_is_not_recorded_twice(data_dir, monkeypatch):
    monkeypatch.setattr(cli, "preflight", lambda *a, **k: None)

    def started_then_failed(engine, trigger, now):
        run_id = start_run(engine, trigger, now)
        release_run_lock(engine)
        return run_id

    monkeypatch.setattr(cli, "start_run", started_then_failed)

    def fail(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(cli, "execute_run", fail)
    assert main(["run"]) == 1
    assert len(_runs(data_dir)) == 1  # the one start_run made; the pipeline records its own failures


def test_a_start_failure_other_than_an_overlap_is_recorded(data_dir, monkeypatch, capsys):
    monkeypatch.setattr(cli, "preflight", lambda *a, **k: None)

    def locked(*a, **k):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(cli, "start_run", locked)
    assert main(["run"]) == 1
    [run] = _runs(data_dir)
    assert run.trigger == "schedule" and "database is locked" in run.errors[0]
    assert "database is locked" in capsys.readouterr().out


def test_run_uses_the_data_folder_it_is_given(data_dir, tmp_path, monkeypatch):
    other = tmp_path / "elsewhere"
    other.mkdir()

    def no_roles(*a, **k):
        raise RunSetupError("Add at least one job title to search for.")

    monkeypatch.setattr(cli, "preflight", no_roles)
    assert main(["run", "--data-dir", str(other)]) == 1
    assert len(_runs(other)) == 1 and _runs(data_dir) == []
