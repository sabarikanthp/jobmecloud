from jobmecloud.secrets import delete_secret, get_secret, set_secret


def test_set_get_delete():
    set_secret("provider:p1", "sk-123")
    assert get_secret("provider:p1") == "sk-123"
    delete_secret("provider:p1")
    assert get_secret("provider:p1") is None


def test_delete_missing_is_ok():
    delete_secret("nope")


def test_pasted_key_is_trimmed():
    set_secret("provider:p1", "  sk-123\n")
    assert get_secret("provider:p1") == "sk-123"
