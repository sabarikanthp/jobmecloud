import pytest
from fakes import FakeProvider
from fastapi.testclient import TestClient

from jobmecloud.api.app import create_app
from jobmecloud.config.settings import load_settings
from jobmecloud.llm.errors import ProviderUnreachableError
from jobmecloud.secrets import get_secret, set_secret


def _add_provider(client, pid="p1", key=None):
    body = {"id": pid, "kind": "anthropic", "label": "Claude"}
    if key is not None:
        body["api_key"] = key
    return client.put(f"/api/providers/{pid}", json=body)


def test_health(client):
    assert client.get("/api/health").json()["ok"] is True


def test_provider_key_never_returned(client):
    client.put("/api/providers/p1", json={"id": "p1", "kind": "anthropic",
               "label": "Claude", "api_key": " sk-secret\n"})
    body = client.get("/api/providers").text
    assert "sk-secret" not in body and '"has_key":true' in body.replace(" ", "")
    assert get_secret("provider:p1") == "sk-secret"


def test_no_get_response_contains_stored_key(client):
    _add_provider(client, key="sk-topsecret")
    client.put("/api/search", json={"backend": "tavily", "api_key": "tv-topsecret"})
    for path in ["/api/health", "/api/settings", "/api/providers"]:
        text = client.get(path).text
        assert "topsecret" not in text, path
    assert "topsecret" not in client.put("/api/providers/p1", json={"id": "p1"}).text


def test_provider_test_unreachable(data_dir):
    app = create_app(data_dir, provider_builder=lambda c: FakeProvider(raises=ProviderUnreachableError("x")))
    with TestClient(app) as c:
        c.put("/api/providers/p1", json={"id": "p1", "kind": "openai_compatible",
              "label": "Local", "base_url": "http://localhost:11434/v1"})
        r = c.post("/api/providers/p1/test", json={"model": "llama3.1"})
    assert r.status_code == 200 and r.json()["ok"] is False
    assert "Couldn't reach" in r.json()["message"]


def test_provider_test_ok_and_unknown(client):
    _add_provider(client)
    r = client.post("/api/providers/p1/test", json={"model": "m"})
    assert r.json() == {"ok": True, "message": "Connected. The model replied."}
    r = client.post("/api/providers/nope/test", json={"model": "m"})
    assert r.status_code == 404 and r.json() == {"detail": "No provider with that id"}


def test_delete_provider_removes_key_and_steps(client, data_dir):
    _add_provider(client, "p1", key="sk-1")
    _add_provider(client, "p2", key="sk-2")
    s = client.get("/api/settings").json()
    s["steps"] = {"score": {"provider_id": "p1", "model": "m"},
                  "tailor": {"provider_id": "p2", "model": "m"}}
    assert client.put("/api/settings", json=s).status_code == 200
    assert client.delete("/api/providers/p1").status_code == 204
    settings = load_settings(data_dir)
    assert [p.id for p in settings.providers] == ["p2"]
    assert list(settings.steps) == ["tailor"]
    assert get_secret("provider:p1") is None
    assert get_secret("provider:p2") == "sk-2"


def test_blank_key_means_no_change(client):
    _add_provider(client, key="sk-keep")
    _add_provider(client, key="   ")
    assert get_secret("provider:p1") == "sk-keep"
    assert client.get("/api/providers").json()[0]["has_key"] is True
    _add_provider(client, "p2", key="  ")
    assert get_secret("provider:p2") is None


def test_put_provider_replaces_and_rejects_id_mismatch(client):
    _add_provider(client)
    client.put("/api/providers/p1", json={"id": "p1", "kind": "anthropic", "label": "New"})
    providers = client.get("/api/providers").json()
    assert len(providers) == 1 and providers[0]["label"] == "New"
    r = client.put("/api/providers/p1", json={"id": "other", "kind": "anthropic", "label": "x"})
    assert r.status_code == 422


def test_put_settings_invalid_is_422(client):
    s = client.get("/api/settings").json()
    s["match_cutoff"] = 500
    assert client.put("/api/settings", json=s).status_code == 422


def test_search_builtin(client):
    r = client.put("/api/search", json={"backend": "builtin"})
    assert r.json() == {"backend": "builtin", "has_key": False}
    r = client.post("/api/search/test")
    assert r.json() == {"ok": True,
                        "message": "Built-in search is used with Claude. Nothing to test."}


