# Check a job's fit with AI, and a Follow-ups count in the menu

Date: 2026-11-16. Status: draft for the owner's approval. Size: a project of two independent parts, delivered as two pull requests (the count first, since it is small).

## Intent and why

Today, when the owner finds a job on their own, they paste its text or link into a chat assistant and ask for a fit judgment, then decide by hand and record the result by hand. They want to do this inside JobMeCloud: paste a job (or a link), get the AI's fit, decide (skip with a reason, apply, or leave it), optionally add a note, and, if they apply, optionally create the tailored documents. Every step should be recorded in the tracker automatically, so nothing has to be copied back.

They also want a number next to **Follow-ups** in the menu, so that follow-ups that need attention are visible without opening the page. (The follow-up itself already exists: marking a job applied creates a check-in follow-up due after `followup_default_days`, 7 by default.)

They considered using their chat subscription instead of API credits. That cannot be embedded (the chat sites forbid iframes and offer no API for subscription use), so this feature uses the configured AI provider, at a cost of cents per check, with a choice of model per check.

## Goals

- **Check a job** on the Jobs page: paste text or a link, pick the AI for the judgment, get the fit.
- The fit shows the score against the owner's cutoff, why it fits, the gaps, warnings, and any hard rules the job fails (pay floor, deal-breakers).
- The job is **saved as soon as it has been read**, and the fit is saved on it, so a check is never lost and is visible in the tracker even if the owner does nothing further.
- The owner decides with the existing status controls (apply with a date and note; skip with a reason and note; reject; leave it for now).
- After applying, an option to **create documents** using the existing documents flow.
- A job already in the tracker is recognised: the owner is shown the existing job instead of getting a duplicate, and may re-check its fit.
- A number next to **Follow-ups** counting what is overdue or due today.

## Non-goals

- Chatting with an AI about a job (deferred by the owner).
- Reading files or screenshots of a posting.
- Choosing a model the owner has not already configured in Settings (no provider model browser).
- Checking many jobs at once, or any automatic checking.
- Email or push reminders for follow-ups (the email digest feature is separate and not built).
- Embedding or driving a chat website, or using a chat subscription login.

## Anti-goals (failure even if it works)

- Creating a duplicate of a job the tracker already holds.
- Losing a check: the job and its fit must be recorded even if the owner closes the page or the AI step fails.
- Spending more than the owner expects: a check is two small AI calls, never a loop, and never starts documents by itself.
- Applying, skipping or creating documents without the owner's explicit choice.
- Fetching a page the app is not allowed to fetch (LinkedIn, non-public addresses).

## Constraints

- The API function has a 30-second limit; fetching a page can take up to 20 seconds (`TIMEOUT = 20`), so reading and judging must be separate calls.
- Pasted and fetched text is untrusted: it goes only to the existing extraction and scoring calls, which have no tools and fixed output schemas (every object schema must forbid extra properties, as `tests/test_schemas.py` enforces).
- No database schema change: the job's existing `match_score`, `reasons`, `gaps`, `flags`, `hard_rules`, `liveness`, `notes`, `description` and the activity log carry everything.
- Cost stays visible: each check writes its model and approximate cost to the job's activity log.
- Open source: no personal data, and the docs and tests use made-up examples.

## Approaches considered

**How a check runs.**
- **Two calls (chosen).** `check` reads the job (fetch if a link, extract, duplicate check, save the job as New) and returns quickly; `fit` judges it and saves the fit. Each call is well inside 30 seconds, the job is recorded before any judging, and a failed judgment leaves a saved job with a Retry.
- One call doing everything: simplest for the browser, but fetch plus extract plus score can exceed 30 seconds, and a failure would lose the job.
- A background worker with polling (like documents): robust, but adds a worker path and polling for work that fits in two short calls.

