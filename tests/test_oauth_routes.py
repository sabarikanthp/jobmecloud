from urllib.parse import parse_qs, urlparse

import pytest

from jobmecloud.api import routes_oauth

SITE = "https://site.example"
REDIRECT = "https://chatgpt.com/cb"


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("JOBMECLOUD_SITE_URL", SITE)
    routes_oauth.reset_limits()


def register(client, **body):
    body = {"client_name": "ChatGPT", "redirect_uris": [REDIRECT], **body}
    return client.post("/api/oauth/register", json=body)


def authorize(client, client_id, **overrides):
    params = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT, "state": "xyz",
              "code_challenge": "c" * 43, "code_challenge_method": "S256", "scope": "readwrite", **overrides}
    params = {k: v for k, v in params.items() if v is not None}
    return client.get("/api/oauth/authorize", params=params, follow_redirects=False)


def test_protected_resource_document(client):
    for path in ("/.well-known/oauth-protected-resource/api/mcp", "/.well-known/oauth-protected-resource"):
        body = client.get(path).json()
        assert body["resource"] == f"{SITE}/api/mcp"
        assert body["authorization_servers"] == [SITE]
        assert body["scopes_supported"] == ["read", "readwrite"]
        assert body["bearer_methods_supported"] == ["header"]


def test_authorization_server_document(client):
    body = client.get("/.well-known/oauth-authorization-server").json()
    assert body["issuer"] == SITE
    assert body["authorization_endpoint"] == f"{SITE}/api/oauth/authorize"
    assert body["token_endpoint"] == f"{SITE}/api/oauth/token"
    assert body["registration_endpoint"] == f"{SITE}/api/oauth/register"
    assert body["response_types_supported"] == ["code"]
    assert body["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert body["code_challenge_methods_supported"] == ["S256"]
    assert body["token_endpoint_auth_methods_supported"] == ["none"]
    assert body["scopes_supported"] == ["read", "readwrite"]


def test_issuer_comes_from_configuration_not_the_host_header(client):
    body = client.get("/.well-known/oauth-authorization-server", headers={"X-Forwarded-Host": "evil.example"}).json()
    assert body["issuer"] == SITE


def test_register_returns_client_id(client):
    r = register(client)
    assert r.status_code == 201
    body = r.json()
    assert body["client_id"] and body["client_name"] == "ChatGPT" and body["redirect_uris"] == [REDIRECT]
    assert body["token_endpoint_auth_method"] == "none"
    assert "authorization_code" in body["grant_types"] and body["response_types"] == ["code"]


@pytest.mark.parametrize("payload", [
    b"not json", b"[1, 2]", b'{"redirect_uris": "https://x.com/cb"}', b'{"redirect_uris": [1]}', b'{"redirect_uris": []}',
    b'{"redirect_uris": ["http://example.com/cb"]}',
])
def test_register_junk_is_400_not_500(client, payload):
    r = client.post("/api/oauth/register", content=payload, headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client_metadata"


def test_register_bounds_a_huge_name(client):
    assert register(client, client_name="n" * 5000).json()["client_name"] == "n" * 60


def test_register_is_rate_limited(client):
    codes = [register(client).status_code for _ in range(12)]
    assert codes[:10] == [201] * 10 and 429 in codes[10:]


def test_authorize_redirects_to_consent_page(client):
    cid = register(client).json()["client_id"]
    r = authorize(client, cid)
    assert r.status_code == 302
    location = urlparse(r.headers["location"])
    assert f"{location.scheme}://{location.netloc}" == SITE and location.path == "/"
    assert location.fragment.startswith("/connect?")
    query = parse_qs(location.fragment.split("?", 1)[1])
    assert query["client_id"] == [cid] and query["state"] == ["xyz"] and query["redirect_uri"] == [REDIRECT]
    assert query["code_challenge"] == ["c" * 43] and query["scope"] == ["readwrite"]


def test_authorize_never_redirects_to_unregistered_uri(client):
    cid = register(client).json()["client_id"]
    for kwargs in ({"redirect_uri": "https://evil.example/cb"}, {"redirect_uri": None}):
        r = authorize(client, cid, **kwargs)
        assert r.status_code == 400 and "location" not in r.headers
    r = authorize(client, "no-such-client")
    assert r.status_code == 400 and "location" not in r.headers


def test_authorize_problems_go_back_to_the_app_with_an_error(client):
    cid = register(client).json()["client_id"]
    for overrides in ({"code_challenge_method": "plain"}, {"code_challenge": None}, {"response_type": "token"}):
        r = authorize(client, cid, **overrides)
        assert r.status_code == 302
        back = urlparse(r.headers["location"])
        assert f"{back.scheme}://{back.netloc}{back.path}" == REDIRECT
        query = parse_qs(back.query)
        assert query["error"] == ["invalid_request"] and query["state"] == ["xyz"]


def test_unconfigured_site_url_is_a_clear_503(client, monkeypatch):
    monkeypatch.delenv("JOBMECLOUD_SITE_URL")
    for path in ("/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource"):
        r = client.get(path)
        assert r.status_code == 503 and "site_domain" in r.json()["error_description"]


def test_register_hostile_input_is_400_not_500(client):
    bodies = [
        rb'{"client_name": "a\u0000b", "redirect_uris": ["https://x.com/cb"]}',
        rb'{"redirect_uris": ["https://x.com/\u0000"]}',
        ("[" * 100000).encode(),  # nesting deep enough to overflow a recursive parser
        b'{"redirect_uris": ["https://x.com/cb"], "pad": "' + b"a" * 100000 + b'"}',  # far too large
        ('{"redirect_uris": [' + ",".join(f'"https://x.com/{i}"' for i in range(500)) + "]}").encode(),
    ]
    for body in bodies:
        r = client.post("/api/oauth/register", content=body, headers={"Content-Type": "application/json"})
        assert r.status_code == 400, body[:40]
        assert r.json()["error"] == "invalid_client_metadata"


def test_authorize_and_lookup_with_nul_in_client_id_are_clean_errors(client):
    r = authorize(client, "abc\x00def")
    assert r.status_code == 400
    assert client.get("/api/oauth/clients/abc%00def").status_code == 404
