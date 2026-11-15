# Security

JobMeCloud is built for one person. Your data lives in **your own AWS account**; the project has no servers of its own and never sees your data.

## Where your data is

| What | Where | Protection |
|---|---|---|
| Jobs, contacts, follow-ups, activity | Aurora DSQL database | Encrypted at rest by AWS; reachable only by the app's Lambdas (IAM) |
| Resume, profile, settings, generated documents, run logs | A private S3 bucket (versioned) | Public access blocked, encrypted, HTTPS only. Downloads use links that expire after 15 minutes |
| Your AI and search API keys | SSM Parameter Store, as encrypted `SecureString` values under `/jobmecloud/` | Only the app's Lambdas can read them. The website can save a key but never shows it again |
| Your email and password hash | Cognito | Managed by AWS |
| Lambda logs | CloudWatch, kept 14 days | Written by the app, never including API keys |

## Who can get in

- The website needs a **signed-in token**. There is no public sign-up, so only the account created with `scripts/create_owner.py` exists.
- Sign-in requires your **password plus a second step** (authenticator app or email code). A password alone never produces a token.
- Every API route is checked by API Gateway's JWT authorizer before any code runs.
- The data bucket and the website bucket cannot be read directly: the website is served only through CloudFront.
- Lambdas have the smallest permissions that work. The scheduler can start only the search worker. The API can manage only schedules whose names begin `jobmecloud-run-`.

## What leaves your account

- **To your AI provider:** posting text, your resume and profile text, and prompts, so the model can read, score and write. Choose a provider whose terms you accept. Postings are read from public web pages.
- **To the search provider** (Anthropic web search, Tavily or Brave): the search queries.
- Nothing else is sent anywhere. There is no telemetry.

## Limits to know about

- **Anyone with admin access to your AWS account can read everything.** Protect that account: use IAM Identity Center or an IAM user with MFA, and lock away the root user ([deploy.md](deploy.md)).
- Tokens are kept in the browser's local storage so you stay signed in. Sign out on shared computers.
- Do not paste real personal data into issues or pull requests on the project.

## If an API key leaks

1. In your AI provider's console, **revoke the key** and create a new one. This is the step that matters.
2. In JobMeCloud open **Settings**, your AI connection, paste the new key and press **Test**.
3. Check the provider's usage page for spending you did not make.

## If you think your sign-in was compromised

Run the reset in [account-recovery.md](account-recovery.md); it deletes and recreates the account, which ends every session that was signed in with the old one once their tokens expire (within an hour). Then rotate any API keys.

## Reporting a vulnerability

Please use the repository's private **Security advisories** feature (the Security tab on GitHub) rather than a public issue.
