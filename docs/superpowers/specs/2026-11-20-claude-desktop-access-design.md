# Claude Desktop access (API keys + MCP endpoint) — design

Date: 2026-11-20. Status: awaiting approval.

## Intent and why

The owner checks job fit in existing Claude Desktop chats. They want those chats to reach JobMe directly: reference a job, read everything about it, and continue the conversation there — and also act on JobMe from the chat (update status, notes, contacts, follow-ups, interviews, check a new posting). Today the API accepts only a signed-in Cognito token, so nothing outside the website can call it.

## Goals

- A **Settings → Claude access** section to create, name, scope, expire and revoke API keys. A key is shown once.
- An **MCP endpoint** (`/api/mcp`) that Claude Desktop connects to using a key, exposing JobMe as tools.
- Full two-way use: read jobs, resume/profile, follow-ups, contacts, interviews, dashboard; write status, notes, contacts, follow-ups, interviews; add and check jobs.
- A **"Copy for Claude"** button on each job (and contact/follow-up) that copies a short reference such as `JobMe job 123: Acme – Staff Engineer`; pasting it into a chat lets Claude fetch it with `get_job`.
- Everything the chat changes behaves exactly like the same change in the app (same validation, same status history/activity), and is marked as made via Claude.

## Non-goals

- No claude.ai browser/mobile connector (those need OAuth, not keys). Claude Desktop only.
- No deleting anything from chat (jobs, contacts, interviews, follow-up deletion beyond the app's normal "cancel").
- No access to settings, provider/search API keys, or key management through `/api/mcp`.
- JobMe does not generate documents on behalf of the chat (the existing Make docs stays in the app). Documents written in chat are **attached** to a job instead (see Attaching documents).
- No multi-user model; one owner.

## Anti-goals (failure even if it works)

- A leaked or over-trusted key becoming a way to read secrets or wipe data.
- Posting text (untrusted) steering a write-capable chat into harmful edits without the user noticing.
- Existing app routes losing their Cognito protection.

## Constraints

- AWS deployment: API Gateway JWT authorizer fronts every route; Lambda + Aurora DSQL + S3 workspace (see `docs/security.md`, `infra/edge.py`).
- Lambda is stateless: MCP must use stateless streamable HTTP with JSON responses (no sessions, no SSE streams held open).
- Existing patterns: FastAPI routers in `backend/jobmecloud/api/`, SQLModel tables in `db/models.py`, migrations in `db/migrate.py`.

## Approaches considered

- **A. MCP endpoint inside the existing API (chosen by the owner).** One new router + one key table; the authorizer is skipped for `/api/mcp` only and the app checks the key. Fewest moving parts; reuses existing logic.
- B. Separate MCP Lambda with its own DB role. Cleaner isolation, but new infra and duplicated logic; slowest.
- C. REST + a locally installed script. Fragile on the user's machine, less structured for the chat.

## Design

**Keys.** New table `api_key`: id, name, prefix (first 8 chars, for display), sha256 hash, scope (`read` | `readwrite`), created_at, expires_at (nullable), last_used_at, revoked_at. Key format `jmc_` + 32 random bytes base64url. Only the hash is stored; the full key is returned once on creation. Comparison is constant-time. Key management routes (`GET/POST /api/keys`, `DELETE /api/keys/{id}`) sit behind the normal Cognito check, so a key can never create or revoke keys.

**Auth on `/api/mcp`.** `Authorization: Bearer jmc_…`. Rejects missing, unknown, revoked, expired keys (401, no detail). Write tools require scope `readwrite` (otherwise a clear tool error). Per-key rate limit (default 60 requests/min) and a daily cap on tools that spend AI money (`check_job`, `re_evaluate_job`; default 30/day). Updates `last_used_at`. API Gateway gets one extra route for `/api/mcp` without the JWT authorizer; all other routes unchanged.

**Transport.** MCP streamable HTTP, stateless, JSON responses. Implemented with the official MCP Python SDK if it fits Lambda cleanly, otherwise a minimal JSON-RPC handler (`initialize`, `tools/list`, `tools/call`) — builder's call.

**Tools** (each calls the existing route/service logic so behaviour is identical; implemented by in-process dispatch to the routers, not by copying logic):

| Read (any key) | Write (`readwrite` key) |
|---|---|
| `list_jobs` (filters: status, text, score) | `set_job_status` (incl. skip reason, duplicate_of) |
| `get_job` (id or URL/ref: posting, fit, gaps, flags, status, notes, contacts, follow-ups, interviews, history) | `update_job` (notes, applied/response/outcome dates) |
| `get_resume_context` (resume + profile text) | `add_job` (manual) |
| `get_dashboard` | `check_job` (paste text or URL → existing fit check) |
| `list_followups` (bucket filter) | `re_evaluate_job` (new pasted description) |
| `list_contacts` | `create_followup`, `complete_followup`, `snooze_followup`, `reschedule_followup`, `cancel_followup` |
| | `create_contact`, `update_contact` |
| | `add_interview`, `update_interview` |
| `get_job_documents` (the job's attached resume / cover letter, as text) | `attach_documents` (resume and/or cover letter written in chat) |

Not exposed: any delete, settings, provider/search keys, key management, document generation.

**Attaching documents.** `attach_documents(job_id, resume?, cover_letter?)` stores what was written in chat in the job's existing documents folder, so the job page's Open/Download buttons, the follow-up flow and `get_job_documents` all work on it. Each document is either plain text/markdown, or a base64 `.docx`/`.pdf` (capped at about 3 MB so it fits the Lambda request limit). Text is saved as-is (`resume.md`, `cover-letter.md`); the builder should also produce a `.docx` from it when the existing renderer can do so cheaply, and otherwise leave that as a later step. Existing files are archived first, exactly as Make docs does, so nothing is overwritten silently. The job's docs status becomes ready and its page note records "Attached from Claude (key name)". Content is size-limited, filename-fixed (never taken from the chat) and written only inside that job's folder. The job page Download needs to accept the new file types.

**Provenance.** Writes made through a key are recorded with source "Claude (key name)" in the activity/history the app already keeps, so they are visible and attributable.

**Untrusted text.** Posting descriptions and notes returned by tools are wrapped/labelled as untrusted data in the tool result. `docs/claude-desktop.md` advises using a read-only key by default and a read+write key only when needed.

**Settings UI.** New "Claude access" section: list keys (name, scope, prefix, created, last used, expiry, revoke), "Create key" (name, scope, expiry choice), one-time reveal with copy, and a ready-to-paste Claude Desktop config snippet using `mcp-remote` with the key in an `Authorization` header (builder to verify the exact snippet against current Claude Desktop/`mcp-remote` docs). The API URL is shown from the current site origin.

**Copy for Claude.** Button on the job page (and contact/follow-up rows) copying `JobMe job <id>: <employer> – <title>` (similar for others). `get_job` also accepts that reference text.

**Docs.** New `docs/claude-desktop.md` (setup, example prompts, revoking a leaked key); update `docs/security.md` (new door, what it can/cannot do, replace the "planned read-only API" note) and the architecture guide.

## Testing

Backend tests: key create/hash/one-time reveal, auth failures (missing/bad/revoked/expired), scope enforcement, rate and daily caps, each tool against a seeded DB, provenance recorded, no delete/secret tools present, `/api/keys` unreachable with a key. Frontend tests for the Settings section and Copy button. CDK test/assertion that only `/api/mcp` bypasses the authorizer.

## Left to the builder

Whether to also render `.docx` from attached text; Choice of MCP SDK vs minimal handler; exact tool argument schemas and output shapes; default rate/daily limits (above are starting values); migration details; UI styling consistent with existing Settings sections.
