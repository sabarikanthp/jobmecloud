# JobMeCloud

JobMeCloud is an open-source job-search assistant that runs in **your own AWS account**. It searches for postings that fit what you are looking for, scores them, keeps track of every application, and writes a tailored resume and cover letter for your best matches. You bring your own AI provider key (Anthropic, or any OpenAI-compatible service). Nobody else can see your data: it lives in your AWS account, behind a sign-in with two-step verification.

It is built to cost almost nothing to run (see [docs/costs.md](docs/costs.md)): everything is serverless and sits inside AWS's free allowances for one person. The only real cost is the AI provider you choose, and how you use it matters: an AI-driven web search can cost $1 or more per run, while reading a report that another tool emailed you costs cents.

JobMeCloud is the cloud version of JobMe, which runs on one computer. The search and document-writing agents (JobScout and ApplyDocs) are the same.

## What you get

- Automatic runs even when your computer is off, in either of two ways: scheduled web searches at the days and times you pick, or (usually far cheaper) a daily **emailed report** from another tool, which JobMeCloud researches, scores and acts on by itself ([docs/email-ingest.md](docs/email-ingest.md)).
- A score from 0 to 100 for every posting, against your wishes and deal-breakers.
- A tailored resume and cover letter for the best matches, checked so they never claim anything that is not in your real resume.
- A tracker for every job, contact and follow-up.
- Sign-in with your email and password plus an authenticator app or an email code. There is no public sign-up: only the account you create can get in.

## Set it up

You need an AWS account, about an hour for the first time, and a laptop with a terminal. Follow **[docs/deploy.md](docs/deploy.md)**, which starts from creating the AWS account.

Prefer to be guided? Paste the prompt in [docs/prompts/deploy-with-an-agent.md](docs/prompts/deploy-with-an-agent.md) into an AI coding assistant such as Claude Code and it will walk you through every step, doing the typing and checking while you do the few things only a person can.

You need these tools: AWS CLI v2, uv, Node.js 22 or 24 (LTS), the AWS CDK and Git (the guide has install links and checks). In short (the first-time steps, such as verifying your email with SES and `cdk bootstrap`, are in the guide):

```
uv run python scripts/build_lambdas.py
cdk deploy -c owner_email=you@example.com -c sender_email=you@example.com
uv run python scripts/migrate_db.py
uv run python scripts/create_owner.py --email you@example.com
(cd frontend && npm install && npm run build)
uv run python scripts/publish_site.py
```

Optional extras, each documented in the guide: your own web address (`-c site_domain=... -c certificate_arn=...`) and runs driven by an emailed report (`-c inbound_address=... -c inbound_sender=...`).

## Guides

| Guide | What it covers |
|---|---|
| [docs/deploy.md](docs/deploy.md) | From zero to a working site: AWS account, tools, deploy, first sign-in |
| [docs/costs.md](docs/costs.md) | What it costs, what is free, and how to set a spending alert |
| [docs/security.md](docs/security.md) | Where your data lives, who can reach it, and what to do if a key leaks |
| [docs/architecture-guide.md](docs/architecture-guide.md) | How it works: architecture, AWS resources, data flow, security, cost |
| [docs/email-ingest.md](docs/email-ingest.md) | Optional: start runs from a daily emailed report instead of paying for searches |
| [docs/migrating-from-local.md](docs/migrating-from-local.md) | Bringing your data over from the local JobMe app |
| [docs/operations.md](docs/operations.md) | Updating, backups and uninstalling |
| [docs/account-recovery.md](docs/account-recovery.md) | Forgot your password or lost your authenticator? Start here |
| [docs/troubleshooting.md](docs/troubleshooting.md) | The problems people hit most, and the fixes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Working on the code |

## How it works

```
Browser -> CloudFront -> S3 (the website)
                      -> API Gateway (needs a signed-in token) -> api Lambda
api Lambda -> run-worker Lambda (reads, scores, searches) and docs-worker Lambda (writes documents)
EventBridge Scheduler -> run-worker Lambda                       (optional web-search schedule)
Emailed report -> SES -> mail bucket -> ingest Lambda -> run-worker Lambda   (optional)
All Lambdas -> Aurora DSQL (database), S3 (files), SSM Parameter Store (your API keys)
Cognito -> sign-in with MFA
```

The diagram and a walk through every resource are in [docs/architecture-guide.md](docs/architecture-guide.md). The design documents are [the AWS migration design](docs/superpowers/specs/2026-11-14-aws-migration-design.md) and [the email ingest design](docs/superpowers/specs/2026-11-16-email-ingest-design.md).

## License

MIT. See [LICENSE](LICENSE).
