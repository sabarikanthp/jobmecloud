# OAuth Sign-in for ChatGPT / Claude Connectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let ChatGPT (and Claude web/phone) connect to `/api/mcp` through a standard OAuth sign-in, with the same tools and the same safety controls as a Claude Desktop key.

**Architecture:** A small OAuth layer inside the existing FastAPI app: discovery documents, dynamic client registration, an authorize redirect to a consent page in the SPA, an owner-only approve call, and a token endpoint. Each approved connection becomes one stable `ApiKey` row (so scope, limits, history and Revoke are reused) plus an `OAuthGrant` row holding the short-lived access expiry and the rotating refresh token.

**Tech Stack:** Python 3.12, FastAPI, SQLModel (SQLite locally, Aurora DSQL deployed), pytest; React + TypeScript + vitest; AWS CDK (API Gateway HTTP API, CloudFront).

**Spec:** [docs/superpowers/specs/2026-11-20-oauth-connectors-design.md](../specs/2026-11-20-oauth-connectors-design.md)

## Global Constraints

- PKCE `S256` only; public clients only (`token_endpoint_auth_methods_supported: ["none"]`); grant types `authorization_code` and `refresh_token`.
- Redirect URIs: `https`, or `http` only for `localhost`/`127.0.0.1`; registered exactly, matched exactly at authorize and token time.
- Authorization code: random, stored hashed, single use, 5-minute life. Reuse revokes the key created from it.
- Access token: opaque, prefix `jmo_`, 1-hour life. Refresh token: opaque, 30-day life, rotated on every use. Both stored hashed, never logged.
- `ApiKey.expires_at` = the connection's overall life (30 days, pushed forward on each refresh). Access expiry and refresh data live on `OAuthGrant`. One `ApiKey` row per connection; a refresh updates it in place.
- Scope granted is exactly what the owner chose (`read` default, or `readwrite`), whatever the client asked for. `scopes_supported` is `["read", "readwrite"]`.
- Issuer = the configured public site address (env `JOBMECLOUD_SITE_URL`, no trailing slash), never taken from request headers.
- `/api/oauth/register` is unauthenticated: cap about 50 clients, rate-limit, bound name (60 chars) and redirect URI lengths. Clients that never completed an approval are deleted after 24 hours; expired codes are deleted whenever `/token` or `/register` runs.
- Every 401 from `/api/mcp` carries `WWW-Authenticate: Bearer resource_metadata="<site>/.well-known/oauth-protected-resource/api/mcp"`; an expired or revoked token adds `error="invalid_token"`.
- Existing `jmc_` keys keep working unchanged. Rate limit 60/min and AI cap 30/day stay per `ApiKey` row.
- Only `/.well-known/*`, `/api/oauth/register`, `/api/oauth/authorize`, `/api/oauth/token` and the existing `POST /api/mcp` bypass the Cognito authorizer. `/api/oauth/approve` and `/api/oauth/clients/{client_id}` stay behind it.

## Review Focus

1. Authorize with an unregistered or non-matching `redirect_uri` must show an error and never redirect (no open redirect). Pinned in Task 3.
2. Wrong PKCE verifier, reused code, mismatched redirect URI, or a refresh token used after it was rotated: `invalid_grant`, nothing issued; code reuse also revokes the key it created. Pinned in Task 4.
3. A signed-out owner opening the consent link must come back to the same request after Cognito login (query string intact). Pinned in Task 6.
4. Registration with junk JSON, an `http://example.com` redirect, oversized fields, or past the client cap: clean 400, no 500. Pinned in Task 1 and 3.
5. A read-only OAuth grant calling a write tool, an expired access token, and a revoked connection are all refused, and refresh fails after revoke. Pinned in Task 2 and 4.

---

### Task 1: Tables and OAuth store

**Files:**
- Modify: `backend/jobmecloud/db/models.py` (add three tables after `ApiKey`)
- Create: `backend/jobmecloud/oauth/__init__.py`, `backend/jobmecloud/oauth/store.py`
- Test: `tests/test_oauth_store.py`

