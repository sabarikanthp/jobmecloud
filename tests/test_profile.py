from pathlib import Path

import pytest
import yaml

from jobmecloud.config.profile import (
    MasterResume,
    SearchProfile,
    UserProfile,
    load_resume,
    load_search,
    load_user,
    save_search,
)
from jobmecloud.config.settings import SettingsError


def test_missing_files_give_defaults(data_dir):
    assert load_user(data_dir) == UserProfile()
    assert load_search(data_dir).work_modes == ["remote", "hybrid", "onsite"]
    assert load_resume(data_dir) is None


def test_round_trip_and_cleaning(data_dir):
    save_search(
        data_dir,
        SearchProfile(target_roles=["  Data Engineer ", "", "  "], rotation={"mon": "Austin"}),
    )
    s = load_search(data_dir)
    assert s.target_roles == ["Data Engineer"] and s.rotation == {"mon": "Austin"}


def test_bad_profile_file_names_field(data_dir):
    (data_dir / "profile").mkdir(exist_ok=True)
    (data_dir / "profile" / "search.yaml").write_text("min_base_pay: -5\n")
    with pytest.raises(SettingsError, match="min_base_pay"):
        load_search(data_dir)


def test_unreadable_profile_file_is_a_settings_error(data_dir):
    (data_dir / "profile").mkdir(exist_ok=True)
    (data_dir / "profile" / "user.yaml").write_text("name: [unclosed\n")
    (data_dir / "profile" / "resume.json").write_text("{nope")
    with pytest.raises(SettingsError, match="user.yaml could not be read"):
        load_user(data_dir)
    with pytest.raises(SettingsError, match="resume.json could not be read"):
        load_resume(data_dir)


def test_example_profile_is_valid():
    root = Path(__file__).parents[1] / "profile.example"
    UserProfile.model_validate(yaml.safe_load((root / "user.yaml").read_text(encoding="utf-8")))
    SearchProfile.model_validate(yaml.safe_load((root / "search.yaml").read_text(encoding="utf-8")))
    resume = MasterResume.model_validate_json((root / "resume.json").read_text(encoding="utf-8"))
    assert resume.roles


def test_profile_routes(client):
    assert client.get("/api/profile/resume").json() is None
    r = client.put("/api/profile/user", json={"name": "Jordan Example", "email": "j@example.com"})
    assert r.status_code == 200 and client.get("/api/profile/user").json()["name"] == "Jordan Example"
    r = client.put("/api/profile/resume", json={"roles": [{"employer": "Acme", "title": "Engineer"}]})
    assert client.get("/api/profile/resume").json()["roles"][0]["employer"] == "Acme"
    r = client.put("/api/profile/search", json={"target_roles": [" Engineer "]})
    assert client.get("/api/profile/search").json()["target_roles"] == ["Engineer"]


def test_editing_master_updates_default_reading(client):
    from datetime import datetime, timezone

    from jobmecloud.config.profile import MasterResume, ResumeRole
    from jobmecloud.resumes.store import add_resume, load_reading

    r1 = MasterResume(summary="One", roles=[ResumeRole(employer="Northwind Labs", title="Engineer")])
    r2 = MasterResume(summary="Two")
    d = client.app.state.data_dir
    e = add_resume(d, name="Main", filename="a.docx", data=b"a", reading=r1, mapping=None,
                   make_default=True, now=datetime(2026, 11, 12, tzinfo=timezone.utc))
    client.put("/api/profile/resume", json=r2.model_dump(mode="json"))
    assert load_reading(d, e.id) == r2
    assert client.post("/api/profile/resume/import", files={"file": ("a.txt", b"x")}).status_code in (404, 405)
