# JobMe on AWS: migration design

Date: 2026-11-14. Status: approved by the owner 2026-11-15 (name confirmed as JobMeCloud). Revised the same day: Bedrock deferred, login changed to Cognito with required MFA, open-source documentation made a goal, delivery split into two stages.

**Repo and naming (decided by the owner):** this is built in a **new repository** under a **new app name**: **JobMeCloud** (repo and package `jobmecloud`; the owner wrote "obmecloud", read as a typo, to be confirmed). It is referred to below as `<newapp>`. The existing JobMe repo stays as the local app and is the reference to copy from. The agents keep their names (JobScout, ApplyDocs). The Python package, CDK stack, resource names and UI title use `<newapp>`. Where this doc says `jobme` (for example `JOBME_*` settings or the package name), read `<newapp>`.

**Consequence for scope (my call, replacing the earlier "keep local mode working"):** because the old repo remains the local app, the new repo is **AWS-only**. It drops the Windows task scheduler, keyring backend, "change data folder" feature and Word COM page counting instead of maintaining dual backends. SQLite stays only as the fast test/dev database, with in-memory fakes for S3 and SSM in tests, so the 24k lines of tests mostly carry over. Phase 2 therefore builds S3/SSM implementations only, not an abstraction with a local-disk twin.

## Intent and why

JobMe is a local, Windows-first, single-user job-search app (FastAPI + SQLite + React, with a JobScout search agent and an ApplyDocs resume/cover-letter writer). The owner wants to run it on AWS for personal use because:

- they want it available from anywhere with scheduled searches that don't depend on a PC being on,
- they want hands-on experience building agents and serverless AWS systems,
- they want an API that other tools can call to read job data.

Cost must be as close to zero as possible. The only unavoidable variable cost is the LLM usage the owner already pays for.

## Goals

