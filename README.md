# JobMeCloud

JobMeCloud is an open-source job-search assistant that runs in **your own AWS account**. It searches for postings that fit what you are looking for, scores them, keeps track of every application, and writes a tailored resume and cover letter for your best matches. You bring your own AI provider key (Anthropic, or any OpenAI-compatible service). Nobody else can see your data: it lives in your AWS account, behind a sign-in with two-step verification.

It is built to cost almost nothing to run (see [docs/costs.md](docs/costs.md)): everything is serverless and sits inside AWS's free allowances for one person. The only real cost is the AI provider you choose.

JobMeCloud is the cloud version of JobMe, which runs on one computer. The search and document-writing agents (JobScout and ApplyDocs) are the same.

## What you get

- Automatic searches at the days and times you pick, even when your computer is off.
- A score from 0 to 100 for every posting, against your wishes and deal-breakers.
- A tailored resume and cover letter for the best matches, checked so they never claim anything that is not in your real resume.
- A tracker for every job, contact and follow-up.
- Sign-in with your email and password plus an authenticator app or an email code. There is no public sign-up: only the account you create can get in.

## Set it up

You need an AWS account, about an hour for the first time, and a laptop with a terminal. Follow **[docs/deploy.md](docs/deploy.md)**, which starts from creating the AWS account.

Prefer to be guided? Paste the prompt in [docs/prompts/deploy-with-an-agent.md](docs/prompts/deploy-with-an-agent.md) into an AI coding assistant such as Claude Code and it will walk you through every step, doing the typing and checking while you do the few things only a person can.

In short (the first-time steps, such as verifying your email with SES and `cdk bootstrap`, are in the guide):

```
uv run python scripts/build_lambdas.py
uv run cdk deploy -c owner_email=you@example.com -c sender_email=you@example.com
uv run python scripts/migrate_db.py
uv run python scripts/create_owner.py --email you@example.com
(cd frontend && npm install && npm run build)
uv run python scripts/publish_site.py
```

## Guides

| Guide | What it covers |
|---|---|
| [docs/deploy.md](docs/deploy.md) | From zero to a working site: AWS account, tools, deploy, first sign-in |
| [docs/costs.md](docs/costs.md) | What it costs, what is free, and how to set a spending alert |
| [docs/security.md](docs/security.md) | Where your data lives, who can reach it, and what to do if a key leaks |
| [docs/operations.md](docs/operations.md) | Updating, backups and uninstalling |
| [docs/account-recovery.md](docs/account-recovery.md) | Forgot your password or lost your authenticator? Start here |
| [docs/troubleshooting.md](docs/troubleshooting.md) | The problems people hit most, and the fixes |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Working on the code |

## How it works

```
Browser -> CloudFront -> S3 (the website)
                      -> API Gateway (needs a signed-in token) -> api Lambda
api Lambda -> run-worker Lambda (searches) and docs-worker Lambda (writes documents)
EventBridge Scheduler -> run-worker Lambda
All Lambdas -> Aurora DSQL (database), S3 (files), SSM Parameter Store (your API keys)
Cognito -> sign-in with MFA
```

The full design is in [docs/superpowers/specs/2026-11-14-aws-migration-design.md](docs/superpowers/specs/2026-11-14-aws-migration-design.md).

## License

MIT. See [LICENSE](LICENSE).
