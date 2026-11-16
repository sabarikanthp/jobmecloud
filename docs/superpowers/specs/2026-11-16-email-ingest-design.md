# Email ingest: let a daily emailed job report drive a JobMeCloud run

Date: 2026-11-16. Status: draft for the owner's approval. Size: a project.

## Intent and why

The owner already runs a daily job search as a scheduled task in a consumer chat assistant, covered by a flat subscription. It produces a long, careful report (strong matches, stretch roles, exclusions, follow-ups) with direct links, and it can send that report by email to any address.

JobMeCloud's own search agent does the same job by calling the AI provider's web search through an API key. That is billed per token and is expensive for this task: one scheduled run cost about $2.06 and found two postings it could not even read before its spending cap stopped it. The search is where the money goes; reading, checking, scoring and writing documents are cheap by comparison.

So: let the chat assistant do the searching, and let JobMeCloud do everything it is good at after that. When the daily report arrives, JobMeCloud takes the roles the report recommends, does its own research on each (reads the posting, checks it is still open, scores it against the owner's profile), and writes a tailored resume and cover letter for the ones above the owner's cutoff. No part of this needs a person.

Success looks like: the owner's chat assistant sends its daily email; with no further action, the matches appear in JobMeCloud, scored, with documents ready for the good ones, at a cost of cents per day.

## Goals

- A report emailed to a dedicated address starts a JobMeCloud run automatically.
- Only the roles the report recommends are imported. Roles it marks previously surfaced, already applied, rejected, excluded or closed are not.
- JobMeCloud researches and scores each imported role itself; its score, not the assistant's verdict, decides what happens next. The assistant's verdict and notes are kept on the job.
- Everything after the candidate list is unchanged: the same duplicate checks, hard rules, scoring, cutoff and document writing, under one run lock and one spending cap.
- Costs stay at cents per run. No fixed monthly cost is added.
- It is an optional, documented part of the open-source project. The owner's domain and addresses are deploy-time settings and appear nowhere in the repository.

## Non-goals

- Replacing the chat assistant, or reading its results through a login or an API.
- Reading a person's mailbox (Gmail API, IMAP). Only mail sent to one dedicated address enters the system.
- Parsing attachments, or reports in other languages or shapes than an emailed text/HTML report.
- Sending email (digests and reminders are a separate, later feature).
- Multiple users, multiple sender addresses, or a screen for editing the allowed sender.
- Changing the web-search agent. The owner will switch scheduled web search off once this works; fixing that agent's cost is a separate task.
- Automating DNS or the chat assistant's setup. Those are documented manual steps.

## Anti-goals (a failure even if it technically works)

- Importing roles the report said to skip, or importing the same role twice.
- Silently losing an email. Every received email ends in a recorded outcome the owner can see, and a failed one can be replayed.
- Letting a stranger cause AI spend by emailing the address.
- A run that exceeds the per-run spending cap, or two runs at once.
- Any personal address, domain or sender name committed to the repository.

## Constraints

- Serverless, no VPC, no fixed monthly fee. The stack still deploys, unchanged, when this feature is not configured.
- Amazon SES email receiving is available in `us-east-1`. Only one receipt rule set can be active per region and account. CloudFormation cannot activate a rule set.
- The domain's DNS (a mail-exchange record and the SES verification records) is managed by the owner outside AWS.
- Receiving is not restricted by the SES sandbox (to be confirmed on a real message).
- The email text is untrusted input. It is produced by a model that read the open web.
- A run holds the single run lock, so an email arriving during another run or a documents job must be handled.

## Approaches considered

**How mail reaches JobMeCloud.** Chosen earlier: a dedicated address on a subdomain, received by SES. Rejected: reading a mailbox from a Lambda with the Gmail API (a Google Cloud project and OAuth token that expires for personal accounts, and read access to the whole mailbox) or IMAP with an app password (also whole-mailbox access, plus polling). The sample email showed the assistant can send directly to any address, so forwarding is not needed either.

**Where the work happens after the email arrives (the owner chose A).**

- **A. Reuse the existing run (chosen).** A small ingest Lambda validates the email, records it, takes the run lock, creates a Run and starts the existing run worker, which takes its candidates from the email instead of from the search agent. One lock, one cost cap, one progress record; the Today screen shows it like any run.
- B. The ingest Lambda does everything. Rejected: duplicates the read and score pipeline, with its own time limit; the two would drift.
- C. The ingest Lambda saves unread jobs and a later scheduled run picks them up. Rejected: not event-driven, and it depends on the schedule being switched off.

**Calls made by the designer (the owner may change any):**

- SES saves the raw email to a private mail bucket; an S3 notification starts the ingest Lambda. The raw copy exists before anything runs, so a failure can be replayed.
- The mail bucket is separate from the data bucket, with emails deleted after 30 days.
- The email is read by an AI call inside the run worker, not in the ingest Lambda, so its tokens and cost are counted by the run's existing cost tracker and cap.
- Email runs skip the "check older jobs" step, to keep their cost predictable.
- At most 5 email runs per day (a setting), so a flood of mail cannot run up the AI bill.

## The design

### Parts

1. **SES receiving (CDK, optional).** Enabled by two deploy settings: `inbound_address` (for example `dailyjobs@jobmecloud.example.com`) and `inbound_sender` (the one address allowed to send reports). A receipt rule for exactly that recipient has spam and virus scanning on and an S3 action writing to the mail bucket. A custom resource activates the rule set. If another rule set is already active in the region, the deploy fails with a clear message instead of replacing it.
2. **Mail bucket (CDK).** Private, encrypted, HTTPS only, versioning off, 30-day expiry, a policy letting only SES write to it.
3. **Ingest Lambda (CDK + `handlers/ingest.py`).** Small (256 MB, 3 minutes, so it can wait for the run lock). Reads the new email object and decides what to do. Role: read the mail bucket, read and write the database, invoke the run worker. No secret access.
4. **New table `InboundEmail`** (`id`, `s3_key` unique, `received_at`, `sender`, `status`, `run_id`, `note`). Statuses: `received`, `started`, `rejected` (failed the trust checks), `skipped` (over the daily limit), `waiting` (lock busy beyond the wait), `done`, `failed`. It makes ingestion idempotent and gives the owner a visible record.
5. **Run worker change.** The event may carry `email_key`. When it does, the worker's candidate stage reads and parses the email and asks the extract-step model for the recommended roles, then continues with the unchanged read, check, score and document stages. The set-up check for an email run does not require the search step or a search service (there is no search), only the extract, liveness, score and tailor steps and a profile with target roles. The lock is taken before that check, so a failed check must finish the Run and release the lock, which the run's existing clean-up already does.
6. **Frontend (small).** A run started by email is labelled as such on Today. Email-sourced jobs get the new origin `email` (existing values are `scout` and `manual`; the older-jobs recheck applies only to `scout`) and carry the assistant's verdict and note in the job's notes. (The Jobs list's Source filter lists the posting's website host, not the origin, so it needs no change.)

### Flow

```
chat assistant -> email to the dedicated address -> SES receipt rule -> raw email in the mail bucket
  -> bucket notification -> ingest Lambda:
       skip if this object was already handled (InboundEmail.s3_key)
       trust checks (below); record rejected or skipped emails and stop
       take the run lock (wait up to ~90 seconds if busy, else mark `waiting`)
       create Run(trigger="email"), record InboundEmail(status=started)
       invoke the run worker {"task":"run","run_id":N,"email_key":...}
  -> run worker:
       parse the email (text, else HTML to text; collect links)
       one structured AI call (extract-step model): the roles recommended, each with
         employer, title, direct URL, requisition id if given, the assistant's verdict and note
       cap at 25 candidates; keep only http(s) URLs
       for each candidate: the existing read -> dedupe -> liveness -> hard rules -> score
         -> outcome "matched" if at or above the cutoff
       existing document step for matched jobs (the per-run application cap applies)
       finish the Run; set InboundEmail.status to done or failed
```

### What counts as "recommended"

The extraction call returns every role with its verdict as the report states it, and code keeps those marked consider, apply or strong, including stretch roles and unverified leads. Roles marked previously surfaced as not new, applied, rejected, skipped, excluded or closed are dropped, as are roles without a direct link (counted and listed in the run's errors so nothing vanishes). The existing duplicate checks then drop what JobMeCloud already knows by link or requisition. If the report is missing, empty or unparseable, the run finishes with a clear error and the email stays in the bucket.

### Trust checks (all must pass, in the ingest Lambda)

- The recipient is the configured address.
- The sender matches `inbound_sender`.
- SES's spam and virus verdicts are PASS, and the authentication result shows the sender's DKIM signature passed for the sender's own domain.
- The message is under a size limit (1 MB of text).
- Fewer than the daily limit of email runs have started today ("today" in the time zone the stack was deployed with).

A failed check records the email as `rejected` or `skipped` and starts no run. The exact header names SES writes are to be confirmed against a real message during the build.

### Safety of the untrusted text

The extraction call has no tools and returns only a fixed structure; everything else is code. Links go through the existing page fetcher and its blocked-host checks. The candidate count is capped. The email can only add candidate links for JobMeCloud to read and score; it cannot change settings, send mail or run commands.

### Cost

A daily report is a few thousand tokens for the extraction call, then one small call per candidate to read and one to score, using the cheaper models already configured. Expect cents per run. SES receiving is a small per-message charge; S3 and the Lambda are negligible.

### Setup and rollout (documented in the deploy guide)

1. Create the SES domain identity and add the DNS records (a mail-exchange record on the subdomain and the verification records).
2. Deploy with `-c inbound_address=... -c inbound_sender=...`.
3. Send a test email from the sender account to the address; check the Today screen and the run's record.
4. Point the chat assistant's scheduled task at the address.
5. Switch off the scheduled web search in Settings.

## Testing

- Unit: email parsing (plain text and HTML, links, size limit), sanitised sample emails as fixtures (no real names or addresses), extraction with the existing fake provider including a verdict mix of recommended, already-applied and no-link items, candidate cap.
- Ingest handler with fake AWS: each trust check, idempotency (same object twice), the daily limit, the lock busy case.
- Run worker: an email-sourced run uses the same stages and cost cap, skips the older-jobs check, and records a clear error for an unparseable email.
- Infra: the feature absent changes nothing; present adds the rule, bucket, Lambda and permissions with least privilege.
- Database: a real-cluster test for the new table, as for the others.
- Manual end to end: a real email from the sender account.

## Left to the builder

Exact SES header names and the MIME parsing details (standard library is expected to suffice); the extraction prompt and its output schema; how the custom resource activates the rule set and detects an already-active one; the lock-wait loop; UI wording; a small script to replay a stored email; documentation pages.
