import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from jobmecloud.config import paths
from jobmecloud.config.files import atomic_write_text
from jobmecloud.config.settings import (
    Caps,
    Price,
    ProviderConfig,
    Schedule,
    Settings,
    SettingsError,
    StepModel,
    load_settings,
    save_settings,
)


def test_defaults_written_when_missing(data_dir):
    s = load_settings(data_dir)
    assert s.match_cutoff == 75
    assert s.prices["claude-haiku-5-5"].input_per_mtok == 0.10
    assert (data_dir / "settings.yaml").exists()


def test_round_trip(data_dir):
    s = load_settings(data_dir)
    s.match_cutoff = 80
    save_settings(data_dir, s)
    assert load_settings(data_dir).match_cutoff == 80


def test_applications_default(data_dir):
    assert load_settings(data_dir).applications_path(data_dir) == data_dir / "applications"


def test_applications_custom(data_dir, tmp_path):
    s = Settings(applications_dir=str(tmp_path / "apps"))
    assert s.applications_path(data_dir) == tmp_path / "apps"


def test_data_dir_env_override(data_dir):
    assert paths.data_dir() == data_dir


def test_unknown_keys_ignored(data_dir):
    (data_dir / "settings.yaml").write_text("match_cutoff: 70\nsomething_old: 1\n")
    assert load_settings(data_dir).match_cutoff == 70


def test_bad_value_names_field(data_dir):
    (data_dir / "settings.yaml").write_text("match_cutoff: lots\n")
    with pytest.raises(SettingsError, match="match_cutoff"):
        load_settings(data_dir)


def test_ensure_dirs_handles_spaces(tmp_path):
    d = tmp_path / "My Jobs Folder"
    paths.ensure_dirs(d, Settings())
    assert (d / "profile").is_dir() and (d / "applications").is_dir()








def test_defaults_and_exports():
    s = Settings()
    assert s.folder_pattern == "{date}_{company}_{title}"
    assert s.caps == Caps()
    assert s.schedule == Schedule()
    assert s.followup_default_days == 7
    assert s.prices["claude-opus-5-5"] == Price(input_per_mtok=4, output_per_mtok=20)
    assert s.prices["claude-sonnet-5-5"].output_per_mtok == 10
    assert ProviderConfig(id="a", kind="anthropic", label="A").structured_output == "native"
    assert StepModel(provider_id="a", model="m").model == "m"


def test_steps_and_providers_round_trip(data_dir):
    s = Settings(
        providers=[ProviderConfig(id="o", kind="openai_compatible", label="O", base_url="http://x")],
        steps={"search": StepModel(provider_id="o", model="m")},
    )
    save_settings(data_dir, s)
    assert load_settings(data_dir) == s


def test_bad_step_key_names_field(data_dir):
    (data_dir / "settings.yaml").write_text("steps:\n  bogus:\n    provider_id: a\n    model: m\n")
    with pytest.raises(SettingsError, match="steps"):
        load_settings(data_dir)


def test_bad_value_message_has_reason_and_file_path(data_dir):
    (data_dir / "settings.yaml").write_text("match_cutoff: lots\n")
    with pytest.raises(SettingsError) as ei:
        load_settings(data_dir)
    msg = str(ei.value)
    assert str(data_dir / "settings.yaml") in msg
    assert "match_cutoff - Input should be a valid integer" in msg


def test_non_mapping_file_message(data_dir):
    (data_dir / "settings.yaml").write_text("- a\n- b\n")
    with pytest.raises(SettingsError, match="must contain settings written as `name: value` lines"):
        load_settings(data_dir)


def test_atomic_write_leaves_no_temp(tmp_path):
    f = tmp_path / "a.yaml"
    atomic_write_text(f, "one")
    atomic_write_text(f, "two")
    assert f.read_text(encoding="utf-8") == "two"
    assert [p.name for p in tmp_path.iterdir()] == ["a.yaml"]


def test_negative_cap_rejected(data_dir):
    (data_dir / "settings.yaml").write_text("caps:\n  max_searches_per_run: -1\n")
    with pytest.raises(SettingsError, match="caps.max_searches_per_run"):
        load_settings(data_dir)


@pytest.mark.parametrize("bad", [{"times": ["25:00"]}, {"times": ["7am"]}, {"days": ["monday"]}])
def test_schedule_rejects_bad_values(bad):
    with pytest.raises(ValidationError):
        Schedule(**bad)


def test_schedule_accepts_good_values():
    assert Schedule(days=["mon", "fri"], times=["07:30"]).times == ["07:30"]


def test_applications_path_expands_user(tmp_path):
    assert Settings(applications_dir="~/Apps").applications_path(tmp_path) == Path.home() / "Apps"


def test_skipped_steps_default_empty():
    assert Settings().setup_skipped_steps == []


def test_skip_reasons_are_trimmed_and_other_is_kept():
    assert Settings(skip_reasons=["  Pay  "]).skip_reasons == ["Pay", "Other"]
    assert Settings(skip_reasons=["Other", "Pay"]).skip_reasons == ["Other", "Pay"]
    assert Settings(skip_reasons=["other"]).skip_reasons == ["other"]
    assert Settings().skip_reasons[-1] == "Other"


@pytest.mark.parametrize("bad", [[], ["  "], ["x" * 41], ["Pay", "pay"]])
def test_bad_skip_reasons_are_refused(bad):
    with pytest.raises(ValidationError):
        Settings(skip_reasons=bad)


def test_bad_skip_reasons_in_file_are_a_settings_error(data_dir):
    (data_dir / "settings.yaml").write_text("skip_reasons: ['Pay', 'pay']\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="more than once"):
        load_settings(data_dir)
