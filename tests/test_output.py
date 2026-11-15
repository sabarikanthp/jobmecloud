from datetime import date, datetime, timezone

import pytest

from jobmecloud.applydocs.output import (
    FileInUseError,
    archive_previous,
    job_folder_name,
    prepare_folder,
    write_notes_md,
)
from jobmecloud.db.models import Job

J = lambda **kw: Job(**{"employer": "AT&T / Mobility", "title": "Sr. PM?", "origin": "scout", "status": "New",
                        "first_seen_at": datetime.now(timezone.utc), **kw})


def test_folder_names_are_valid_and_unique(tmp_path):
    assert job_folder_name("{date}_{company}_{title}", J(), date(2026, 11, 12)) == "2026-11-12_AT&T-Mobility_Sr.-PM"
    assert job_folder_name("{company}", J(employer="CON"), date(2026, 1, 1)) == "CON_"
    assert len(job_folder_name("{date}_{company}_{title}", J(title="x" * 300), date(2026, 1, 1))) <= 120
    a = prepare_folder(tmp_path, "n", None); b = prepare_folder(tmp_path, "n", None)
    assert (a.name, b.name) == ("n", "n-2") and prepare_folder(tmp_path, "other", str(a)) == a


def test_folder_name_edge_cases():
    d = date(2026, 1, 1)
    assert job_folder_name("{company}", J(employer="nul.txt"), d) == "nul.txt_"
    assert job_folder_name("{company}", J(employer="Lpt1"), d) == "Lpt1_"
    assert job_folder_name("{company}", J(employer="???"), d) == "job"
    assert job_folder_name("{company}.", J(employer="Acme"), d) == "Acme"
    assert job_folder_name("{company}_{foo}", J(employer="Acme"), d) == "Acme_{foo}"


def test_prepare_folder_ignores_existing_outside_applications(tmp_path):
    apps = tmp_path / "apps"; apps.mkdir()
    outside = tmp_path / "outside"; outside.mkdir()
    got = prepare_folder(apps, "n", str(outside))
    assert got == apps / "n" and got.is_dir()


def test_archive_moves_files_and_refuses_when_locked(tmp_path, monkeypatch):
    (tmp_path / "resume.docx").write_bytes(b"1"); (tmp_path / "notes.md").write_text("n")
    dest = archive_previous(tmp_path, datetime(2026, 11, 12, 9, 30, tzinfo=timezone.utc))
    assert dest.parent.name == "previous" and (dest / "resume.docx").exists() and not (tmp_path / "resume.docx").exists()
    (tmp_path / "resume.docx").write_bytes(b"2")
    real_open = open
    def locked(path, *a, **k):
        if str(path).endswith("resume.docx") and "a" in (a[0] if a else k.get("mode", "r")):
            raise PermissionError
        return real_open(path, *a, **k)
    monkeypatch.setattr("builtins.open", locked)
    with pytest.raises(FileInUseError, match=r"Close resume.docx in Word, then try again."):
        archive_previous(tmp_path, datetime(2026, 11, 12, 10, tzinfo=timezone.utc))
    assert (tmp_path / "resume.docx").read_bytes() == b"2"


def test_archive_nothing_and_same_second(tmp_path):
    now = datetime(2026, 11, 12, 9, 30, tzinfo=timezone.utc)
    assert archive_previous(tmp_path, now) is None
    (tmp_path / "notes.md").write_text("a")
    d1 = archive_previous(tmp_path, now)
    (tmp_path / "notes.md").write_text("b")
    d2 = archive_previous(tmp_path, now)
    assert d1 != d2 and (d2 / "notes.md").read_text() == "b"


def test_notes_md(tmp_path):
    write_notes_md(tmp_path, J(match_score=88, reasons="Fits", gaps="Spark"), changes=["Moved B first"],
                   check_notes=[], page_note="2 pages, same as your resume", resume_name="Main", as_is=False)
    text = (tmp_path / "notes.md").read_text(encoding="utf-8")
    for s in ["88", "Fits", "Moved B first", "2 pages, same as your resume", "Spark", "Main"]:
        assert s in text


@pytest.mark.parametrize("pattern,kw", [
    ("{company}", {"employer": r"..\..\x"}),
    ("{title}", {"title": "a/b:c"}),
    ("{company}/{title}", {}),
    (r"..\x", {}),
    (r"C:\x", {}),
    ("...", {}),
    ("..", {}),
])
def test_folder_name_is_single_safe_component(tmp_path, pattern, kw):
    name = job_folder_name(pattern, J(**kw), date(2026, 1, 1))
    assert name and not any(c in name for c in '<>:"/'+chr(92)+'|?*') and name not in (".", "..")
    folder = prepare_folder(tmp_path, name, None)
    assert folder.parent == tmp_path and folder.is_dir()


def test_prepare_folder_guards_name_and_existing_root(tmp_path):
    assert prepare_folder(tmp_path, "..", None).parent == tmp_path
    assert prepare_folder(tmp_path, r"..\x", None).parent == tmp_path
    got = prepare_folder(tmp_path, "n", str(tmp_path))
    assert got != tmp_path and got.parent == tmp_path