**What "choose the AI per check" offers.**
- **The models already configured in Settings (chosen).** The dropdown lists the distinct provider and model pairs across the five steps, labelled by role (Scoring model by default, Writing model as the stronger choice, and so on).
- A free-text model name or a list fetched from the provider: more freedom, but needs a model-listing feature that does not exist and invites typos.

**The count in the menu.**
- **A small counts endpoint refetched on events (chosen).**
- Counting from the full follow-up list on every page: heavier and duplicated.
- Polling only: simple but laggy after the owner changes something.

## The design

### Part 1: Follow-ups count

- **Backend:** `GET /api/followups/counts` returns `{"overdue": n, "due_today": n}` for open follow-ups, using the same bucket rules as the Follow-ups page (`fu_rules.bucket`), the app's own "today".
- **Menu:** a small number pill next to **Follow-ups** showing `overdue + due_today`, shown only when above zero, in the warning colour when anything is overdue. Its accessible label says what it is ("Follow-ups, 3 due").
- **Freshness:** fetched on load, on each page change, when the window regains focus, every five minutes, and right after any successful change request (a status change, a follow-up done or snoozed), through one shared "something changed" signal that the menu debounces.

### Part 2: Check a job

**Flow.**
1. Jobs page, button **Check a job** beside Add a job and Import, opens a panel: one box ("Paste the job, or a link to it"), a dropdown **AI for the fit**, and **Check fit**.
2. A box holding a single web address is a link; anything else is the posting text.
3. `POST /api/jobs/check` reads the job. For a link: refuse LinkedIn and non-public addresses with a plain message ("paste the text instead"); fetch with a 10-second limit; if the page yields too little text, say so and ask for pasted text. For text: cap at 30,000 characters. Extract the posting with the **Extract** step's model. If no employer or title is found, say so. Check for a duplicate by the same rules as Add a job (requisition, employer and title, address); if one exists, return it and create nothing. Otherwise create the job (origin `manual`, status New, address, description, hard-rule results and flags from the existing code rules) and log "added", noting it was checked with AI.
4. `POST /api/jobs/{id}/fit` with the chosen model judges the job with the existing scoring call, the owner's profile and resume, and saves score, reasons, gaps, warnings and deal-breakers on the job. It logs "fit checked" with the model and approximate cost. Calling it again re-checks and overwrites.
5. The panel shows the fit: the score beside the cutoff, why it fits, the gaps, warnings, and hard rules failed. Failures are shown but do not block the owner.
6. The owner decides with the existing status controls (apply with date and note, skip with a reason and note, reject, withdrew) or **Leave it for now**. Marking applied creates the follow-up as it does today and says when it is due.
7. After Applied, **Create documents** uses the existing documents controls (and says to add a resume in Settings if there is none). Documents are never started automatically.

**Errors.** Provider not configured, AI call failed, page unreadable and empty extraction each give a plain-language message. A failed fit leaves the saved job with a **Retry fit** button.

**Cost.** Two small calls: the extraction model reads, the chosen model judges. The activity log line records the model and approximate cost.

### Testing

- Backend, with the fake provider and a fake page fetcher: text and link paths, LinkedIn and non-public refusal, unreadable page, missing employer or title, duplicate by requisition, by title and by address (nothing created), the saved job and fit fields, the activity-log lines (model and cost), re-check overwriting, provider not configured, hard-rule failures reported, counts endpoint across overdue, due today, upcoming, done and cancelled follow-ups.
- Frontend, with mocked API calls: the panel's steps and messages, the dropdown contents and default, duplicate display, retry, the badge (hidden at zero, warning when overdue, refreshing after a change).
- One live check against the real provider before calling it done (provider and schema rules are what fakes cannot prove).

### Documentation

A short guide ("Check a job"), the README feature list, the cost doc (a check costs cents) and the architecture guide.

## Left to the builder

Endpoint and component names beyond those above; exact wording and layout; how the fake fetcher is injected in tests (the app already holds a `RunDeps` with `fetch`); the debounce details; whether the dropdown shows each model's provider; retry behaviour details.
