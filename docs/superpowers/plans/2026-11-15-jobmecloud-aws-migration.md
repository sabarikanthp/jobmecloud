# JobMeCloud Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build JobMeCloud, an open-source, serverless AWS version of JobMe that one person can deploy from the docs and use for about $0 per month of AWS cost.

**Architecture:** Copy the JobMe backend and frontend into a new repo, strip the Windows-only parts, and run it as Lambdas behind CloudFront and an API Gateway HTTP API, with Aurora DSQL, S3, SSM, Cognito (password + MFA), and EventBridge Scheduler. Existing path-based code (`data_dir`) is kept by syncing an S3 prefix to Lambda `/tmp`. Delivered in two stages: stage 1 is a working, documented app; stage 2 adds email digests, the tailoring agent and an external API.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLAlchemy, boto3, AWS CDK (Python), React/Vite (existing), pytest, moto (AWS fakes in tests).

**Spec:** `docs/superpowers/specs/2026-11-14-aws-migration-design.md` (copied into the new repo in Task 1). Source code to port: the existing JobMe repo at `c:\Projects\jobme`, called `OLD/` below.

## Global Constraints

- Python `>=3.12`; Lambdas are arm64; zip + layer, no container images.
- No NAT gateway, VPC, VPC endpoints, provisioned concurrency, X-Ray, RDS/Aurora instances, or Secrets Manager secrets.
- Lambda limits: `api` 30 s / 512 MB; `run-worker` 15 min / 1 GB; `docs-worker` 5 min / 1 GB; `ext-api` (stage 2) 10 s / 256 MB.
- DSQL: a transaction modifies at most 3,000 rows; DDL and DML in separate transactions, one DDL statement per transaction; indexes via `CREATE INDEX ASYNC`; identity columns are `bigint` with an explicit `CACHE`; `ADD COLUMN` takes a type only; connection lifetime under 1 hour.
- Secrets in SSM Parameter Store SecureString, standard tier, under `/jobmecloud/`; names keep the form `provider:<id>` and `search:<backend>`.
- Auth: Cognito Essentials plan, native users, self sign-up disabled, MFA required with authenticator app and email code only. No SMS, no Google/social sign-in, no Bedrock in stage 1.
- Default `*.cloudfront.net` domain. CloudWatch log retention 14 days. AWS Budgets alert at $5 per month.
- The repo is public: no personal data, real profiles, account ids or keys in code, tests, docs or git history; examples only.
- Agent names stay JobScout and ApplyDocs. The no-invented-facts guarantee is enforced by `self_check` in code.
- Do not copy `OLD/.venv`, `__pycache__`, or `node_modules`. Commit after every task.

## Review Focus

- Nobody but the owner can get in: self sign-up is rejected, and a password alone (no MFA) never yields a token (Task 7).
- A lost authenticator or forgotten password has a working recovery path, `scripts/reset_owner.py` (Task 7).
- A spreadsheet import with more than 3,000 rows commits in batches instead of failing at the DSQL limit (Task 3).
- "Run now" clicked twice, or a scheduled run firing during a manual run: exactly one run proceeds and the other gets "A run is already in progress." (Task 9).
- A stranger following `docs/deploy.md` on a fresh AWS account reaches a working sign-in: every command in the guide exists, and no personal data ships in the repo (Task 11).

---

# Stage 1: a working app you can use

### Task 1: Bootstrap the new repo

**Files:**
- Create: new repo `jobmecloud/` (sibling of `OLD/`) with `pyproject.toml`, `README.md` (stub, finished in Task 11), `LICENSE` (copy of `OLD/LICENSE`), `.gitignore`, `docs/superpowers/specs/`, `docs/superpowers/plans/`
- Copy then edit: `OLD/backend/jobme` to `backend/jobmecloud`, `OLD/frontend`, `OLD/tests`, `OLD/profile.example`
- Delete from the copy: `scheduling/windows_task.py`, `api/routes_storage.py`, `config/storage.py`, the Word COM script in `applydocs/pages.py` and its tests, `tests/test_windows_task.py`, `tests/test_storage.py`, `docs/scheduling-mac-linux.md`

