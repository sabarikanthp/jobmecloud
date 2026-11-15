# Operating JobMeCloud

## Update to a new version

```
git pull
uv sync
uv run python scripts/build_lambdas.py
uv run cdk deploy -c owner_email=you@example.com -c sender_email=you@example.com -c timezone=America/Chicago
uv run python scripts/migrate_db.py
(cd frontend && npm install && npm run build)
uv run python scripts/publish_site.py
```

Use the same `-c` values you deployed with. `cdk deploy` shows a summary of what will change and asks before applying it; read it. `migrate_db.py` is safe to repeat: it only adds what is missing. The release notes say if anything needs more than this.

## Backups

- **Files** (resumes, profile, settings, generated documents): the data bucket has **versioning** on, so an overwritten or deleted file can be restored from its earlier version in the S3 console (turn on **Show versions**).
- **The database** (jobs, contacts, follow-ups): Aurora DSQL keeps your data redundantly across availability zones, and the cluster has **deletion protection** on so it cannot be deleted by accident. The app has no export button yet. If you want your own copy, check whether AWS Backup supports Aurora DSQL in your region (the AWS docs say) and set up a backup plan there.
- **API keys** are in Parameter Store under `/jobmecloud/`. Keep the keys themselves in your password manager, since you cannot read them back from the app.

## Where things are

| Thing | Where to look |
|---|---|
| Logs | CloudWatch, log groups named after the functions (`...ApiFunction...`, `...RunWorkerFunction...`, `...DocsWorkerFunction...`). Kept 14 days |
| A run's step-by-step record | The `logs/` folder in the data bucket (one file per run) |
| The schedule | EventBridge, **Scheduler**, schedules named `jobmecloud-run-HHMM` (change them in Settings, not here) |
| Spending | Billing and Cost Management, Budgets and Cost Explorer ([costs.md](costs.md)) |

## Limits to know about

- **One person, one browser tab at a time.** Settings and files are kept in S3 and shared between Lambdas. If two things change the same file at the same moment (for example, saving Settings while a run finishes), the last one saved wins. This is fine for one person and is not designed for teams.
- **Only one run or documents job at a time.** A second request is told "A run is already in progress."

## Lost password or authenticator

See [account-recovery.md](account-recovery.md).

## Uninstall

`cdk destroy` removes the stack, but it deliberately **keeps your data**: the database has deletion protection, the sign-in user pool has deletion protection, and the S3 buckets are set to **retain**. So uninstalling takes a few manual steps:

1. Download anything you want to keep (documents from the data bucket).
2. In the **Aurora DSQL** console, open your cluster and turn off **deletion protection**.
3. In the **Cognito** console, open your user pool and turn off **deletion protection**.
4. Run `uv run cdk destroy`.
5. Delete the two **retained S3 buckets** (names start with the stack name): empty each one first, including all versions (**Show versions**, select all, delete), then delete the bucket.
6. Delete your saved API keys: Parameter Store, parameters starting `/jobmecloud/`.
7. Delete the Cognito domain prefix and the SES verified identity if you no longer want them.

Leaving everything in place costs almost nothing; see [costs.md](costs.md).
