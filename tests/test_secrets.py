import boto3

from jobmecloud.secrets import delete_secret, get_secret, set_secret


def test_set_get_delete():
    set_secret("provider:p1", "sk-123")
    assert get_secret("provider:p1") == "sk-123"
    delete_secret("provider:p1")
    assert get_secret("provider:p1") is None


def test_get_missing_returns_none():
    assert get_secret("provider:never-saved") is None


def test_delete_missing_is_ok():
    delete_secret("nope")


def test_pasted_key_is_trimmed():
    set_secret("provider:p1", "  sk-123\n")
    assert get_secret("provider:p1") == "sk-123"


def test_stored_as_secure_string_under_the_app_path():
    set_secret("search:tavily", "tvly-1")
    param = boto3.client("ssm").get_parameter(Name="/jobmecloud/search/tavily")["Parameter"]
    assert param["Type"] == "SecureString"


def test_overwriting_replaces_the_value():
    set_secret("provider:p1", "old")
    set_secret("provider:p1", "new")
    assert get_secret("provider:p1") == "new"