**Interfaces:**
- Produces: importable package `jobmecloud` (rename of `jobme`), UI title "JobMeCloud", `pytest` passing on the ported suite.

- [ ] **Step 1:** `git init` the new repo, copy the spec and this plan into it, copy the source above, and do a repo-wide replace of `jobme` with `jobmecloud` (imports, `pyproject.toml` name and script entry, hatch package path).
- [ ] **Step 2:** Remove imports and routes of the deleted modules; make the page counter a no-op returning `None` so `make_docs` works. Leave `routes_schedule.py` importable (rewritten in Task 10).
- [ ] **Step 3:** Run `uv sync && uv run pytest -q`; expected: all remaining tests pass. Fix only import/rename breakage.
- [ ] **Step 4:** Commit `chore: bootstrap jobmecloud from jobme`.

### Task 2: Data layer for SQLite and DSQL

**Files:**
- Create: `backend/jobmecloud/db/engine.py`, `backend/jobmecloud/db/migrate.py`, `tests/test_engine.py`, `tests/test_migrate.py`, `tests/integration/test_dsql_schema.py` (marked `@pytest.mark.dsql`, skipped unless `JOBMECLOUD_DB_URL` is set)
- Modify: `backend/jobmecloud/db/models.py`, `backend/jobmecloud/db/session.py` (remove `get_engine`, `init_db`, `add_missing_columns`), `backend/jobmecloud/api/app.py`, `backend/jobmecloud/cli.py`

**Interfaces:**
- Produces: `make_engine(url: str | None = None, data_dir: Path | None = None) -> Engine`. No url with a `data_dir` gives the SQLite engine (WAL and foreign-key PRAGMAs as today). A url starting `dsql://<endpoint>` gives a PostgreSQL engine whose `creator` makes an IAM token per new connection (`boto3.client("dsql").generate_db_connect_admin_auth_token`, `pool_recycle=2400`, `pool_pre_ping=True`). Env `JOBMECLOUD_DB_URL` overrides.
- Produces: `migrate(engine: Engine) -> list[str]` (changes applied). On PostgreSQL each `CREATE TABLE` runs in its own transaction, indexes use `CREATE INDEX ASYNC`, and a missing column is added in two transactions (`ADD COLUMN <type>`, then `SET DEFAULT`). SQLite keeps the `PRAGMA table_info` logic.
- Produces: `pk_column()` helper in `models.py`: `BigInteger` with `Identity(cache=100)` on PostgreSQL, plain autoincrement on SQLite; every model uses it.

- [ ] **Step 1:** Tests: `test_sqlite_when_no_url`, `test_dsql_url_builds_postgres_engine_with_token_creator` (patch boto3; assert the token is used as the password), `test_creates_all_tables`, `test_adds_missing_column_with_default`, `test_migrate_idempotent_returns_empty`. DSQL integration test: create schema, insert a `Job` with JSON columns and a foreign-keyed `RunJob`, read back, assert JSON round-trips.
- [ ] **Step 2:** Run `pytest tests/test_engine.py tests/test_migrate.py -v`; expected FAIL.
- [ ] **Step 3:** Implement; add `psycopg[binary]` as a dependency; replace `init_db` call sites with `migrate`.
- [ ] **Step 4:** Run the suite; expected PASS. If a DSQL cluster is available, also run `pytest -m dsql` and note the result in the commit message. Commit `feat: sqlite and dsql data layer`.

### Task 3: Conflict retry and batched writes

**Files:**
- Create: `backend/jobmecloud/db/retry.py`, `backend/jobmecloud/db/batch.py`, `tests/test_retry.py`, `tests/test_batch.py`
- Modify: importers (`importers/sheet_import.py`, `importers/tracker.py`, `importers/watchlist.py`, `importers/text.py`), `agents/jobscout/pipeline.py` per-job saves, `api/app.py`

**Interfaces:**
- Produces: `retry_on_conflict(attempts: int = 5, base_delay: float = 0.05)` decorator re-running the function on a DB error with SQLSTATE `40001` (or message containing `OC000`/`OC001`), jittered backoff, re-raising after the last attempt.
- Produces: `chunked(items: Iterable[T], size: int = 500) -> Iterator[list[T]]` and `MAX_ROWS_PER_TX = 3000`.
- Produces: middleware that retries a non-GET request once on a serialization conflict (body buffered), otherwise answers 409 "Please try again."

