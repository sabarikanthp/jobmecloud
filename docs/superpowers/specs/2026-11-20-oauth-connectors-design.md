# Sign-in (OAuth) for ChatGPT and Claude web connectors: design

Date: 2026-11-20. Status: draft for approval.

## Intent and why

The owner wants ChatGPT (and later Claude on web and phone) to connect to JobMeCloud's `/api/mcp` endpoint and do what Claude Desktop already does: review, update and create jobs, statuses and follow-ups (and everything else the existing MCP tools do).

Today `/api/mcp` accepts only a static key (`Authorization: Bearer jmc_...`) checked against the hashed `ApiKey` table. ChatGPT's custom connector cannot send a fixed header; it supports only OAuth. So the endpoint needs a standard OAuth sign-in flow that these clients can discover and use by themselves.

## Goals

- ChatGPT can add `https://<site>/api/mcp` as a connector, sign the owner in, and call every existing tool.
- The owner signs in with the existing Cognito login (password + MFA) and chooses, per connection, **Read only** or **Read and change**.
- Every connection is an ordinary `ApiKey` row, so scopes, rate limits (60/min), the AI-spend cap (30/day), "by Claude: name" history, expiry and the **Revoke** button in Settings, Claude access all apply unchanged.
- Claude on web and phone should work through the same flow (same standard; not separately verified).

## Non-goals

- No change to Claude Desktop keys (`jmc_...`): they keep working exactly as now.
- Single owner only. No multi-user accounts, no OIDC/ID tokens, no third-party sign-in providers.
- No new tools and no new permission levels beyond `read` and `readwrite`.
- No use of Cognito as the OAuth server for connectors (it cannot register clients dynamically).

## Anti-goals (would make this a failure even if it technically works)

- Anyone but the signed-in owner obtaining a token, or a token with more power than the owner approved.
- A connection the owner cannot see and revoke in Settings.
- Weakening the existing key route or exposing any other route without sign-in.

## Constraints

- Stack: FastAPI in one Lambda behind API Gateway HTTP API behind CloudFront (site is a static SPA on S3; `/api/*` goes to the API). Aurora DSQL database; `migrate_db.py` adds missing tables (check whether it adds missing columns before relying on that).
- Every route except `/api/mcp` is behind the Cognito JWT authorizer (`infra/edge.py`).
- The public site address is the OAuth issuer. It must come from configuration, never from request headers (CloudFront forwards the API Gateway host, and a header-derived issuer would be spoofable).
- The owner has a custom domain (`app.jobmecloud.ssrrapps.win`) and the CloudFront address as a second one.

## Approaches considered

- **A. A small OAuth layer in our own API (chosen).** Discovery documents, dynamic client registration, authorize/consent, token endpoint, mapping onto `ApiKey`. Most code, but keeps every existing control and does not depend on what a given client supports.
- B. Cognito as the OAuth server. Less code, but no dynamic registration, uncertain whether ChatGPT accepts a pre-made client id/secret, no per-connection scope choice or Settings revoke. Could end up unusable.
- C. A third-party sign-in service (Auth0, Stytch). Most built-in support, but adds a vendor, a monthly cost and a second place holding the login.

The owner chose A.

## Design

### Flow

1. ChatGPT calls `POST /api/mcp` with no token. The route returns `401` with `WWW-Authenticate: Bearer resource_metadata="https://<site>/.well-known/oauth-protected-resource/api/mcp"`.
2. ChatGPT fetches that document (names this site as the authorization server) and then `/.well-known/oauth-authorization-server` (lists the endpoints below, `code_challenge_methods_supported: ["S256"]`, `token_endpoint_auth_methods_supported: ["none"]`, grant types `authorization_code` and `refresh_token`).
3. ChatGPT registers itself: `POST /api/oauth/register` (RFC 7591), receiving a `client_id`.
4. ChatGPT sends the owner's browser to `https://<site>/connect?client_id=...&redirect_uri=...&state=...&code_challenge=...&code_challenge_method=S256&scope=...`. This is a page in the existing SPA, so the existing Cognito sign-in (with MFA) runs first if the owner is not signed in.
5. The page shows: the app's registered name, the host it will return to, and a choice of **Read only** (default) or **Read and change**, with a clear "Only approve if you just started this from ChatGPT/Claude" line, and Approve / Cancel.
6. Approve calls `POST /api/oauth/approve` (behind the normal Cognito authorizer, so only the signed-in owner can call it). It validates the request, stores a one-time authorization code (hashed, 5 minutes) and returns the redirect URL (`redirect_uri?code=...&state=...`). The page sends the browser there. Cancel returns `error=access_denied`.
7. The client calls `POST /api/oauth/token` with the code and PKCE verifier. The server creates an `ApiKey` row (name like "ChatGPT", scope as approved, expiry) plus an `OAuthGrant` row, and returns an opaque access token and refresh token.
8. `/api/mcp` accepts the access token through the same `verify_key` path as keys (so revoke, expiry, scope and limits all apply).

### Public and protected routes

Public (no Cognito authorizer; each validates itself): `GET /.well-known/oauth-protected-resource/api/mcp`, `GET /.well-known/oauth-authorization-server`, `POST /api/oauth/register`, `POST /api/oauth/token`, `POST /api/mcp` (existing). Protected by the normal authorizer: `POST /api/oauth/approve`, key listing and revoking.

