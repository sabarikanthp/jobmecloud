from jobmecloud.jobs.dedup import dedup_key, normalize_employer


def test_normalize_and_keys():
    assert normalize_employer("Acme, Inc.") == normalize_employer("ACME") == "acme"
    assert dedup_key("Acme Inc", "R-12", "Eng", None) == "acme|req:r-12"
    assert dedup_key("Acme", None, "Senior  Eng", "Austin") == "acme|t:senior eng|l:austin"
    assert dedup_key("Acme", None, "Eng", None) == "acme|t:eng|l:"


def test_only_trailing_suffix_words_dropped():
    assert normalize_employer("Co Op Foods Company") == "co op foods"
    assert normalize_employer("  Big   Corp. ") == "big"


def test_fallback_key_and_normalize_url():
    from jobmecloud.jobs.dedup import fallback_key, normalize_url

    assert fallback_key("Acme Inc", "Senior  Eng", "Austin") == "acme|t:senior eng|l:austin"
    assert normalize_url("HTTPS://Jobs.Example/Path/#top") == "https://jobs.example/Path"


def test_normalize_url_never_raises():
    from jobmecloud.jobs.dedup import normalize_url

    assert normalize_url(" http://[Oops/x ") == "http://[oops/x"
    assert normalize_url("https://jobs.example.com／apply") == "https://jobs.example.com／apply"
