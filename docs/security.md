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
| Emailed reports (optional) | A private S3 mail bucket, deleted after 30 days | Public access blocked, encrypted, HTTPS only. Only mail from your one sender address is kept; the message itself is deleted at once for anyone else |

## Who can get in

- The website needs a **signed-in token**. There is no public sign-up, so only the account created with `scripts/create_owner.py` exists.
- Sign-in requires your **password plus a second step** (authenticator app or email code). A password alone never produces a token.
- Every API route except `/api/mcp` and the connector sign-in routes below is checked by API Gateway's JWT authorizer before any code runs.
- **Emailed reports (if you turn them on)** can only start a run if the message is addressed to your report address, comes from your one allowed sender, passes SES's spam and virus checks and carries a valid DKIM signature for the sender's domain. Mail from anyone else is deleted at once and never shown or acted on (a one-line record of the sender address and the word `ignored` stays in the database). At most `inbound_daily_limit` runs start a day, and messages over 2 MB are refused unread. The report text is treated as untrusted: the AI call that reads it has no tools and can only list roles; links are fetched by the same checked page fetcher as everything else.
- **Claude Desktop access (if you create a key).** One route, `/api/mcp`, is open to API Gateway without a sign-in token, because Claude Desktop cannot sign in with Cognito. The app checks a key instead: keys are random, only a hash is stored, each is shown once, and each can be read-only or read-and-change, expire, and be revoked in Settings. There is a per-minute limit and a daily limit on tools that spend AI money. The tools cannot delete anything or touch settings, AI keys or key management. Changes made this way are recorded as "by Claude: key name". Job postings and notes are labelled untrusted when handed to Claude, but a read-and-change key in a chat that reads a hostile posting is a risk: use read-only keys by default. See [claude-desktop.md](claude-desktop.md).
- **ChatGPT and Claude connectors (sign-in with OAuth).** Four more routes are open to API Gateway because a connector has no login yet: `/.well-known/*` (public metadata), `/api/oauth/register`, `/api/oauth/authorize` and `/api/oauth/token`. Each checks what it is given: registration is rate-limited and capped and only accepts https (or localhost) return addresses; authorize never sends the browser to an address that was not registered; the token swap needs a one-time code (5 minutes, spent on first use) and a PKCE secret that only the real app holds. Nothing is granted until **you**, signed in with your password and two-step verification, approve it on the consent page: that call (`/api/oauth/approve`) is behind the normal sign-in. You choose read-only or read-and-change per connection. Each connection is a normal entry under Settings, Claude access: it can be revoked there, it has the same rate and AI-spend limits as a key, and its access token lasts one hour (the connector renews it for up to 30 days; nothing else is stored in clear: tokens and codes are kept only as hashes). If a used code is ever presented again, the connection it created is revoked. See [chatgpt.md](chatgpt.md).
- The data bucket and the website bucket cannot be read directly: the website is served only through CloudFront.
- Permissions are narrowed where it is practical. The scheduler can start only the search worker. The API can manage only schedules whose names begin `jobmecloud-run-`. Only the API can save or delete your API keys; the workers can only read them.
- Honest limit: every function connects to the database as the cluster's **admin role**, because the app creates and updates its own tables. The Claude Desktop door (below) uses the same role, so its limits come from the app's own checks, not from the database.

## What leaves your account

- **To your AI provider:** posting text, your resume and profile text, and prompts, so the model can read, score and write; and, if you use emailed reports, the text of each report. Choose a provider whose terms you accept. Postings are read from public web pages.
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

Please use the repository's private **Security advisories** feature (the Security tab on GitHub) rather than a public issue. The full policy is in [SECURITY.md](../SECURITY.md).