**Interfaces:**
- Produces, models (use `pk_column()`, nullable columns as `ApiKey` does, a JSON column for the URI list as other models do):
  - `OAuthClient(client_id: str unique, name: str, redirect_uris: list[str], created_at: datetime)`
  - `OAuthCode(code_hash: str unique, client_id: str, redirect_uri: str, code_challenge: str, scope: str, expires_at: datetime, used_at: datetime | None, api_key_id: int | None)`
  - `OAuthGrant(api_key_id: int unique, client_id: str, access_expires_at: datetime, refresh_hash: str unique, refresh_expires_at: datetime)`
- Produces, in `oauth/store.py`:
  - `class OAuthError(Exception)` with `.code: str` and `.description: str` (codes: `invalid_client_metadata`, `invalid_request`, `invalid_grant`, `invalid_client`)
  - `@dataclass Tokens(access_token: str, refresh_token: str, expires_in: int, scope: str)`
  - `register_client(session, *, name: str, redirect_uris: list[str], now: datetime) -> OAuthClient`
  - `get_client(session, client_id: str) -> OAuthClient | None`
  - `check_redirect(client: OAuthClient, redirect_uri: str) -> bool` (exact match)
  - `issue_code(session, *, client: OAuthClient, redirect_uri: str, code_challenge: str, scope: str, now: datetime) -> str`
  - `exchange_code(session, *, client_id: str, code: str, redirect_uri: str, verifier: str, now: datetime) -> Tokens`
  - `refresh(session, *, client_id: str, refresh_token: str, now: datetime) -> Tokens`
  - `access_valid(session, key: ApiKey, now: datetime) -> bool` (True when the key's grant exists and `access_expires_at > now`)
  - constants `OAUTH_PREFIX = "jmo_"`, `MAX_CLIENTS = 50`

- [ ] **Step 1: Write failing tests** in `tests/test_oauth_store.py` using the `client` fixture's engine (see `tests/test_api_keys_store.py` for session setup). Tests, each with the stated assertions:
  - `test_register_rejects_bad_redirects`: `http://example.com/cb`, `javascript:x`, empty list, and a 3000-char URI each raise `OAuthError` with code `invalid_client_metadata`; `https://chatgpt.com/cb` and `http://localhost:8080/cb` succeed.
  - `test_register_caps_clients`: the 51st registration within 24 hours raises `invalid_client_metadata`; after 25 hours a client with no grant is pruned and registration succeeds again.
  - `test_code_exchange_happy_path`: `issue_code` then `exchange_code` with the S256 verifier returns `Tokens` whose `access_token` starts with `jmo_`, `expires_in == 3600`, `scope` equals the approved scope; an `ApiKey` row exists with that scope, `expires_at == now + 30 days`, name containing the client name; `verify_key` (from `keys.store`) accepts the access token.
  - `test_code_is_single_use_and_revokes`: a second `exchange_code` with the same code raises `invalid_grant` and sets `revoked_at` on the key the first exchange created.
  - `test_exchange_rejects_wrong_verifier_redirect_and_expiry`: wrong verifier, different `redirect_uri`, other `client_id`, and a code 6 minutes old each raise `invalid_grant`.
  - `test_refresh_rotates_in_place`: `refresh` returns a new access and refresh token, the same `ApiKey.id`, the old access token no longer verifies, the old refresh token raises `invalid_grant`, `ApiKey.expires_at` moves to `now + 30 days`.
  - `test_refresh_refused_after_revoke_or_expiry`: revoked key and a refresh token past 30 days raise `invalid_grant`.
  - `test_access_valid`: true within the hour, false after.

- [ ] **Step 2: Run** `uv run pytest tests/test_oauth_store.py -v`. Expected: FAIL (module missing).

- [ ] **Step 3: Implement the models and store.** Generate tokens with `secrets.token_urlsafe(32)`; hash with sha256 hex (reuse `keys.store._hash`, exposing it as `keys.store.hash_token` if needed). Create the `ApiKey` row directly (scope from the code, `prefix=token[:8]`). Validate PKCE with `base64url(sha256(verifier)) == code_challenge` using `hmac.compare_digest`. Delete expired codes and unapproved clients older than 24 hours inside `register_client` and `exchange_code`.

- [ ] **Step 4: Run** `uv run pytest tests/test_oauth_store.py tests/test_models.py tests/test_migrate.py -v`. Expected: PASS (migrate creates the new tables).

- [ ] **Step 5: Commit** `git add backend tests && git commit -m "feat: OAuth tables and store"`.

### Task 2: Accept OAuth tokens on /api/mcp and add the 401 header

**Files:**
- Modify: `backend/jobmecloud/api/routes_mcp.py`
- Test: `tests/test_mcp_oauth_auth.py` (reuse helpers from `tests/test_mcp_endpoint.py`: `rpc`, `dummy_tools` pattern)

**Interfaces:**
- Consumes: `oauth.store.OAUTH_PREFIX`, `oauth.store.access_valid`, `keys.store.verify_key`.
- Produces: `oauth.store.www_authenticate(*, invalid_token: bool) -> str` (builds the header value from `site_url()`); `oauth.store.site_url() -> str` (reads `JOBMECLOUD_SITE_URL`; raises `OAuthError("invalid_request", ...)` if unset).

- [ ] **Step 1: Write failing tests:**
  - `test_oauth_token_works_like_a_key`: after a code exchange, `tools/list` and an `echo` call succeed with the `jmo_` token.
  - `test_read_grant_cannot_use_write_tools`: with a `read` grant, calling a write tool returns the same refusal text the existing read-only key test asserts.
  - `test_expired_access_token_gets_401_invalid_token`: after 61 minutes, 401 and the `WWW-Authenticate` header contains `error="invalid_token"` and the `resource_metadata` URL.
  - `test_no_token_gets_401_with_metadata_header` (no `error=` part), `test_revoked_connection_401`.
  - `test_desktop_keys_unchanged`: existing `jmc_` key still works; an expired `jmc_` key gets 401.

- [ ] **Step 2: Run** `uv run pytest tests/test_mcp_oauth_auth.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement.** In `mcp()` after `verify_key`, if the presented token starts with `OAUTH_PREFIX` also require `access_valid`. Replace the bare `Response(status_code=401)` with one carrying the header. Set `JOBMECLOUD_SITE_URL` in the tests with `monkeypatch.setenv`.

- [ ] **Step 4: Run** `uv run pytest tests/test_mcp_oauth_auth.py tests/test_mcp_endpoint.py tests/test_mcp_review_fixes.py -v`. Expected: PASS.

- [ ] **Step 5: Commit** `feat: accept OAuth access tokens on the MCP route`.

### Task 3: Discovery, registration and authorize routes

**Files:**
- Create: `backend/jobmecloud/api/routes_oauth.py` (two routers: `well_known` mounted at root, `router` mounted at `/api`)
- Modify: `backend/jobmecloud/api/app.py` (include both routers, next to `routes_mcp`)
- Test: `tests/test_oauth_routes.py`

**Interfaces:**
- Consumes: `oauth.store.register_client`, `get_client`, `check_redirect`, `site_url`, `OAuthError`.
- Produces HTTP:
  - `GET /.well-known/oauth-protected-resource/api/mcp` and `/.well-known/oauth-protected-resource` → `{"resource": "<site>/api/mcp", "authorization_servers": ["<site>"], "scopes_supported": ["read","readwrite"], "bearer_methods_supported": ["header"]}`
  - `GET /.well-known/oauth-authorization-server` → `issuer`, `authorization_endpoint` (`<site>/api/oauth/authorize`), `token_endpoint` (`<site>/api/oauth/token`), `registration_endpoint` (`<site>/api/oauth/register`), `response_types_supported ["code"]`, `grant_types_supported ["authorization_code","refresh_token"]`, `code_challenge_methods_supported ["S256"]`, `token_endpoint_auth_methods_supported ["none"]`, `scopes_supported ["read","readwrite"]`
  - `POST /api/oauth/register` JSON `{client_name, redirect_uris, ...}` → 201 `{client_id, client_name, redirect_uris, token_endpoint_auth_method: "none", grant_types, response_types}`; errors 400 `{"error": "invalid_client_metadata", "error_description": ...}`; rate-limited (reuse the in-memory pattern in `routes_mcp._too_fast`, 10 a minute overall)
  - `GET /api/oauth/authorize?response_type=code&client_id&redirect_uri&state&code_challenge&code_challenge_method=S256&scope&resource` → 302 to `<site>/#/connect?client_id=...&redirect_uri=...&state=...&code_challenge=...&scope=...` (values URL-encoded); an unknown client or non-matching redirect → 400 with a plain error page (never a redirect); other problems (missing challenge, method not S256, response_type not `code`) → 302 back to the registered `redirect_uri` with `error=invalid_request` and the `state`

- [ ] **Step 1: Write failing tests** (with `JOBMECLOUD_SITE_URL=https://site.example` monkeypatched): `test_protected_resource_document`, `test_authorization_server_document` (assert each field above), `test_register_returns_client_id`, `test_register_junk_body_is_400_not_500` (non-JSON, list instead of object, huge name, `http://example.com`), `test_register_rate_limited`, `test_authorize_redirects_to_consent_page` (Location starts with `https://site.example/#/connect?` and contains the client_id, state and challenge), `test_authorize_never_redirects_to_unregistered_uri` (status 400, no Location), `test_authorize_requires_s256` (302 to the redirect URI with `error=invalid_request`), `test_unconfigured_site_url_is_clear_503`.

- [ ] **Step 2: Run** `uv run pytest tests/test_oauth_routes.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement** the routes. `register` accepts `redirect_uris` and `client_name` and ignores other fields. Map `OAuthError` to the JSON error body.

- [ ] **Step 4: Run** `uv run pytest tests/test_oauth_routes.py tests/test_api.py -v`. Expected: PASS.

- [ ] **Step 5: Commit** `feat: OAuth discovery, registration and authorize routes`.

### Task 4: Approve, client lookup and token endpoint

**Files:**
- Modify: `backend/jobmecloud/api/routes_oauth.py`
- Test: `tests/test_oauth_flow.py`

**Interfaces:**
- Consumes: Task 1 store functions.
- Produces HTTP:
  - `GET /api/oauth/clients/{client_id}` → `{"name": str, "redirect_hosts": [str]}` (404 if unknown). Owner-only (behind the authorizer, see Task 7).
  - `POST /api/oauth/approve` JSON `{client_id, redirect_uri, state, code_challenge, scope: "read" | "readwrite", approve: bool}` → `{"redirect_to": str}`: with `approve: true` a URL `redirect_uri?code=...&state=...`; with `false` `redirect_uri?error=access_denied&state=...`. Revalidates client, redirect URI and challenge; `scope` outside `read`/`readwrite` is 422.
  - `POST /api/oauth/token`, form-encoded (parse `request.body()` with `urllib.parse.parse_qs`; do not add a dependency): `grant_type=authorization_code` with `client_id, code, redirect_uri, code_verifier`, or `grant_type=refresh_token` with `client_id, refresh_token`. Success 200 `{access_token, token_type: "Bearer", expires_in: 3600, refresh_token, scope}` with `Cache-Control: no-store`; failure 400 `{"error", "error_description"}`. Ignore a `resource` field.

- [ ] **Step 1: Write failing tests** driving the whole flow through `TestClient`: `test_full_flow_then_mcp_call` (register → authorize → approve (read) → token → `tools/list` on `/api/mcp` with the access token → refresh → old refresh rejected → new access works); `test_scope_is_what_the_owner_chose` (client asks `scope=readwrite`, owner approves `read`, token response says `read`); `test_deny_returns_access_denied`; `test_approve_rejects_bad_scope_and_unregistered_redirect`; `test_token_rejects_wrong_verifier_and_code_reuse` (second use → `invalid_grant`, and the key from the first use is revoked so its token now gets 401); `test_refresh_after_revoke_fails` (revoke through `DELETE /api/keys/{id}`); `test_token_is_no_store_and_never_logs_tokens` (caplog contains neither token).

- [ ] **Step 2: Run** `uv run pytest tests/test_oauth_flow.py -v`. Expected: FAIL.

- [ ] **Step 3: Implement** the three endpoints over the store functions. `redirect_hosts` is the host part of each registered redirect URI.

- [ ] **Step 4: Run** `uv run pytest tests/test_oauth_flow.py tests/test_oauth_store.py tests/test_oauth_routes.py -v`. Expected: PASS.

- [ ] **Step 5: Commit** `feat: OAuth approve and token endpoints`.

### Task 5: Settings list shows connections

**Files:**
- Modify: `backend/jobmecloud/api/routes_keys.py`, `frontend/src/api.ts`, `frontend/src/sections/ClaudeAccessSection.tsx`
- Test: `tests/test_api_keys_routes.py` (add), `frontend/src/sections/ClaudeAccessSection.test.tsx` (add)

**Interfaces:**
- Produces: `KeyOut` gains `via: Literal["key", "sign-in"]` (sign-in when an `OAuthGrant` exists for the row) and `app_name: str | None` (the registered client name); `api.ts` `ApiKeyRow` gains the same two fields.

- [ ] **Step 1: Write failing tests:** backend `test_list_marks_sign_in_connections` (an OAuth-created connection lists `via == "sign-in"` and the app name; a `jmc_` key lists `via == "key"`); frontend: a sign-in row shows the text "Connected via sign-in" and the app name, a key row does not, and both have a Revoke button.
- [ ] **Step 2: Run** `uv run pytest tests/test_api_keys_routes.py -v` and `cd frontend && npm test -- ClaudeAccessSection`. Expected: FAIL.
- [ ] **Step 3: Implement** the join in `list_keys` and the label in the section. A sign-in row's "expires" shows the connection's `expires_at` like any key.
- [ ] **Step 4: Run** the same commands. Expected: PASS.
- [ ] **Step 5: Commit** `feat: show OAuth connections in Settings`.

### Task 6: Consent page

**Files:**
- Create: `frontend/src/pages/Connect.tsx`, `frontend/src/pages/Connect.test.tsx`
- Modify: `frontend/src/App.tsx` (render `Connect` instead of the normal pages when the hash starts with `#/connect`, after the sign-in gate), `frontend/src/api.ts`

**Interfaces:**
- Produces in `api.ts`: `getOAuthClient(clientId: string): Promise<{name: string; redirect_hosts: string[]}>` and `approveOAuth(body: {client_id; redirect_uri; state; code_challenge; scope: 'read' | 'readwrite'; approve: boolean}): Promise<{redirect_to: string}>`.
- Produces: `Connect` page reading `client_id, redirect_uri, state, code_challenge` from the query part of the hash (`#/connect?...`), showing the app name and the host it returns to, a choice **Read only** (default) / **Read and change**, the line "Only approve if you just started this from ChatGPT or Claude", and **Approve** / **Cancel** buttons; on either it calls `approveOAuth` then `window.location.assign(redirect_to)` (go through a replaceable `nav.to`-style object as `auth.ts` does, so tests can assert it).
- Sign-in: `rememberWhere()` in `auth.ts` already keeps any hash starting `#/`, so the `#/connect?...` address survives the Cognito trip; add a test proving it.

- [ ] **Step 1: Write failing tests:** shows client name and host; defaults to Read only; Approve with Read and change sends `scope: 'readwrite'` and navigates to `redirect_to`; Cancel sends `approve: false`; unknown client shows an error and no buttons; missing `client_id` shows "This link is not valid"; in `auth.test.ts`, `rememberWhere` + `restoreWhere` round-trips a `#/connect?client_id=abc&state=x%20y` hash unchanged.
- [ ] **Step 2: Run** `cd frontend && npm test -- Connect auth`. Expected: FAIL.
- [ ] **Step 3: Implement** the page and wire it in `App.tsx`; `route.ts` is not changed (connect is not a nav page).
- [ ] **Step 4: Run** `cd frontend && npm test && npm run build`. Expected: PASS, build succeeds.
- [ ] **Step 5: Commit** `feat: OAuth consent page`.

### Task 7: Infrastructure

**Files:**
- Modify: `infra/edge.py`, `infra/jobmecloud_stack.py`
- Test: `tests/infra/` (follow the existing test there; add `test_oauth_routes_public.py`)

**Interfaces:**
- Produces: public API Gateway routes (no authorizer) `GET /.well-known/{proxy+}`, `POST /api/oauth/register`, `GET /api/oauth/authorize`, `POST /api/oauth/token`; a CloudFront behavior `/.well-known/*` to the API origin (GET/HEAD, caching disabled, same origin request policy as `/api/*`); Lambda env `JOBMECLOUD_SITE_URL = https://<site_domain>` set on the API function only when `site_domain` is given (it cannot reference the CloudFront address without a circular dependency; without a custom domain the OAuth routes return a clear "set site_domain" error, documented in Task 8).

- [ ] **Step 1: Write failing infra tests** (synthesize the stack as the neighbours do): the four routes exist with `AuthorizationType NONE`; `POST /api/oauth/approve` and `GET /api/oauth/clients/{id}` are only matched by the authorized `/api/{proxy+}` route; the distribution has a `/.well-known/*` behavior; with `site_domain` set, the API function env has `JOBMECLOUD_SITE_URL`.
- [ ] **Step 2: Run** `uv run pytest tests/infra -v`. Expected: FAIL.
- [ ] **Step 3: Implement** in `edge.py` and pass the env in `jobmecloud_stack.py`. Update the comment above the `/api/mcp` route to describe the other public routes.
- [ ] **Step 4: Run** `uv run pytest tests/infra -v`, then `cdk diff` with the owner's `-c` values (see operations.md; recover them with the AWS lookups used for the last deploy). Expected: only new routes, a new behavior and one env var change.
- [ ] **Step 5: Commit** `feat: public OAuth routes and CloudFront behavior`.

### Task 8: Docs, full test run, deploy and live check

**Files:**
- Create: `docs/chatgpt.md`
- Modify: `docs/claude-desktop.md` (replace the "web and phone do not accept a key" note), `docs/security.md` (the new public routes and what protects each), `docs/operations.md` (this update needs `migrate_db.py`, new routes, a CloudFront behavior)

- [ ] **Step 1: Write the docs.** `chatgpt.md`: add the connector in ChatGPT with `https://<site_domain>/api/mcp`, sign in, choose Read only first, what each choice allows, how to revoke, requires `site_domain`.
- [ ] **Step 2: Run everything:** `uv run pytest -q` and `cd frontend && npm test && npm run build`. Expected: all pass.
- [ ] **Step 3: Deploy** per operations.md with the owner's real `-c` values; show the `cdk diff` to the owner and wait for approval before `cdk deploy`; then `migrate_db.py`, frontend build, `publish_site.py`.
- [ ] **Step 4: Live check with the owner:** `curl https://<site_domain>/.well-known/oauth-authorization-server` returns the document; add the connector in ChatGPT, approve as Read only, ask it to list jobs; revoke in Settings and confirm the next call fails; repeat once with Read and change and a status update.
- [ ] **Step 5: Commit** `docs: ChatGPT connector`.