- [ ] **Step 1:** Tests: `test_retries_then_succeeds`, `test_gives_up_after_attempts`, `test_non_conflict_error_not_retried`, `test_chunked_sizes` (1,201 items, size 500 gives 500, 500, 201), `test_import_of_3500_rows_commits_in_batches` (count rows per commit with an event listener; none above 3,000).
- [ ] **Step 2:** FAIL. **Step 3:** Implement; commit importers with `chunked(rows, 500)`. **Step 4:** Suite PASS. **Step 5:** Commit `feat: conflict retry and batched imports`.

### Task 4: SSM secrets and S3 workspace sync

**Files:**
- Modify: `backend/jobmecloud/secrets.py`, `backend/jobmecloud/config/paths.py`, `tests/test_secrets.py`, `tests/conftest.py`
- Create: `backend/jobmecloud/storage/workspace.py`, `tests/test_workspace.py`

**Interfaces:**
- Produces (same names as today): `set_secret(name: str, value: str) -> None`, `get_secret(name: str) -> str | None`, `delete_secret(name: str) -> None`, stored as SecureString at `/jobmecloud/<name with ":" replaced by "/">`, standard tier. Remove the `keyring` dependency.
- Produces: `Workspace(bucket: str, prefix: str, local_dir: Path)` with `pull() -> None` (download every object under the prefix, skipping files whose size and ETag match the local manifest), `push() -> list[str]` (upload new or changed files, never `.db` files; return keys), `presign(relative_key: str, expires: int = 900) -> str`.
- Produces: `paths.data_dir()` returns `Path(os.environ.get("JOBMECLOUD_DATA_DIR", "/tmp/jobmecloud"))`; the location-file logic is removed.

- [ ] **Step 1:** moto tests: `test_secret_set_then_get`, `test_get_missing_returns_none`, `test_delete_missing_is_silent`, `test_secret_stored_as_secure_string`, `test_pull_downloads_nested_files`, `test_push_uploads_only_changed`, `test_second_pull_skips_unchanged`, `test_presign_has_expiry`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; add a moto fixture to `conftest.py` and port the existing keyring-mocking tests to it. **Step 4:** Suite PASS. **Step 5:** Commit `feat: ssm secrets and s3 workspace`.

### Task 5: Cloud-mode app and `api` Lambda handler

**Files:**
- Modify: `backend/jobmecloud/api/app.py`
- Create: `backend/jobmecloud/handlers/api.py`, `tests/test_app_cloud_mode.py`, `tests/test_handler_api.py`

**Interfaces:**
- Produces: `create_app()` reads `JOBMECLOUD_ALLOWED_HOSTS` (comma-separated; default `127.0.0.1,localhost,testserver`) for `TrustedHostMiddleware`; when `JOBMECLOUD_BUCKET` is set it pulls the workspace once per cold start and pushes after every successful non-GET request; it never calls `migrate` when `JOBMECLOUD_DB_URL` is set.
- Produces: `handler(event: dict, context) -> dict`, an API Gateway HTTP API v2 adapter (Mangum, `lifespan="off"`, app built once at import).

