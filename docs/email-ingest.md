# Start runs from an emailed report

Instead of paying an AI provider to search the web, you can let another tool do the searching and email JobMeCloud the result. When the report arrives, JobMeCloud takes the roles it recommends, does its own research on each (reads the posting, checks it is still open, scores it against your profile) and writes a tailored resume and cover letter for the ones above your cutoff. Nothing needs you.

This is optional. JobMeCloud works without it.

## What it costs

- AWS: a very small charge per received email, plus pennies of storage. Check [SES pricing](https://aws.amazon.com/ses/pricing/) for the current figure.
- The AI provider: one cheap call to read the report, then one small call per role to read and one to score. Expect cents per report. Writing documents costs more, but only for roles above your cutoff and only up to your per-run limit.
- There is no fixed monthly cost.

## What you need

- A **domain you control**, where you can add DNS records (Cloudflare, Route 53 or any other provider). Use a subdomain such as `mail.example.com` so your normal mail is untouched.
- A tool that can email you a job report on a schedule, from **one fixed address that only you can send as** and that signs its mail with DKIM (Gmail and most providers do). Do not use a shared notification address that a service sends to all its users: anyone else using that service could then send mail that passes every check.
- The report should give each role's employer, title and a **direct link to the posting**, with a plain verdict (recommend, consider, strong, or applied, rejected, skipped, excluded, already seen). JobMeCloud reads ordinary prose, so no special format is needed.

## Example: let a ChatGPT scheduled task do the searching

This is the setup the feature was built and tested with: a chat assistant runs your daily search on its own flat plan, emails the report to your JobMeCloud address, and JobMeCloud does everything after the search. It needs a ChatGPT plan that offers **scheduled tasks** and a **Gmail connection** (check OpenAI's current documentation: these features and the plans that include them change, and this project is not affiliated with OpenAI). Any other tool that can email a report works the same way.

1. **A sending Gmail account.** Use a dedicated Gmail address that only you control, for example `yourname.jobs@gmail.com`, and connect it to ChatGPT through its Gmail connection. This address is your `inbound_sender`.
2. **A scheduled task** that holds your search instructions: the roles, places, pay floor, employers to watch, and how to judge fit. Run it daily.
3. **Tell the task to email the whole report** to your report address from that Gmail account, in the body of the email. A notification email that only holds a link back to ChatGPT is **not** enough: JobMeCloud cannot open a link that needs your login.
4. **Ask for a report JobMeCloud can read.** For each role, give the employer, the title, the **direct link to the posting** (the employer's own careers page or job board, not a search page or a tracking link), the requisition id and pay if shown, and a plain verdict: recommend, consider or strong, or already seen, applied, rejected, skipped, excluded or closed. Roles marked as already known are dropped, so the report can keep listing them for you to read.
5. Follow **Set it up** below, send one test email from the sender account, and when it works point the task at the report address and switch off scheduled web search in JobMeCloud's Settings.

From then on: ChatGPT searches and emails you, JobMeCloud receives the email, researches each recommended role itself (reads the posting, checks it is still open, scores it against your profile), and writes a tailored resume and cover letter for the ones above your cutoff. JobMeCloud does not trust ChatGPT's verdict: its own score decides what happens.

## Set it up

1. **Pick two addresses.** The report address (see the next step for its name) and the one sender address allowed to use it, for example `you@example.net`.
2. **Make the report address hard to guess.** The secrecy of the address is part of the protection, so use an unguessable part, for example `reports-k3x9q2vd@mail.example.com`, and do not publish it.
3. **Verify the subdomain in SES.** In the console (region `us-east-1`, or another region where SES can receive email: check the AWS documentation), open **Amazon SES**, **Identities**, **Create identity**, choose **Domain**, enter `mail.example.com` and keep **Easy DKIM** on. Or run `aws sesv2 create-email-identity --email-identity mail.example.com`.
4. **Add the DNS records at your provider.**
   - The three DKIM `CNAME` records SES shows you. On Cloudflare set each to **DNS only** (grey cloud).
   - One `MX` record: name `mail` (so `mail.example.com`), value `inbound-smtp.us-east-1.amazonaws.com` (use your region), priority `10`.
   Wait until SES shows the identity as **Verified**.
5. **Deploy with two extra settings** (use the same `-c` values as always, plus these):
   ```
   uv run python scripts/build_lambdas.py
   cdk deploy -c owner_email=... -c sender_email=... -c inbound_address=reports@mail.example.com -c inbound_sender=you@example.net
   uv run python scripts/migrate_db.py
   ```
   `inbound_daily_limit` (default 5) caps how many emailed reports may start a run per day. If another SES receiving rule set is already active in the region, the deploy stops with a message and changes nothing: add a rule for the report address to that rule set yourself, or deactivate it, and deploy again.
6. **Send a test email** from the sender address to the report address, with a short report naming one real role and its link. Within a minute `uv run python scripts/reprocess_email.py --list` shows it as `started`, then `done`, and the **Today** screen says "Last report … (from email)".
7. **Point your report at the address**, then switch off scheduled web search in **Settings** (delete the schedule) so only the email drives runs. **Run now** still works as a manual search.

## What it does with each email

1. Checks the message. Mail from **anyone but your sender address** is deleted at once and ignored: it is never shown and never starts anything. Mail from your sender address must also pass SES's spam and virus checks and carry a valid DKIM signature for the sender's domain; if it does not, it is kept and recorded as `rejected`, and the Today screen says so, because that means something about your setup needs attention.
2. Starts a run, unless the daily limit is reached (`skipped`) or another run or documents job holds the lock for more than about 8 minutes (`waiting`). If an email is rejected, skipped, waiting or failed, the **Today** screen says so, so a missing report is never a mystery.
3. Reads the report with one AI call and keeps the roles it recommends. Roles marked already seen, applied, rejected, skipped, excluded or closed are dropped, as are roles with no usable link (these are listed in the run's problems). At most 25 roles per report.
4. Reads, checks and scores each role like any other run, and writes documents for the ones above your cutoff. Each job keeps the report's verdict and note so you can see why it was imported.

| Status | Meaning |
|---|---|
| `received` | Arrived; recorded |
| `processing` | Being checked and started (an interrupted one is picked up again after about 15 minutes) |
| `started` | A run was started for it |
| `done` | The run finished |
| `rejected` | From your sender, but failed a check (spam, virus, no valid signature); the email is kept |
| `ignored` | From anyone else, or far too large: deleted immediately, never shown |
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

- Raw reports from your sender are kept in a private bucket for 30 days, then deleted. Mail from anyone else is deleted as soon as it is recognised.
- The report text is sent to your AI provider so it can be read.
- The report is treated as untrusted text. The model only picks out roles; it cannot change settings, send mail or run anything. Links go through the same page fetcher as every other posting.
- Only mail that passes every check can start a run: it must come from your one sender address with a valid signature. At most `inbound_daily_limit` runs start a day, and messages over 2 MB are refused without being read. Because the sender address could be known to others, keep the report address secret as described above.

## If something does not work

See the email section of [troubleshooting.md](troubleshooting.md).
