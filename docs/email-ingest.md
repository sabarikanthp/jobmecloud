# Start runs from an emailed report

Instead of paying an AI provider to search the web, you can let another tool do the searching and email JobMeCloud the result. When the report arrives, JobMeCloud takes the roles it recommends, does its own research on each (reads the posting, checks it is still open, scores it against your profile) and writes a tailored resume and cover letter for the ones above your cutoff. Nothing needs you.

This is optional. JobMeCloud works without it.

## What it costs

- AWS: a very small charge per received email, plus pennies of storage. Check [SES pricing](https://aws.amazon.com/ses/pricing/) for the current figure.
- The AI provider: one cheap call to read the report, then one small call per role to read and one to score. Expect cents per report. Writing documents costs more, but only for roles above your cutoff and only up to your per-run limit.
- There is no fixed monthly cost.

## What you need

- A **domain you control**, where you can add DNS records (Cloudflare, Route 53 or any other provider). Use a subdomain such as `mail.example.com` so your normal mail is untouched.
- A tool that can email you a job report on a schedule, from **one fixed address that signs its mail with DKIM** (Gmail and most providers do).
- The report should give each role's employer, title and a **direct link to the posting**, with a plain verdict (recommend, consider, strong, or applied, rejected, skipped, excluded, already seen). JobMeCloud reads ordinary prose, so no special format is needed.

## Set it up

1. **Pick two addresses.** The report address, for example `reports@mail.example.com`, and the one sender address allowed to use it, for example `you@example.net`.
2. **Verify the subdomain in SES.** In the console (region `us-east-1`, or another region where SES can receive email: check the AWS documentation), open **Amazon SES**, **Identities**, **Create identity**, choose **Domain**, enter `mail.example.com` and keep **Easy DKIM** on. Or run `aws sesv2 create-email-identity --email-identity mail.example.com`.
3. **Add the DNS records at your provider.**
   - The three DKIM `CNAME` records SES shows you. On Cloudflare set each to **DNS only** (grey cloud).
   - One `MX` record: name `mail` (so `mail.example.com`), value `inbound-smtp.us-east-1.amazonaws.com` (use your region), priority `10`.
   Wait until SES shows the identity as **Verified**.
4. **Deploy with two extra settings** (use the same `-c` values as always, plus these):
   ```
   uv run python scripts/build_lambdas.py
   cdk deploy -c owner_email=... -c sender_email=... -c inbound_address=reports@mail.example.com -c inbound_sender=you@example.net
   uv run python scripts/migrate_db.py
   ```
   `inbound_daily_limit` (default 5) caps how many emailed reports may start a run per day. If another SES receiving rule set is already active in the region, the deploy stops with a message and changes nothing: add a rule for the report address to that rule set yourself, or deactivate it, and deploy again.
5. **Send a test email** from the sender address to the report address, with a short report naming one real role and its link. Within a minute `uv run python scripts/reprocess_email.py --list` shows it as `started`, then `done`, and the **Today** screen says "Last report … (from email)".
6. **Point your report at the address**, then switch off scheduled web search in **Settings** (delete the schedule) so only the email drives runs. **Run now** still works as a manual search.

## What it does with each email

1. Checks the message. It must be addressed to your report address, come from your sender address, pass SES's spam and virus checks, and carry a valid DKIM signature for the sender's domain. Anything else is recorded as `rejected` and starts nothing.
2. Starts a run, unless the daily limit is reached (`skipped`) or another run or documents job holds the lock for more than about 90 seconds (`waiting`).
3. Reads the report with one AI call and keeps the roles it recommends. Roles marked already seen, applied, rejected, skipped, excluded or closed are dropped, as are roles with no usable link (these are listed in the run's problems). At most 25 roles per report.
4. Reads, checks and scores each role like any other run, and writes documents for the ones above your cutoff. Each job keeps the report's verdict and note so you can see why it was imported.

| Status | Meaning |
|---|---|
| `received` | Arrived; being looked at |
| `started` | A run was started for it |
| `done` | The run finished |
| `rejected` | Failed the checks (wrong sender, wrong address, spam, no valid signature) |
| `skipped` | Over the daily limit |
| `waiting` | The run lock stayed busy; the email is kept and can be replayed |
| `failed` | Something went wrong; the note says what |

## Look at it, and run one again

```
uv run python scripts/reprocess_email.py --list
uv run python scripts/reprocess_email.py --key inbound/<message id>
uv run python scripts/reprocess_email.py --key inbound/<message id> --force
```

Without `--force` only `waiting` and `failed` emails are replayed. The key is shown by `--list`.

## Privacy and safety

- Raw emails are kept in a private bucket for 30 days, then deleted.
- The report text is sent to your AI provider so it can be read.
- The report is treated as untrusted text. The model only picks out roles; it cannot change settings, send mail or run anything. Links go through the same page fetcher as every other posting.
- Only your one sender address can start a run, and at most `inbound_daily_limit` runs a day.

## If something does not work

See the email section of [troubleshooting.md](troubleshooting.md).