def test_search_tavily_without_key_is_200_not_500(client):
    assert client.put("/api/search", json={"backend": "tavily"}).json() == {
        "backend": "tavily", "has_key": False}
    r = client.post("/api/search/test")
    assert r.status_code == 200 and r.json() == {"ok": False, "message": "No search key saved"}


def test_search_key_stored_trimmed(client):
    r = client.put("/api/search", json={"backend": "brave", "api_key": " bk \n"})
    assert r.json() == {"backend": "brave", "has_key": True}
    assert get_secret("search:brave") == "bk"
    assert client.get("/api/settings").json()["search_backend"] == "brave"


def test_bad_settings_file_returns_400(data_dir):
    (data_dir / "settings.yaml").write_text("match_cutoff: lots\n")
    with TestClient(create_app(data_dir)) as c:
        r = c.get("/api/settings")
    assert r.status_code == 400 and "match_cutoff" in r.json()["detail"]


def test_bad_settings_file_400_on_provider_and_search_routes(data_dir):
    (data_dir / "settings.yaml").write_text("match_cutoff: lots\n")
    with TestClient(create_app(data_dir)) as c:
        for r in [c.get("/api/providers"), c.post("/api/search/test"),
                  c.post("/api/providers/p1/test", json={"model": "m"})]:
            assert r.status_code == 400 and "match_cutoff" in r.json()["detail"]
        assert c.get("/api/health").status_code == 200


def test_create_app_none_uses_default_data_dir(data_dir):
    with TestClient(create_app()) as c:
        c.get("/api/health")
    assert (data_dir / "jobmecloud.db").exists()


def test_changing_base_url_without_key_removes_stored_key(client):
    client.put("/api/providers/p1", json={"id": "p1", "kind": "openai_compatible",
               "label": "L", "base_url": "http://a/v1", "api_key": "sk-old"})
    r = client.put("/api/providers/p1", json={"id": "p1", "kind": "openai_compatible",
                   "label": "L", "base_url": "http://evil.example/v1"})
    assert r.json()["has_key"] is False
    assert get_secret("provider:p1") is None


def test_changing_kind_without_key_removes_stored_key(client):
    _add_provider(client, key="sk-old")
    r = client.put("/api/providers/p1", json={"id": "p1", "kind": "openai_compatible",
                   "label": "Claude"})
    assert r.json()["has_key"] is False


def test_changing_base_url_with_new_key_stores_new_key(client):
    client.put("/api/providers/p1", json={"id": "p1", "kind": "openai_compatible",
               "label": "L", "base_url": "http://a/v1", "api_key": "sk-old"})
    client.put("/api/providers/p1", json={"id": "p1", "kind": "openai_compatible",
               "label": "L", "base_url": "http://b/v1", "api_key": "sk-new"})
    assert get_secret("provider:p1") == "sk-new"


def test_changing_label_only_keeps_key(client):
    _add_provider(client, key="sk-keep")
    r = client.put("/api/providers/p1", json={"id": "p1", "kind": "anthropic",
                   "label": "Renamed"})
    assert r.json()["has_key"] is True
    assert get_secret("provider:p1") == "sk-keep"


def test_unknown_host_header_is_rejected(client):
    assert client.get("/api/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/health", headers={"Host": "localhost:8000"}).status_code == 200


def test_provider_test_builder_failure_is_plain_result(data_dir):
    def boom(_cfg):
        raise RuntimeError("no good")
    with TestClient(create_app(data_dir, provider_builder=boom)) as c:
        _add_provider(c)
        r = c.post("/api/providers/p1/test", json={"model": "m"})
    assert r.status_code == 200
    assert r.json() == {"ok": False, "message": "Something went wrong: no good"}


def test_validation_error_does_not_echo_api_key(client):
    r = client.put("/api/providers/p1", json={"id": "p1", "kind": "bogus",
                   "label": "x", "api_key": "sk-x"})
    assert r.status_code == 422
    assert "sk-x" not in r.text


def test_get_search_reports_saved_state(client):
    assert client.get("/api/search").json() == {"backend": "builtin", "has_key": False}
    client.put("/api/search", json={"backend": "brave", "api_key": "bk-secret"})
    r = client.get("/api/search")
    assert r.json() == {"backend": "brave", "has_key": True}
    assert "bk-secret" not in r.text
    client.put("/api/search", json={"backend": "tavily"})
    assert client.get("/api/search").json() == {"backend": "tavily", "has_key": False}
    client.put("/api/search", json={"backend": "builtin"})
    assert client.get("/api/search").json() == {"backend": "builtin", "has_key": False}