- [ ] **Step 1:** Tests: `test_allowed_hosts_from_env`, `test_unknown_host_rejected`, `test_no_migrate_on_dsql_startup`, `test_health_through_handler`, `test_post_json_roundtrip`, `test_multipart_resume_upload_roundtrip`, `test_workspace_pushed_after_post`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: cloud-mode app and api lambda handler`.

### Task 6: CDK foundation

**Files:**
- Create: `infra/app.py`, `infra/jobmecloud_stack.py`, `infra/requirements.txt`, `infra/cdk.json`, `tests/infra/test_stack_foundation.py`

**Interfaces:**
- Produces: `JobMeCloudStack` with `dsql_cluster`, `data_bucket` (private, versioned, block-public-access, SSE-S3), `site_bucket`, and helper `make_function(name: str, handler: str, timeout: int, memory: int, env: dict) -> Function` (arm64, Python 3.12, 14-day log retention, shared layer). A `Budget` of $5 monthly alerting `owner_email` (CDK context value).

- [ ] **Step 1:** `Template` assertion tests: `test_data_bucket_private_and_versioned`, `test_no_nat_gateway_or_vpc`, `test_log_retention_14_days`, `test_budget_5_usd`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement (use the `aws-cdk` skill for construct patterns; DSQL via the L1 `CfnCluster` if no L2 exists). **Step 4:** PASS and `cdk synth` succeeds. **Step 5:** Commit `feat(infra): foundation stack`.

### Task 7: Sign-in with required MFA

**Files:**
- Modify: `infra/jobmecloud_stack.py`
- Create: `scripts/create_owner.py`, `scripts/reset_owner.py`, `tests/infra/test_stack_auth.py`, `tests/test_owner_scripts.py`

**Interfaces:**
- Produces (CDK): a user pool on the Essentials feature plan with self sign-up disabled (`allow_admin_create_user_only`), `email` required, MFA `REQUIRED` with TOTP and email OTP enabled and SMS not, email sent through SES from the verified sender (context `sender_email`), self-service account recovery off, a hosted-login domain, and a public SPA app client (authorization-code + PKCE, no secret). An API Gateway JWT authorizer using this pool.
- Produces: `create_owner(email: str, pool_id: str, client=None) -> None` (admin-creates the user with a verified email and emails a temporary password; idempotent if the user exists). `reset_owner(email: str, pool_id: str, client=None) -> None` (sets a new temporary password and turns off the user's MFA preferences so they re-enrol). Both are runnable as `python scripts/<name>.py --email ... --pool-id ...`.

- [ ] **Step 1:** CDK tests: `test_self_signup_disabled`, `test_mfa_required_totp_and_email_only`, `test_no_sms_configuration`, `test_feature_plan_essentials`, `test_spa_client_has_no_secret`, `test_account_recovery_disabled`. Script tests (moto): `test_create_owner_creates_confirmed_email_user`, `test_create_owner_idempotent`, `test_reset_owner_clears_mfa_and_forces_password_change`, `test_reset_owner_unknown_user_errors_clearly`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: cognito sign-in with required mfa`.

### Task 8: API Gateway, CloudFront and frontend sign-in

**Files:**
- Modify: `infra/jobmecloud_stack.py`, `frontend/src/api.ts`, `frontend/src/main.tsx`, `frontend/vite.config.ts`
- Create: `frontend/src/auth.ts`, `frontend/src/auth.test.ts` (add `vitest`), `tests/infra/test_stack_edge.py`

**Interfaces:**
- Produces (CDK): HTTP API with the `api` Lambda on `/api/{proxy+}` behind the JWT authorizer; CloudFront with the site bucket (origin access control, SPA fallback to `index.html`) as default and `/api/*` routed to the HTTP API; `JOBMECLOUD_ALLOWED_HOSTS` set to the distribution domain; stack outputs `SiteUrl`, `UserPoolId`, `ClientId`.
- Produces (frontend): `getToken(): Promise<string>`, `login(): void` (redirect to hosted login, PKCE), `handleCallback(): Promise<void>`, `logout(): void`; `api.ts` sends `Authorization: Bearer <token>` and calls `login()` on 401. Pool and client ids come from a `config.json` written at deploy.

- [ ] **Step 1:** Frontend tests: `pkce challenge is base64url of sha256 of the verifier`, `api adds bearer header`, `401 triggers login`. CDK tests: `test_api_routes_require_authorizer`, `test_cloudfront_api_behavior_targets_http_api`, `test_site_bucket_not_public`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** `npm test`, `npm run build`, `pytest tests/infra` PASS. **Step 5:** Commit `feat: api gateway, cloudfront and frontend sign-in`. After deploying, sign in with the owner account, complete MFA setup and see the Today screen: the first usable deployment.

### Task 9: Workers and async "Run now" / "Make docs"

**Files:**
- Create: `backend/jobmecloud/jobs/dispatch.py`, `backend/jobmecloud/handlers/run_worker.py`, `backend/jobmecloud/handlers/docs_worker.py`, `tests/test_dispatch.py`, `tests/test_handler_run_worker.py`, `tests/test_handler_docs_worker.py`
- Modify: `backend/jobmecloud/api/routes_runs.py`, the docs route that calls `make_docs`, `backend/jobmecloud/api/app.py`, `infra/jobmecloud_stack.py`

