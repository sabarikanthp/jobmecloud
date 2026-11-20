# Claude Desktop Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Claude Desktop chats read and act on JobMe through API keys created in Settings, via an MCP endpoint, including attaching documents written in chat to a job.

**Architecture:** A key table plus `/api/keys` routes (Cognito-protected like all other routes). A stateless MCP JSON-RPC endpoint at `POST /api/mcp` that API Gateway exposes without the JWT authorizer; the app checks the bearer key itself. Each tool dispatches in-process to the existing routes through a FastAPI `TestClient`, so validation, history and S3 sync behave as in the app. A `ContextVar` marks activity-log rows written by a key as `claude:<key name>`.

**Tech Stack:** Python/FastAPI/SQLModel/pytest, Mangum on Lambda, AWS CDK (Python), React + TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-11-20-claude-desktop-access-design.md`. One deliberate change from the spec: the endpoint is `/api/mcp`, not `/mcp`, because CloudFront only forwards `/api/*` to the API and API Gateway's more specific route can then skip the authorizer.

## Global Constraints

- Key format `jmc_` + 32 random bytes base64url; only a sha256 hash is stored; the full key is returned once, on creation.
- Scopes exactly `read` and `readwrite`; the default in the UI is `read`.
- Unauthenticated `/api/mcp` failures return 401 with no detail (missing, unknown, revoked, expired alike).
- No tool deletes anything or touches settings, provider/search keys, key management or Make docs. `/api/keys` is never callable with a key.
- Limits: 60 requests/min per key (best effort, in-process per Lambda instance) and 30 AI-cost tool calls/day per key (stored in the database). AI-cost tools: `check_job`, `re_evaluate_job`.
- Attached documents: max about 3 MB each after decoding; filenames are fixed by JobMe (`resume.md|txt|docx|pdf`, `cover-letter.md|docx|pdf`), never taken from the chat; written only inside the job's documents folder; previous files archived first.
- Writes made with a key show in activity as actor `claude:<key name>`.
- Posting text and notes in tool results are wrapped as untrusted data.
- Existing routes keep their Cognito protection; only `/api/mcp` bypasses the authorizer.

## Review Focus

- A key presented in the wrong case, with extra whitespace, or as `Bearer` vs `bearer`: accept the scheme case-insensitively, reject a key with surrounding junk.
- A write call arriving with a read key: a clear tool error, nothing written.
- `attach_documents` with an oversize, invalid-base64 or wrong-type payload, or a job that has no folder yet: clean error, no partial files, folder created when missing.
- A job id that does not exist, or a reference string like `JobMe job 123: Acme – Staff` : `get_job` resolves the id from the text or returns a not-found tool error.
- Two concurrent revokes/creates, and a revoked key mid-session: the next call after revocation fails.

---

### Task 1: API key store

**Files:**
- Modify: `backend/jobmecloud/db/models.py` (add `ApiKey`)
- Create: `backend/jobmecloud/keys/__init__.py`, `backend/jobmecloud/keys/store.py`
- Test: `tests/test_api_keys_store.py`

**Interfaces:**
- Produces: `class ApiKey(SQLModel, table=True)` with fields `id, name, prefix, key_hash, scope, created_at, expires_at: datetime|None, last_used_at: datetime|None, revoked_at: datetime|None, ai_day: date|None, ai_count: int = 0`.
- Produces in `keys/store.py`: `create_key(session, *, name: str, scope: str, expires_at: datetime | None, now: datetime) -> tuple[ApiKey, str]` (returns the row and the full key); `verify_key(session, presented: str, now: datetime) -> ApiKey | None`; `list_keys(session) -> list[ApiKey]`; `revoke_key(session, key_id: int, now: datetime) -> bool`; `touch(session, key: ApiKey, now: datetime) -> None`; `spend_ai_call(session, key: ApiKey, today: date, limit: int) -> bool` (False when the day's limit is reached).

- [ ] **Step 1: Write failing tests** in `tests/test_api_keys_store.py` using the existing in-memory engine pattern from `tests/test_db.py`: `test_create_returns_key_once_and_stores_only_hash` (key starts `jmc_`, row has no field equal to the key, `prefix == key[:8]`), `test_verify_accepts_valid_key`, `test_verify_rejects_unknown_revoked_and_expired`, `test_scope_must_be_read_or_readwrite` (ValueError), `test_spend_ai_call_stops_at_limit_and_resets_next_day`, `test_touch_sets_last_used`.
- [ ] **Step 2: Run** `uv run pytest tests/test_api_keys_store.py -v`. Expected: FAIL (import error).
- [ ] **Step 3: Implement** the model and store. Use `secrets.token_urlsafe(32)` for the body, `hashlib.sha256`, `hmac.compare_digest`. Look the key up by hash (indexed column `key_hash`, unique). Migration is automatic via `db/migrate.py` (new table).
- [ ] **Step 4: Run tests.** Expected: PASS. Also run `uv run pytest tests/test_migrate.py -v` (expected PASS).
- [ ] **Step 5: Commit** `feat: API key table and store`.

### Task 2: Key management routes

**Files:**
- Create: `backend/jobmecloud/api/routes_keys.py`
- Modify: `backend/jobmecloud/api/app.py` (import and `include_router(routes_keys.router, prefix="/api")`)
- Test: `tests/test_api_keys_routes.py`

**Interfaces:**
- Consumes: Task 1 store.
- Produces: `GET /api/keys -> list[KeyOut]` (`id, name, prefix, scope, created_at, expires_at, last_used_at, revoked_at`), `POST /api/keys` body `{name: str, scope: "read"|"readwrite", expires_in_days: int|None}` -> 201 `{key: str, ...KeyOut}` (the only time `key` appears), `DELETE /api/keys/{id}` -> 204 (revokes; 404 if unknown).

- [ ] **Step 1: Failing tests** with the `client` fixture style of `tests/test_api.py`: `test_create_then_list_never_returns_key_again`, `test_scope_validation_422`, `test_revoke_marks_key_and_list_still_shows_it`, `test_revoke_unknown_404`, `test_name_required_and_trimmed`.
- [ ] **Step 2: Run** them; expected FAIL.
- [ ] **Step 3: Implement** the router; validation error handler in `app.py` already hides bodies.
- [ ] **Step 4: Run tests;** PASS.
- [ ] **Step 5: Commit** `feat: create, list and revoke API keys`.

### Task 3: Provenance for key-made changes

**Files:**
- Create: `backend/jobmecloud/jobs/actor.py`
- Modify: `backend/jobmecloud/jobs/tracking.py:85` and `backend/jobmecloud/jobs/followups.py:42` (the two places that build `ActivityLog` rows)
- Modify: `frontend/src/pages/jobTimeline.ts` (show `claude:<name>` as "Claude (<name>)")
- Test: `tests/test_actor_override.py`, `frontend/src/pages/jobTimeline.test.ts` (create if absent)

**Interfaces:**
- Produces: `ACTOR: ContextVar[str | None]` and `with acting_as(label: str):` context manager in `jobs/actor.py`. When `ACTOR` is set, log rows whose actor would be `"user"` get the label instead.

- [ ] **Step 1: Failing tests:** `test_status_change_logs_label_inside_acting_as` (change a job's status inside `acting_as("claude:Desktop")`, assert the ActivityLog row `actor == "claude:Desktop"`), `test_followup_created_logs_label`, `test_system_actor_is_never_overridden`, `test_no_label_outside_context`. Frontend: timeline renders "Claude (Desktop)" for that actor.
- [ ] **Step 2: Run** (pytest and `npm test --prefix frontend -- jobTimeline`); FAIL.
- [ ] **Step 3: Implement** the module and the two one-line hooks; update the timeline label function.
- [ ] **Step 4: Run;** PASS.
- [ ] **Step 5: Commit** `feat: mark activity made through a Claude key`.

### Task 4: MCP endpoint (auth, protocol, limits)

**Files:**
- Create: `backend/jobmecloud/mcp/__init__.py`, `backend/jobmecloud/mcp/protocol.py`, `backend/jobmecloud/mcp/registry.py`, `backend/jobmecloud/api/routes_mcp.py`
- Modify: `backend/jobmecloud/api/app.py` (include router)
- Test: `tests/test_mcp_endpoint.py`

**Interfaces:**
- Consumes: Task 1 (`verify_key`, `touch`, `spend_ai_call`), Task 3 (`acting_as`).
- Produces in `registry.py`: `@dataclass Tool(name: str, description: str, input_schema: dict, handler: Callable[[ToolContext, dict], dict | list | str], write: bool = False, ai_cost: bool = False)`; `TOOLS: dict[str, Tool]`; `def tool(...)` decorator registering into `TOOLS`; `@dataclass ToolContext(app, key: ApiKey, now: datetime, today: date, call: Callable[..., Any])` where `ctx.call(method: str, path: str, *, json=None, params=None) -> Any` performs an in-process request and raises `ToolError(message)` on any 4xx/5xx.
- Produces: `class ToolError(Exception)`; `POST /api/mcp` accepting JSON-RPC 2.0 (`initialize`, `notifications/initialized` -> 202 empty, `tools/list`, `tools/call`, `ping`); responses are plain JSON (stateless, no SSE); `GET /api/mcp` -> 405. Tool results are returned as `{"content":[{"type":"text","text":<json string>}], "isError": bool}`.

- [ ] **Step 1: Failing tests** with a registered dummy tool: `test_missing_or_bad_key_401_empty_detail` (also revoked, expired, wrong scheme junk), `test_initialize_returns_server_info_and_tools_capability`, `test_tools_list_hides_nothing_but_marks_nothing_secret`, `test_write_tool_with_read_key_is_tool_error_and_not_run`, `test_tool_error_becomes_iserror_result_not_http_500`, `test_ai_cost_tool_blocked_after_daily_limit`, `test_rate_limit_61st_call_in_a_minute_is_429`, `test_last_used_updates`, `test_ctx_call_runs_route_in_process_and_acts_as_key_label` (dummy tool changes a job status via `ctx.call`; activity actor is `claude:<name>`), `test_untrusted_wrapper_helper` (`untrusted(text)` wraps as `<untrusted_data>…</untrusted_data>`).
- [ ] **Step 2: Run;** FAIL.
- [ ] **Step 3: Implement.** Protocol version string: use the latest the MCP spec documents; verify against current MCP docs at build time and echo the client's requested version when supported. `ctx.call` uses `fastapi.testclient.TestClient(app, base_url=f"http://{first host in JOBMECLOUD_ALLOWED_HOSTS}")` created without a `with` block so lifespan does not run. The in-process request must be wrapped in `acting_as(f"claude:{key.name}")`. Rate limiter: module-level dict of key id -> deque of timestamps, 60 per 60 s. Add `untrusted(text: str) -> str` to `registry.py`.
- [ ] **Step 4: Run;** PASS.
- [ ] **Step 5: Commit** `feat: MCP endpoint with key auth, scopes and limits`.

### Task 5: Read tools

**Files:**
- Create: `backend/jobmecloud/mcp/tools_read.py` (imported by `registry.py` at the bottom so tools register)
- Test: `tests/test_mcp_tools_read.py`

**Interfaces:**
- Consumes: `tool`, `ToolContext`, `ToolError`, `untrusted` (Task 4).
- Produces tools (all `write=False`): `list_jobs{status?, query?, min_score?, limit<=50}` via `GET /api/jobs`; `get_job{job: int | str}` (an int, or text containing `job <id>` such as the Copy-for-Claude reference) composed from `GET /api/jobs/{id}` plus follow-ups (`/api/followups?job_id=`), contacts and interviews for that job, with description and notes wrapped by `untrusted`; `get_resume_context{}` (resume and profile text, using the same data `routes_resumes.context_status`/profile loaders expose); `get_dashboard{}` via `GET /api/dashboard`; `list_followups{bucket?, job_id?, contact_id?}`; `list_contacts{job_id?}`; `get_job_documents{job: int|str}` (Task 8 provides the body; register it there).
- Produces: `parse_job_ref(value: int | str) -> int` (raises `ToolError` when no id found).

- [ ] **Step 1: Failing tests** seeding jobs/contacts/follow-ups with an `readonly` key: `test_list_jobs_filters_by_status`, `test_get_job_by_id_and_by_reference_text`, `test_get_job_includes_followups_contacts_interviews_and_wraps_description`, `test_get_job_unknown_is_tool_error`, `test_parse_job_ref_variants` (`123`, `"JobMe job 123: Acme – Staff"`, `"#123"`, `"abc"` error), `test_get_resume_context_returns_text`, `test_list_followups_bucket_overdue`.
- [ ] **Step 2: Run;** FAIL.
- [ ] **Step 3: Implement** the tools with JSON-schema `input_schema` for each; keep handlers thin (compose `ctx.call` results).
- [ ] **Step 4: Run;** PASS.
- [ ] **Step 5: Commit** `feat: MCP read tools`.

### Task 6: Write tools

**Files:**
- Create: `backend/jobmecloud/mcp/tools_write.py` (imported by `registry.py`)
- Test: `tests/test_mcp_tools_write.py`

**Interfaces:**
- Consumes: Task 4 registry; existing routes `POST /api/jobs/{id}/status`, `PATCH /api/jobs/{id}`, `POST /api/jobs`, `POST /api/jobs/check`, `POST /api/jobs/{id}/description`, `POST /api/followups`, `/api/followups/{id}/done|snooze|reschedule|cancel`, `POST/PUT /api/contacts`, `POST /api/jobs/{id}/interviews`, `PUT /api/interviews/{id}`.
- Produces tools (all `write=True`; `ai_cost=True` for `check_job` and `re_evaluate_job`): `set_job_status{job, status, date?, skip_reason?, skip_note?, note?, duplicate_of?}`, `update_job{job, notes?, applied_date?, first_response_date?, outcome_date?}`, `add_job{employer, title, apply_url?, location?, notes?}`, `check_job{input}`, `re_evaluate_job{job, description}`, `create_followup{type, due_date, job?, contact_id?, note?}`, `complete_followup{id, outcome_note?, next_date?}`, `snooze_followup{id, until}`, `reschedule_followup{id, due_date}`, `cancel_followup{id}`, `create_contact{name, job?, employer?, role?, link?, relationship?, status?, notes?}`, `update_contact{id, ...same fields}`, `add_interview{job, date?, stage?, notes?}`, `update_interview{id, date?, stage?, notes?}`.
- Note: `update_job` `notes` replaces; add a separate `append_job_note{job, text}` that reads the current notes and appends a dated line (needed because chats usually add, not overwrite).

- [ ] **Step 1: Failing tests** (readwrite key): one per tool asserting the database effect and the activity actor label where the route logs one (`set_job_status` to Applied also creates the default follow-up, proving the real route ran); `test_invalid_status_transition_is_tool_error`; `test_append_job_note_keeps_existing_text`; `test_check_job_counts_toward_daily_limit` and `test_check_job_uses_existing_fit_check` (use `FakeProvider` from `tests/fakes.py` as other check tests do); `test_no_delete_or_settings_tools_registered` (names in `TOOLS` contain none of `delete`, `settings`, `key`, `make_docs`).
- [ ] **Step 2: Run;** FAIL.
- [ ] **Step 3: Implement** the handlers as pass-throughs that map argument names (`job` via `parse_job_ref`) onto the route bodies; no new business logic.
- [ ] **Step 4: Run;** PASS.
- [ ] **Step 5: Commit** `feat: MCP write tools for jobs, follow-ups, contacts, interviews`.

### Task 7: Attach and read documents

**Files:**
- Create: `backend/jobmecloud/mcp/tools_docs.py` (imported by `registry.py`), `backend/jobmecloud/applydocs/attach.py`
- Modify: `backend/jobmecloud/applydocs/output.py` (add `COVER_NAMES = ("cover-letter.docx", "cover-letter.pdf", "cover-letter.md")`, extend `ARCHIVED` with them); `backend/jobmecloud/api/routes_jobs.py` `_target` to search `COVER_NAMES` for `cover_letter`
- Test: `tests/test_attach_docs.py`, extend `tests/test_download.py`

**Interfaces:**
- Produces: `attach_documents(session, state, job_id: int, *, resume: DocIn | None, cover_letter: DocIn | None, source: str, now: datetime) -> dict` in `attach.py`, where `DocIn` is `{format: "md"|"txt"|"docx"|"pdf", text: str | None, base64: str | None}` (exactly one of `text` / `base64`; `md`/`txt` need `text`, `docx`/`pdf` need `base64`); returns `{"resume": filename|None, "cover_letter": filename|None}`. Uses `job_folder_name`, `prepare_folder`, `archive_previous` from `applydocs/output.py` and the settings' folder pattern/applications path as `routes_jobs._target` does; sets `job.docs_folder`, `job.docs_status = "ready"`, `job.docs_note = "Attached from Claude (<source>)"`, clears `docs_error`, and logs an activity row action `docs_attached`.
- Produces tools: `attach_documents{job, resume?, cover_letter?}` (`write=True`) and `get_job_documents{job}` (`write=False`) returning each document as text (`md`/`txt` directly; `docx` via the existing docx text reader in `importers/` / `tests/test_docx_text.py`'s subject; `pdf` via pypdf) wrapped by `untrusted`.

- [ ] **Step 1: Failing tests:** `test_attach_text_resume_creates_folder_and_file`, `test_attach_archives_previous_files_first`, `test_attach_base64_docx_round_trips_bytes`, `test_rejects_over_3mb_invalid_base64_wrong_format_pairing_and_unknown_format` (nothing written, no job fields changed), `test_filename_never_comes_from_input`, `test_write_stays_inside_job_folder`, `test_sets_docs_ready_and_note`, `test_get_job_documents_returns_text_and_wraps`, `test_attach_requires_readwrite_key`; in `test_download.py`: `test_download_cover_letter_md_and_pdf_found`.
- [ ] **Step 2: Run;** FAIL.
- [ ] **Step 3: Implement.** Decode with `base64.b64decode(..., validate=True)`; check size before writing; write atomically (existing helper in `config/files.py` if suited, else write to a temp name then `os.replace`). Rendering text to `.docx` is intentionally NOT done here (YAGNI); note it as a follow-up in the docs.
- [ ] **Step 4: Run** `uv run pytest tests/test_attach_docs.py tests/test_download.py tests/test_make_docs.py tests/test_output.py -v`; PASS (existing docs tests prove archiving/names are unchanged).
- [ ] **Step 5: Commit** `feat: attach documents written in Claude to a job`.

### Task 8: API Gateway route without the JWT authorizer

**Files:**
- Modify: `infra/edge.py` (second `add_routes` for `path="/api/mcp"`, methods `POST` and `GET`, same Lambda integration, **no** authorizer)
- Test: `tests/test_infra_edge.py`

- [ ] **Step 1: Failing test** using `aws_cdk.assertions.Template` on a minimal stack that builds `Edge`: `test_only_mcp_route_has_no_authorizer` (the `/api/{proxy+}` route has `AuthorizationType: JWT`; every other route has it; exactly one route, `ANY /api/mcp` or its POST/GET pair, has `NONE`).
- [ ] **Step 2: Run;** FAIL.
- [ ] **Step 3: Implement** the route (API Gateway prefers the more specific route over `{proxy+}`).
- [ ] **Step 4: Run** the test and `uv run cdk synth` (expected: success).
- [ ] **Step 5: Commit** `feat: expose /api/mcp without the sign-in authorizer`.

### Task 9: Settings "Claude access" section

**Files:**
- Create: `frontend/src/sections/ClaudeAccessSection.tsx`, `frontend/src/sections/ClaudeAccessSection.test.tsx`
- Modify: `frontend/src/api.ts` (add `ApiKeyOut`, `listApiKeys`, `createApiKey(name, scope, expiresInDays)`, `revokeApiKey(id)`), `frontend/src/pages/Settings.tsx` (render the section last)

**Interfaces:**
- Consumes: Task 2 routes.
- Produces: component `ClaudeAccessSection()`; a helper `desktopConfig(origin: string, key: string): string` returning the JSON block to paste into Claude Desktop's config using `npx mcp-remote` with `--header "Authorization: Bearer <key>"` and URL `<origin>/api/mcp`. Verify the exact `mcp-remote` argument form and Claude Desktop config file location against current docs before finalising, and put the verified form in the test.

- [ ] **Step 1: Failing tests** (follow patterns in existing `*.test.tsx`): `lists keys with name, scope, prefix, last used`, `create shows the key once with a copy button and the config snippet; closing hides it`, `default scope is read-only and read+write shows a warning line`, `revoke asks to confirm then calls the API`, `desktopConfig puts the key in the Authorization header and uses /api/mcp`.
- [ ] **Step 2: Run** `npm test --prefix frontend -- ClaudeAccessSection`; FAIL.
- [ ] **Step 3: Implement** following the look of `LimitsSection.tsx`/`AiSection.tsx` (`mode="settings"` not needed).
- [ ] **Step 4: Run** the frontend tests and `npm run build --prefix frontend` (type-check); PASS.
- [ ] **Step 5: Commit** `feat: Settings section to create and revoke Claude keys`.

### Task 10: "Copy for Claude" buttons

**Files:**
- Create: `frontend/src/claudeRef.ts`, `frontend/src/claudeRef.test.ts`
- Modify: `frontend/src/pages/JobPage.tsx` (button in the job header), `frontend/src/pages/FollowUps.tsx` and `frontend/src/pages/ContactsTab.tsx` (button per row)

**Interfaces:**
- Produces: `jobRef(job: {id: number; employer: string; title: string}): string` -> `JobMe job 123: Acme – Staff Engineer`; `contactRef(c)` -> `JobMe contact 5: Jane Doe (Acme)`; `followUpRef(f)` -> `JobMe follow-up 9: <type> due <date>`. The backend resolves job references only (`parse_job_ref`); contact and follow-up references carry the id for use with `list_contacts`/`list_followups`.

- [ ] **Step 1: Failing tests:** `jobRef` formats exactly as above and trims long titles to 80 characters; clicking the job button writes that text to `navigator.clipboard` and shows "Copied".
- [ ] **Step 2: Run;** FAIL.
- [ ] **Step 3: Implement** (no clipboard crash when unavailable: show the text selected for manual copy).
- [ ] **Step 4: Run** frontend tests and build; PASS.
- [ ] **Step 5: Commit** `feat: Copy for Claude buttons`.

### Task 11: Documentation

**Files:**
- Create: `docs/claude-desktop.md`
- Modify: `docs/security.md` (new "Claude access" door: what a key can and cannot do, the limits, untrusted-text caveat, revoke steps; replace the "narrower database role is planned for the read-only external API" note with an honest statement that `/api/mcp` uses the same admin database role), `docs/architecture-guide.md`, `README.md` (one line linking to the new doc)

- [ ] **Step 1: Write `docs/claude-desktop.md`:** create a key, paste the verified config, restart Claude Desktop, example prompts (referencing a job, "attach this resume to job 123"), tool list, read-only vs read+write advice, revoking a leaked key, note that Word rendering of attached text is not included.
- [ ] **Step 2: Update the other docs** as above; keep tone of the existing docs.
- [ ] **Step 3: Run the whole suite:** `uv run pytest -q` and `npm test --prefix frontend` and `npm run build --prefix frontend`. Expected: all pass.
- [ ] **Step 4: Commit** `docs: Claude Desktop access`.

### Task 12: End-to-end check against a real Claude Desktop

**Files:** none (verification only).

- [ ] **Step 1:** Run the app locally (`uv run jobmecloud` per the README), create a read+write key in Settings, add the config to Claude Desktop pointed at `http://localhost:<port>/api/mcp`, restart it.
- [ ] **Step 2:** In a chat: "get JobMe job <id>", "set that job's note…", "create a follow-up…", "attach this cover letter to the job". Confirm each result in the app (activity shows `Claude (<key name>)`, Download works).
- [ ] **Step 3:** Revoke the key; confirm the next chat call fails. Report anything that differs from the docs and fix before deploy.
- [ ] **Step 4 (deploy, only when the owner says so):** follow `docs/deploy.md`; then repeat Step 2 against the CloudFront URL.

---

## Self-review notes

- Spec coverage: keys/UI (1, 2, 9), endpoint/auth/limits (4, 8), tools incl. contacts/follow-ups/interviews (5, 6), attach docs (7), provenance (3), Copy for Claude (10), docs (11), verification (12). Untrusted wrapper (4, 5, 7). No-delete rule asserted in Task 6.
- Spec items decided here: path `/api/mcp`; per-minute limit is per Lambda instance (best effort), daily AI cap is exact (database); `append_job_note` added; Word rendering deferred.
