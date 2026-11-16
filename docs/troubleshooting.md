# Troubleshooting

Start with the symptom. If your problem is a lost password or authenticator, go to [account-recovery.md](account-recovery.md).

## Deploying

**`cdk bootstrap` or `cdk deploy` says it cannot find credentials.** Sign in again (`aws sso login --profile <name>`) and set `AWS_PROFILE`. Check with `aws sts get-caller-identity`.

**"This stack uses assets, so the toolkit stack must be deployed."** Run `cdk bootstrap` once in this account and region ([deploy.md](deploy.md)).

**`cdk deploy` says a file is missing in `dist/lambda`.** Run `uv run python scripts/build_lambdas.py` first.

**An AWS service is "not available in this region".** Aurora DSQL, Cognito and SES must all exist in the region. Redeploy in another one (for example `us-east-1`); the regions are listed at <https://aws.amazon.com/about-aws/global-infrastructure/regional-product-services/>.

**The email identity is not verified / `cdk deploy` fails on the user pool email.** SES must have a **verified** identity for `sender_email` in the *same region* you deploy to. Verify it in the SES console and try again.

**`scripts/migrate_db.py` says "No stack named JobMeCloud".** Set `AWS_REGION` to the region you deployed to, or pass `--stack-name`.

**`migrate_db.py` is denied access to the database.** You need admin rights on the account (the same ones you deployed with).

## Signing in

**The temporary-password email never arrives.** Check spam. Check that the address is **verified in SES** (the account is in sandbox mode, so SES only sends to verified addresses) and that you verified it in the region you deployed to. Then run `scripts/reset_owner.py` to send a new one.

**The email code (MFA) never arrives.** The same causes: the sender and your address must both be verified in SES in that region. Sign in with your authenticator app instead, or see [account-recovery.md](account-recovery.md).

**"Your session has ended."** Your sign-in expired. Sign in again.

**I get a Cognito error page about `redirect_uri`.** The site address you opened is not the one the sign-in knows. Open the `SiteUrl` from the deploy output, and run `uv run python scripts/publish_site.py` again.

**The page is blank, or says it could not read the sign-in settings.** Run `scripts/publish_site.py`; it writes `config.json` into the site. Your browser may be holding an old copy: reload without the cache.

## Using the app

**"Couldn't reach JobMeCloud."** Your connection dropped or the API is down. Reload. Check the API function's log group in CloudWatch.

**A page shows "Something went wrong (error 500)".** Open the API's log group (see [operations.md](operations.md)). If you see `unsupported transaction statement: SAVEPOINT`, the deployed functions are running an older build than your code. Run `uv run python scripts/build_lambdas.py` and `cdk deploy` again, then reload.

**A command with a path like `/jobmecloud/...` fails in Git Bash.** Git Bash rewrites it into a Windows path. Run `export MSYS_NO_PATHCONV=1` first, or use PowerShell.

**"Connect an AI first."** Open Settings, your AI connection, paste your API key and press **Test**.

**A run does nothing, or "Add a Tavily or Brave search key".** Only Anthropic's own models can search the web without help. For other providers add a Tavily or Brave key in Settings.

**"A run is already in progress."** One run or document job at a time. A run that was cut off clears itself after about ten minutes.

**A run ends with "Stopped early to stay within the time limit."** The worker has 15 minutes. Lower **Searches per run** or **Applications per run** in Settings.

**"Make docs" takes a long time.** It can take a minute or two. If it says it is taking longer than expected, check the docs worker's log group in CloudWatch.

**Scheduled searches do not run at the right time.** The schedule uses the time zone you gave at deploy (`-c timezone=...`, default UTC). Redeploy with your own.

**The weekday rotation seems a day off.** Same cause: set `timezone`.

## Still stuck

Open an issue (without personal data or keys) with what you did, what you expected and what you saw, plus the relevant lines from the CloudWatch log group.