**Interfaces:**
- Produces: `Dispatcher` protocol with `start_run(run_id: int) -> None` and `start_docs(job_id: int, options: dict) -> None`; `LambdaDispatcher(client)` invokes the workers with `InvocationType="Event"`, payloads `{"task":"run","run_id":12}` and `{"task":"docs","job_id":5,"options":{...}}`; `ThreadDispatcher` keeps today's thread behavior for tests. `app.state.dispatcher` replaces `run_thread`.
- Produces: `run_worker.handler(event, context)` handling `{"task":"run","run_id":N}` via `execute_run` and `{"trigger":"schedule"}` via `preflight`, `start_run(engine, "schedule", now)`, `execute_run`; `docs_worker.handler(event, context)` pulls the workspace, calls `make_docs`, pushes the workspace, and writes docs status (`generating`/`ready`/`error`) to the DB. Before the limit (`context.get_remaining_time_in_millis() < 90_000`) a run stops cleanly and records "Stopped early to stay within the time limit."

- [ ] **Step 1:** Tests: `test_run_now_dispatches_and_returns_run_id`, `test_second_run_now_returns_409_in_progress`, `test_schedule_event_during_manual_run_skips_with_note`, `test_worker_stops_early_when_time_is_short` (fake context with 60 s left; the stop note is recorded and the lock released), `test_make_docs_returns_202_and_dispatches`, `test_docs_worker_marks_ready_and_uploads_files`, `test_docs_worker_error_message_has_no_secrets`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; reuse `RunLock` unchanged. Grant the `api` role `lambda:InvokeFunction` on the two workers. **Step 4:** PASS. **Step 5:** Commit `feat: workers and async dispatch`.

### Task 10: EventBridge Scheduler

**Files:**
- Create: `backend/jobmecloud/scheduling/eventbridge.py`, `tests/test_eventbridge_schedule.py`
- Modify: `backend/jobmecloud/api/routes_schedule.py`, `backend/jobmecloud/config/settings.py` (drop `wake`), frontend `ScheduleSection.tsx` (remove the wake option and Windows copy), `infra/jobmecloud_stack.py`

**Interfaces:**
- Produces: `sync_schedules(days: list[str], times: list[str], tz: str, *, client=None) -> list[str]` making the account's `jobmecloud-run-*` schedules match the request (one `cron(M H ? * DOW *)` per time, target `run-worker`, payload `{"trigger":"schedule"}`); `list_schedules(client=None) -> dict`; `clear_schedules(client=None) -> None`. `routes_schedule.py` keeps its request/response shapes minus `wake`.

- [ ] **Step 1:** moto tests: `test_creates_one_schedule_per_time`, `test_removes_stale_schedules`, `test_cron_uses_selected_days`, `test_clear_removes_all`, `test_status_lists_schedules`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; grant the `api` role scheduler permissions on `jobmecloud-run-*` and `iam:PassRole` for the scheduler's invoke role. **Step 4:** PASS. **Step 5:** Commit `feat: eventbridge scheduler for runs`.

### Task 11: Build script and open-source documentation

**Files:**
- Create: `scripts/build_lambdas.py`, `scripts/migrate_db.py`, `docs/deploy.md`, `docs/costs.md`, `docs/security.md`, `docs/operations.md`, `docs/account-recovery.md`, `docs/troubleshooting.md`, `CONTRIBUTING.md`, `tests/test_build_lambdas.py`, `tests/test_docs.py`
- Modify: `README.md`

