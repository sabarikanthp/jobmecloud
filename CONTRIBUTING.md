# Contributing to JobMeCloud

Thanks for helping. Bug reports, fixes, docs improvements and ideas are all welcome.

## Before you open an issue or pull request

- **Never include personal data**: no resumes, real names or emails, AWS account numbers, access keys, API keys or run logs. Use made-up examples (`jordan@example.com`, account `123456789012`).
- Report security problems privately, as described in [docs/security.md](docs/security.md).

## Set up for development

```
uv sync
cd frontend && npm install && cd ..
uv run pytest -q          # backend and infrastructure tests (no AWS account needed)
cd frontend && npm test && npm run build
```

The tests use fake AWS services (moto), so they never touch a real account. A few tests marked `dsql` need a real Aurora DSQL cluster and are skipped unless you set `JOBMECLOUD_DB_URL=dsql://<endpoint>`. Run them before a release (`uv run pytest -m dsql`): fakes cannot show the database's real rules. For the same reason `tests/test_schemas.py` checks every structured-output schema against the AI provider's rules.

You need Python 3.12 (`uv` installs it), Node.js 22 or 24, and Git. The repository stores text files with LF line endings (`.gitattributes`); if your editor or a script rewrites them as CRLF, Git normalises them on commit.

## How the code is laid out

| Path | What is there |
|---|---|
| `backend/jobmecloud/agents/jobscout` | The search agent and the read, score and recheck steps |
| `backend/jobmecloud/applydocs` | Resume and cover-letter writing |
| `backend/jobmecloud/inbound` | Emailed reports: parsing, trust checks, role extraction, the record of each email, replay |
| `backend/jobmecloud/api` | The FastAPI routes |
| `backend/jobmecloud/handlers` | Lambda entry points (`api`, `run_worker`, `docs_worker`, `ingest`) |
| `backend/jobmecloud/db` | Models, the SQLite/DSQL engine, migrations, write-conflict retry |
| `backend/jobmecloud/admin` | Code behind the helper scripts |
| `infra` | The AWS CDK stack (Python), including the optional custom-domain and emailed-report parts |
| `frontend` | The React website |
| `docs` | The guides, plus the design (`docs/superpowers/specs`) and plans |

## Working style

- **Write the test first** and watch it fail for the reason you expect, then make it pass.
- Run the whole suite before you push: `uv run pytest -q` and `npm test`.
- Keep changes small and say in the pull request what you changed and why.
- Keep the cost promise: nothing with a fixed monthly charge (no NAT gateway, VPC endpoints, provisioned capacity or database instances).
- Anything a fake cannot prove (a database rule, a provider rule, a real email) needs one real check before you call it done, and a test that would have caught it.
- Keep the docs true. If you change a command or a step, change [docs/deploy.md](docs/deploy.md) in the same pull request; `tests/test_docs.py` checks that every script the docs name exists.

## Testing the deployment guide

The most valuable review is following [docs/deploy.md](docs/deploy.md) on a fresh AWS account and fixing every place it was wrong or unclear.