- Run the existing app on AWS for one user at roughly $0 per month of AWS cost, excluding LLM spend.
- Model access with an API key (Anthropic, or any OpenAI-compatible provider) kept in SSM, as in the current app. Bedrock is deferred to a later stage.
- Scheduled runs via EventBridge Scheduler, managed from the existing Settings schedule screen.
- Email via SES (sandbox, to the owner's own verified address): a digest after runs plus follow-up reminders.
- Static frontend on S3 behind CloudFront. Login with Cognito (email and password) with MFA required: authenticator app (for example Google Authenticator) and email code. No self sign-up.
- **Open source:** anyone can deploy and use it. The repo ships a step-by-step deployment guide that starts from creating an AWS account, plus a cost estimate, security notes, update and uninstall steps, and troubleshooting.
- **Simple and usable first:** stage 1 delivers a working, deployable app; the tailoring agent, email digests and external API follow in stage 2.
- Separate Lambdas behind an API Gateway HTTP API, split by role (see Architecture).
- A read-only external API (`/v1/...`) for other tools to query jobs, with its own scoped credentials.
- Turn the resume/cover-letter writer into a real tool-using agent (the owner wants the agent-writing practice).
- Code runs in AWS on Aurora DSQL; SQLite is kept only for tests and quick local development of the new repo.

## Non-goals

- Multi-user, teams, billing, or tenant isolation.
- Writes through the external API (read-only first).
- Bedrock AgentCore, Step Functions, or any managed agent framework. The hand-written loop in `llm/loop.py` stays.
- Rewriting the frontend. Only auth and API-base-URL changes.
- Bedrock (later stage), Google/social sign-in, and phone/SMS MFA (SMS is billed per message through SNS and new accounts start in the SMS sandbox; it can be enabled later with one setting).

## Anti-goals (failure even if it works)

- A fixed monthly charge: no NAT gateway, VPC endpoints, provisioned capacity, Aurora/RDS instances, or Secrets Manager secrets.
- The tailoring agent inventing facts about the owner (the truthfulness guarantee must stay enforced in code, not in the prompt).
- Anything reachable without login except the sign-in redirect.
- Losing the existing test coverage when porting code into the new repo.

## Constraints

- Single user, personal data (resume, contacts, applications). Everything private by default.
- Python 3.12 backend with SQLModel; the code must run on both SQLite (local, tests) and Aurora DSQL (AWS).
- A run takes minutes; Lambda's limit is 15 minutes. API Gateway's synchronous limit is 30 seconds, so runs are always asynchronous.
- Windows-only features (Word COM page counting, Windows Task Scheduler) have no AWS equivalent.

## Approaches considered

Data store:

| Option | Verdict |
|---|---|
| DynamoDB | Cheapest and most AWS-native, but means rewriting about 13 relational tables and their queries. Rejected: effort outweighs the savings. |
| SQLite file in S3 | Near-zero cost and least rewrite, but several concurrent Lambdas would overwrite each other's writes (one file), needing compare-and-swap retry code around every write. Rejected once multiple Lambdas were chosen. |
| **Aurora DSQL (chosen)** | Serverless Postgres. Always-free tier of 100,000 DPUs and 1 GB per month, scale to zero, no VPC. Foreign keys, JSON/JSONB, and SQLAlchemy are supported. Needs the code changes listed below. |

Lambda layout:

| Option | Verdict |
|---|---|
| One monolith Lambda | Simplest, but one 15-minute-capable, widely permissioned function serves everything. Rejected. |
| **Few Lambdas split by role (chosen)** | Separate timeout, memory and IAM per role. |
| One Lambda per route group (about 19) | Purest, but multiplies packaging and cold starts for no benefit at this scale. Rejected. |

## Architecture

```
Browser -> CloudFront --+-- S3 (static frontend)
                        +-- /api/*  -> API Gateway (HTTP API, Cognito JWT authorizer)
                                         +-- api        Lambda (FastAPI)
                                         +-- ext-api    Lambda (/v1 read-only)
api  --async invoke--> run-worker / docs-worker Lambdas
EventBridge Scheduler --> run-worker (search runs), run-worker {task: digest}
All Lambdas -> Aurora DSQL (IAM auth) | S3 data bucket | SSM Parameter Store | Anthropic / OpenAI-compatible API | SES
```

### Frontend and edge
- S3 (private, origin access control) behind CloudFront. The `/api/*` behavior routes to API Gateway, so the SPA and API share one origin (no CORS).
- Default `*.cloudfront.net` domain. A custom domain is optional and is the only thing that would add cost (Route 53 hosted zone, about $0.50 per month).
- Frontend changes: Cognito sign-in (hosted UI, authorization-code flow with PKCE), attach the access token to API calls, handle 401 by re-login.

### Auth
- Cognito user pool with **native users** (email and password) and **self sign-up disabled**. The only account is created by a deploy script (`scripts/create_owner.py`) for the owner's email. Essentials feature plan, which is free for the first 10,000 monthly users, so $0 here.
- **MFA required** with two factors enabled: an authenticator app (TOTP, free; Google Authenticator or any compatible app) and an email code (sent through SES, needs the Essentials plan). At first sign-in the hosted login makes the user set a password and register a factor. Having both is the fallback if the phone is lost.
- **Phone/SMS MFA is out of scope** for cost and setup reasons (see Non-goals).
- **No Google sign-in:** Cognito delegates authentication for federated users to the provider and does not apply its own MFA to them, and every deployer would have to create a Google OAuth client. Native users with MFA are simpler and give real 2FA.
- **Password recovery:** self-service reset is off (an email address cannot be both an MFA factor and the recovery channel). Recovery is `scripts/reset_owner.py` run with the deployer's AWS admin credentials. The docs explain this.
- Public browser app client (authorization-code with PKCE, hosted login). API Gateway JWT authorizer on all `/api` routes.
- For stage 2: a machine app client (client-credentials) and a resource server scope exactly `jobs.read` for the external API. Browser tokens must not reach `/v1`; machine tokens must not reach the app API.
- `TrustedHostMiddleware` allowed hosts become configurable (CloudFront domain).

### Lambdas (all arm64, Python 3.12)

| Lambda | Role | Timeout / memory | Permissions |
|---|---|---|---|
| `api` | The existing FastAPI app (CRUD, settings, setup wizard, uploads, "Run now" and "Make docs" start worker invokes) | 30 s / 512 MB | DSQL read-write, data bucket, SSM, Scheduler, invoke workers |
| `ext-api` | `/v1` read-only job queries | 10 s / 256 MB | DSQL **read-only** database role, nothing else |
| `run-worker` | JobScout run (search agent, read/score/recheck); also the daily digest task | 15 min / 1 GB | DSQL read-write, data bucket, SSM, SES |
| `docs-worker` | Tailoring agent and Word rendering for one job | 5 min / 1 GB | DSQL read-write, data bucket, SSM |

The `api` Lambda runs FastAPI through an ASGI adapter (Lambda Web Adapter or Mangum; builder's choice). The worker handlers are thin wrappers around existing `execute_run` and ApplyDocs code.

### Runs and scheduling
- "Run now" and scheduled runs both end up in `run-worker`. The `Run` row and `RunLock` table (with heartbeat and stale detection) already provide the single-run guarantee. They move to DSQL as is and must be retested under optimistic concurrency.
- The thread-based start in `routes_runs.py` becomes an async Lambda invoke. The UI keeps polling run status from the `Run` table as today.
- `scheduling/windows_task.py` is replaced by an EventBridge Scheduler adapter. The Settings schedule screen (days, times) creates, updates or deletes one schedule per entry with a target of `run-worker` and payload `{"trigger": "schedule"}`. The local Windows adapter stays for local mode behind the same interface.

### Data
- Aurora DSQL, one cluster, IAM authentication (short-lived token per connection, generated with boto3). Connection lifetime is under the 1-hour DSQL limit, which fits Lambda.
- Code changes required (all verified against the DSQL docs):
  1. Primary keys: DSQL identity columns must be `bigint` with an explicit `CACHE` of 1 or at least 65536 (we use 1), so SERIAL-style autoincrement is replaced for the Postgres dialect (`BigInteger` with `Identity(cache=...)`, or app-generated IDs; builder's call).
  2. `add_missing_columns` in `db/session.py` uses SQLite `PRAGMA table_info`. Rewrite it dialect-aware. On DSQL `ADD COLUMN` takes a type only (no DEFAULT or NOT NULL in the same statement), so a default must be applied in a second step or handled in the model.
  3. Optimistic concurrency: wrap write transactions in a retry for serialization failures.
  4. A transaction may modify at most 3,000 rows. The spreadsheet, tracker and text importers must commit in batches.
  5. Remove SQLite PRAGMAs on the Postgres path. Keep them for SQLite.
  6. DDL and DML must be in separate transactions; `CREATE INDEX` must be `CREATE INDEX ASYNC`. Table creation at startup moves from per-request `create_all` to an explicit migration step run at deploy time.
- Local mode and tests keep using SQLite. A `JOBME_DB_URL`-style setting selects the engine.

### Files, settings and secrets
- The "data folder" becomes a storage abstraction with a local-disk implementation and an S3 implementation (private bucket, versioning on, presigned URLs for downloading resumes and generated documents). Run transcripts (`logs/run-*-search.json`), generated `.docx`, uploaded resumes, `profile/*.yaml` and `settings.yaml` all go through it.
- Rendering and uploads stage in Lambda `/tmp`.
- `secrets.py` gets an SSM Parameter Store SecureString backend (standard tier, free) alongside the keyring backend. Same names (`provider:<id>`, `search:<backend>`).
- The "change data folder" feature (`storage.py`, `routes_storage.py`) is hidden in AWS mode.

### Models
Unchanged from the current app: Anthropic and OpenAI-compatible providers, API key in SSM, Anthropic's built-in web search as today. Bedrock is deferred; the `Provider` protocol already leaves room for it.

### Agents
- **Search agent** (existing): unchanged logic, runs in `run-worker`, same caps (turns, searches, spend).
- **Tailoring agent** (new): replaces the fixed draft, check, revise chain in `applydocs/tailor.py` with a tool-using agent on the same `run_agent` loop. Tools:
  - `get_master_resume`, `get_job`, `get_preferences` (read-only),
  - `fetch_url` and `web_search` (reuse the search agent's fetcher and backends, including their blocked-domain and untrusted-content handling) so it can research the company and role,
  - `check_draft` (runs the existing `self_check`), and
  - `submit_draft` (terminal tool).
- **Hard gate (code, not prompt):** whatever the agent submits is run through `self_check` against the Master Resume before it is saved. If problems remain after a fixed number of revisions, the documents are saved flagged "needs review" instead of passing silently. The "Allowed / Not allowed" truthfulness rules stay in the system prompt as guidance, but the gate is what enforces them.
- Same cost tracker, turn cap and per-run spend limit as the search agent. Page-count checking via Word COM is Windows-only; in AWS mode it is skipped and the output notes that page count wasn't verified (my call; a LibreOffice layer was rejected as too heavy).
- Existing JobScout steps (extract, liveness, score) stay single structured calls, not agents.

### Email (SES, sandbox)
- One verified identity (the owner's address) as both sender and recipient, which is all sandbox allows without a request.
- Two emails: a **digest** after each scheduled run (new jobs at or above the match cutoff, plus count of closed ones) and a **daily follow-up reminder** (follow-ups due today). Reminders are sent by `run-worker` on a second EventBridge schedule with payload `{"task": "digest"}`. Nothing is sent if there is nothing to report.
- Settings gets an on/off toggle for each. The digest must not include API keys or full resume text.

### External API
- `GET /v1/jobs` (filters: `status`, `min_score`, `since`, `q`; cursor pagination), `GET /v1/jobs/{id}` (details, score, rationale, status, contacts and follow-ups summary), `GET /v1/runs/latest`. JSON with a published OpenAPI spec.
- Separate `ext-api` Lambda using a read-only DSQL role, so the machine credential can never modify data. Requires scope `jobs.read`. Throttled by API Gateway route settings.

### Infrastructure as code and deploy
- AWS CDK in Python (matches the backend language) in an `infra/` folder, one stack. Lambda code is built with `uv`-resolved dependencies into zips (no container images) and shared code goes in a layer.
- Deploy is one command (`cdk deploy`) plus two small scripts: one runs the DSQL schema migration, the other creates the owner account (`scripts/create_owner.py`). The only manual steps are the AWS account setup and verifying the SES sender address, both covered in `docs/deploy.md`.
- Cost guards: an AWS Budgets alert at $5 per month, CloudWatch log retention of 14 days, no X-Ray, no provisioned concurrency.

### Estimated AWS cost (excluding LLM spend)
Expected to be $0 to $2 per month at one user, mostly inside free tiers: Lambda, DSQL (100,000 DPUs and 1 GB free per month), SSM, EventBridge Scheduler, Cognito Essentials (10,000 free monthly users), CloudFront and S3 at this volume. API Gateway HTTP API is about $1 per million requests after its first-year free allowance (cents for one user). SES email is $0.10 per 1,000 messages. The docs must show this as a table, link to the AWS pricing pages, tell deployers to re-check free-tier terms (they change), and explain that LLM spend is separate and the biggest variable cost (the per-run spend cap exists for this).

## Open-source documentation requirements

The repo must let a stranger deploy and use it without help:
- `README.md`: what it is, a short description or screenshots, what it costs, and links to the guides.
- `docs/deploy.md`: from zero. Create an AWS account; set a billing alert; do not use the root user (create an admin user with IAM Identity Center or an IAM user with MFA); install the AWS CLI, Node.js, uv and the CDK; configure credentials; pick a region (confirm DSQL, Cognito and SES availability there); bootstrap CDK; verify the SES sender address; deploy; create the owner account; first sign-in and MFA setup; add the AI provider key; first run.
- `docs/costs.md`: the cost table above with assumptions, how to set a budget alert, and how to estimate LLM spend.
- `docs/security.md`: what is stored where, that data is private to the deployer's account, the sign-in model, and what to do if a key leaks.
- `docs/operations.md`: updating, backups (S3 versioning; exporting DSQL data), recovering a lost authenticator or password, and uninstalling (`cdk destroy`, what is retained).
- `docs/troubleshooting.md`: the common failures (SES sandbox, MFA email not arriving, region mismatch, CDK bootstrap, DSQL permissions).
- `CONTRIBUTING.md`, `LICENSE`, and no personal data or real profile in the repo (examples only).

## Phases (each shippable and tested)

**Stage 1: a working app you can use**
1. Bootstrap the new repo from JobMe.
2. Data layer: engine factory, DSQL-compatible keys and migrations, conflict retry, batched imports.
3. SSM secrets and S3 workspace sync, cloud-mode app, `api` Lambda handler.
4. CDK foundation, then Cognito (MFA) plus API Gateway, CloudFront and frontend sign-in. First usable deployment.
5. `run-worker` and `docs-worker` with async "Run now" and "Make docs", then EventBridge Scheduler.
6. Open-source documentation and the build script.

**Stage 2: once you are using it**
7. SES digest and follow-up reminders.
8. Tailoring agent with the `self_check` gate.
9. Read-only external API with machine credentials.

## Risks and things to verify early

- DSQL identity/SQLAlchemy behavior and DPU consumption under a real run (spike in phase 2).
- Cognito email MFA through SES while SES is in sandbox: confirm the code email reaches the owner's verified address and that the Essentials plan is selected.
- DSQL, Cognito and SES must all be available in the chosen region; the docs must say how to check.
- 15-minute worker limit versus a slow run: the pipeline's cost and search caps must keep a run well under it, with a clean "stopped early" result if time runs short.
- The deployment guide is only as good as its testing: someone other than the author should follow it on a fresh AWS account before the repo is announced.

## Decisions I made (not yet confirmed by the owner)

- Split by role into four Lambdas, with `ext-api` separate (stage 2) for least privilege.
- CDK in Python for infrastructure.
- Native Cognito user with required MFA (authenticator app plus email), no Google sign-in, no SMS, self sign-up off.
- Cognito client-credentials for the external API instead of API keys (stage 2).
- S3 workspace sync keeps the existing path-based code instead of rewriting file access.
- Skip page-count verification in AWS mode.
- Digest and reminder emails as the SES use case (stage 2).
- AWS-only new repo (see top), rather than a dual local/AWS codebase.
- Default CloudFront domain, no custom domain.

## What changed since this was approved (added 2026-11-16)

This design is kept as it was agreed; this note records where the built system differs, and why.

- **Search cost.** Running the AI provider's built-in web search on a schedule cost $0.70 to $2.10 per run, almost all of it input tokens re-read inside a single provider call, and the per-run spending cap is only checked between AI calls. This changed the design: see [the email ingest design](2026-11-16-email-ingest-design.md), which lets another tool do the searching and email JobMeCloud the report. Stage 2 became that feature first.
- **Lambdas.** Four, not the three described here as stage 1 plus an `ext-api`: `api`, `run-worker`, `docs-worker` and (optional) `ingest`. The `ext-api` (read-only external API) is still not built.
- **Custom address.** An optional CloudFront hostname and ACM certificate (`site_domain`, `certificate_arn`) were added, with no custom CloudFront error pages (they rewrote API 404s).
- **Aurora DSQL.** The facts the build depends on were learned against a real cluster: identity columns need `CACHE 1` (or 65,536 and up), no `SAVEPOINT` (so SQLAlchemy's hstore lookup is disabled and the run lock is written without savepoints), optimistic-concurrency retries, at most 3,000 rows per transaction.
- **Still not built:** SES digest and reminder emails, the tool-using tailoring agent, the read-only external API, Bedrock as a provider.

## Left to the builder

ASGI adapter choice; exact identity or ID-generation scheme; schema migration tooling; Lambda packaging details; tool descriptions and prompts for the tailoring agent; email templates; frontend sign-in library.