**Interfaces:**
- Produces: `build_lambdas.py` writing a layer zip (dependencies from `uv export`, arm64 wheels) and one code zip per handler under `dist/lambda/`; it fails if any zip exceeds 50 MB zipped or the unzipped total exceeds 250 MB. `migrate_db.py` runs `migrate(engine)` against the deployed cluster.
- Docs content is fixed by the spec's "Open-source documentation requirements". `deploy.md` must give runnable commands in order: create an AWS account; billing alert; do not use the root user (IAM Identity Center admin or an IAM user with MFA); install AWS CLI, Node.js, uv, CDK; `aws configure` or SSO login; choose and check a region; `cdk bootstrap`; verify the SES sender; `python scripts/build_lambdas.py`; `cdk deploy -c owner_email=... -c sender_email=...`; `python scripts/migrate_db.py`; `python scripts/create_owner.py`; first sign-in and MFA setup; add the AI key in Settings; first run. `account-recovery.md` is a dedicated, step-by-step guide covering: why self-service reset is off; forgot password; lost phone or authenticator (use the email code, then re-enrol); lost both (run `reset_owner.py` with AWS admin credentials, with the exact command and what the user sees next); lost AWS access too (root/account recovery pointers); changing the owner email; and a "prevent lockout" checklist (enrol both factors, keep a second admin). It is linked from the README, `deploy.md`, `operations.md` and `troubleshooting.md`. `costs.md` has a per-service table with free-tier terms and links to the AWS pricing pages, and explains LLM spend.