CloudFront needs a behavior sending `/.well-known/*` to the API origin; API Gateway needs a public route for it; the SPA needs a `/connect` route.

### Data (new tables; names are the builder's call)

- `OAuthClient`: client_id, name, redirect_uris (JSON), created_at.
- `OAuthCode`: code_hash, client_id, redirect_uri, code_challenge, scope, expires_at, used_at.
- `OAuthGrant`: api_key_id, client_id, refresh_hash, refresh_expires_at.
- `ApiKey` is unchanged (so no column migration is needed).

### Security rules

- PKCE S256 required; plain not accepted. Public clients only (no client secret).
- Redirect URIs must be `https` (or `http` on localhost/127.0.0.1 only), registered exactly, and matched exactly at authorize and token time.
- Authorization codes: random, stored hashed, single use, 5-minute life; the code is bound to client, redirect URI and challenge. Reuse of a used code is refused and revokes the key created from it.
- Tokens: random, stored hashed, never logged. Access token life 1 hour; refresh token life 30 days, rotated on every use. Revoking the `ApiKey` row ends both.
- Scope granted is exactly what the owner chose on the consent page, never what the client asked for.
- `/register` is unauthenticated by design: cap total registered clients (for example 50) and rate-limit it; validate and bound name and redirect-URI lengths. Registered clients grant nothing until the owner approves.
- Consent page is the only place a code is issued, and `approve` requires the Cognito session, so a stolen client_id alone gets nothing.
- Settings, Claude access lists these connections with their names and a "connected via sign-in" label, and Revoke works.

### Docs and operations

New `docs/chatgpt.md` (how to add the connector, what to expect); update `claude-desktop.md` (the web/phone note), `security.md` and `operations.md` (this adds routes, tables and a CloudFront behavior, so the full update steps including `migrate_db.py` are needed).

## Decided by the owner

- Approach A.
- Same capability as Claude Desktop (read and write for jobs, statuses and follow-ups, and the rest of the existing tools).

## My calls (to check)

- Per-connection read versus read-and-change choice on the consent page, defaulting to read only.
- Access token 1 hour, refresh token 30 days with rotation.
- Consent page lives in the existing SPA at `/connect` instead of a server-rendered page, so it reuses the existing Cognito session and needs no new Cognito client.
- Opaque tokens stored as `ApiKey` rows (not JWTs).
- Client registration capped at about 50 and rate-limited.

## Settled after the builder check (my calls)

- **One stable `ApiKey` row per connection.** A refresh updates the access-token hash in place, never makes a new row, so Settings stays tidy and the 60/min and 30/day limits, history name and revoke all persist. `ApiKey.expires_at` holds the connection's overall life (30 days, pushed forward on each refresh). The 1-hour access-token expiry and the refresh token live on `OAuthGrant` (`access_expires_at`, `refresh_hash`, `refresh_expires_at`), and token verification for OAuth-issued tokens also checks it. Settings therefore shows a connection as active while it keeps being refreshed, not "expired" every hour.
- **Settings listing** joins `OAuthGrant` to show "connected via sign-in" and the app's name; revoke works as today. The list endpoint and Settings UI get a small change.
- **Query string through login:** the `/connect` page saves the pending request (client, redirect, state, challenge) in `sessionStorage` before the Cognito redirect and restores it on return, so a signed-out owner is not dropped. Must be tested.
- **Issuer:** the configured custom domain when `site_domain` is set, else the CloudFront address. The connector must be added with that address. Metadata, `resource_metadata` and redirect checks all use that one value.
- **Client compatibility:** public clients with PKCE and dynamic registration, per the MCP spec. Accept the `resource` parameter (RFC 8707) and ignore it unless it names a different server. ChatGPT is the acceptance target; Claude web and phone are best effort.
- **Scope:** advertise `scopes_supported` as `["read", "readwrite"]`. The token response returns the scope the owner granted, whatever the client asked for. "Read only" means the `ApiKey` scope `read`, with no other mapping.
- **Cleanup:** expired codes are deleted whenever `/token` or `/register` runs. Registered clients that never completed an approval are deleted after 24 hours, and the 50-client cap counts only clients still within that 24 hours or with a grant.
- **401 responses** always carry `WWW-Authenticate: Bearer resource_metadata="..."`. For an expired or revoked token it also carries `error="invalid_token"`, so the client refreshes or restarts the sign-in.

## Left to the builder

Exact table and column names, token prefix (for example `jmo_`), how the site address reaches the Lambda as configuration, how the SPA router and CloudFront fallback handle `/connect`, error response formats, test layout, and whether `migrate_db.py` needs any change to create the new tables.

## Testing

- Unit tests for discovery documents, registration validation and caps, authorize/approve, PKCE success and failure, redirect mismatch, code reuse, expiry, refresh rotation, revoke ending access and refresh, scope enforcement (a read grant cannot call write tools), and that `/approve` rejects unauthenticated calls.
- A test that existing `jmc_` keys still work.
- Manual end-to-end: add the connector in ChatGPT, approve, list jobs, make a change with a read-and-change grant, revoke in Settings and confirm the next call fails.