- [ ] **Step 1:** Tests: `test_layer_excludes_boto3_and_tests`, `test_each_handler_zip_has_entry_module`, `test_size_limit_enforced`, `test_readme_links_every_guide`, `test_deploy_guide_covers_required_steps` (assert the guide mentions: billing alert, root user, IAM Identity Center, cdk bootstrap, build_lambdas, cdk deploy, migrate_db, create_owner, authenticator), `test_every_script_named_in_docs_exists`, `test_account_recovery_guide_covers_scenarios` (mentions forgot password, lost authenticator, lost both, reset_owner, changing owner email, lockout checklist), `test_recovery_guide_linked_from_readme_deploy_ops_and_troubleshooting`, `test_costs_doc_lists_each_service` (Lambda, DSQL, Cognito, CloudFront, S3, API Gateway, SES, SSM, EventBridge Scheduler), `test_no_personal_data_in_repo` (fail on the owner's email domain/usernames and on 12-digit account-id patterns outside `docs/` placeholders such as `123456789012`).
- [ ] **Step 2:** FAIL. **Step 3:** Implement the scripts and write the docs. **Step 4:** PASS. **Step 5:** Commit `docs: deployment guide, costs, security and operations`.
- [ ] **Step 6 (manual gate, not automated):** Deploy to the real account by following `docs/deploy.md` only; fix every place the guide was wrong or unclear. Before announcing the repo, ask one other person to follow it on a fresh account.

---

# Stage 2: once you are using it

### Task 12: SES digest and reminders

**Files:**
- Create: `backend/jobmecloud/notify/digest.py`, `backend/jobmecloud/notify/templates.py`, `tests/test_digest.py`
- Modify: `backend/jobmecloud/handlers/run_worker.py`, `backend/jobmecloud/config/settings.py` (`notify: {digest: bool, reminders: bool}`), `infra/jobmecloud_stack.py` (SES identity, daily reminder schedule), frontend settings section

**Interfaces:**
- Produces: `build_digest(engine, run_id: int, cutoff: int) -> Email | None`, `build_reminders(engine, today: date) -> Email | None` (`None` when nothing to report), `send(email: Email, *, client=None) -> None` via SES to the verified address; `Email` is `(subject: str, text: str, html: str)`. Digests hold only title, employer, score, link and counts, never resume text or keys. The run worker sends the digest after a scheduled run; a daily schedule fires `{"task":"digest"}`.

- [ ] **Step 1:** Tests: `test_digest_lists_matches_above_cutoff`, `test_digest_none_when_no_new_matches`, `test_reminders_list_due_followups`, `test_reminders_none_when_nothing_due`, `test_email_has_no_secrets_or_resume_text`, `test_send_uses_verified_address`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: ses digest and reminders`.

### Task 13: Tailoring agent with the truthfulness gate

**Files:**
- Create: `backend/jobmecloud/applydocs/tailor_agent.py`, `tests/test_tailor_agent.py`
- Modify: `backend/jobmecloud/applydocs/make_docs.py` (`_draft`), `backend/jobmecloud/db/models.py` (a "needs review" note on the docs status if none exists), frontend docs card

**Interfaces:**
- Produces: `tailor_with_agent(provider: Provider, model: str, *, job: Job, profile: SearchProfile, resume: MasterResume, user: UserProfile, tone: str, feedback: str | None, headline: str, costs: CostTracker, search: SearchBackend | None, max_revisions: int = 2) -> TailorOutcome`, a dataclass `(draft: Draft, problems: list[str], turns: int)`; `problems` is empty only when the final draft passed `self_check`.
- Tools for `run_agent` (`Tool(spec, run)`): `get_master_resume()`, `get_job()`, `get_preferences()`, `fetch_url(url)` and `web_search(query)` (reusing the search agent's fetcher, guards and `search`; omitted when `search` is None), `check_draft(draft_json)` (calls `self_check`), `submit_draft(draft_json)` (validates against `DRAFT_SCHEMA`, ends the loop).
- Gate in code: after the agent ends, `self_check` runs on the submitted draft; up to `max_revisions` more agent revisions with the problems fed back; if problems remain, `make_docs` saves the documents with the note "Needs review: could not verify every claim." The system prompt reuses `RULES` and `DATA_NOTE` from `tailor.py`. `tailor.draft_documents` stays as the fallback for providers without tool use.

- [ ] **Step 1:** Scripted fake-provider tests: `test_agent_submits_clean_draft`, `test_invented_employer_is_flagged_not_passed`, `test_revision_loop_stops_at_max_revisions`, `test_cost_cap_returns_best_draft_flagged`, `test_posting_text_cannot_inject_tool_calls`, `test_fetch_url_blocks_private_addresses`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** PASS. **Step 5:** Commit `feat: tailoring agent with truthfulness gate`.

### Task 14: Read-only external API

**Files:**
- Create: `backend/jobmecloud/api_ext/app.py`, `backend/jobmecloud/handlers/ext_api.py`, `tests/test_api_ext.py`, `docs/external-api.md`
- Modify: `infra/jobmecloud_stack.py`, `scripts/migrate_db.py` (creates the read-only DSQL role)

**Interfaces:**
- Produces: FastAPI app with `GET /v1/jobs` (params `status`, `min_score: int`, `since: datetime`, `q`, `limit: int = 50` capped at 200, `cursor`) returning `{"items": [JobSummary], "next_cursor": str | None}`; `GET /v1/jobs/{id}` returning `JobDetail` (summary plus description, score, rationale, flags, contacts and follow-ups summary); `GET /v1/runs/latest`. 404 for unknown ids. It uses a read-only DB role (`SELECT` only) and imports no write helpers.
- Produces (CDK): `/v1/{proxy+}` on the same HTTP API with an authorizer requiring scope `jobmecloud/jobs.read`; a machine app client (client-credentials) and resource server; route throttling of 5 requests per second, burst 10.

- [ ] **Step 1:** Tests: `test_list_filters_by_min_score_and_status`, `test_pagination_cursor_roundtrip`, `test_detail_404`, `test_limit_capped_at_200`, `test_no_write_routes_exist` (every route is GET), `test_openapi_served`, CDK `test_v1_requires_jobs_read_scope`.
- [ ] **Step 2:** FAIL. **Step 3:** Implement; document how to create a machine client and get a token in `docs/external-api.md`. **Step 4:** PASS; after deploy, a machine token reads `/v1/jobs` and a browser token gets 403. **Step 5:** Commit `feat: read-only external api`.

---

## Self-review notes

- **Spec coverage:** architecture, four Lambdas, DSQL changes, S3/SSM, auth (native users, MFA, no SMS/Google), Scheduler, open-source docs and cost table are in Tasks 1–11; SES, tailoring agent and external API are Tasks 12–14. Bedrock, SMS MFA and Google sign-in are non-goals in the spec and appear in no task.
- **Known unknowns resolved inside tasks:** DSQL identity behavior under SQLAlchemy (Task 2 integration test); Cognito email MFA through SES in sandbox and the exact CDK properties for the Essentials plan (Task 7; confirm in the AWS docs and note any L1 override needed); DSQL read-only role syntax (Task 14); regional availability of DSQL, Cognito and SES (Task 11 docs).
- **Order:** sequential. Task 8 is the first deployable app; Task 11's manual gate proves the docs; Stage 2 tasks can run in any order.
