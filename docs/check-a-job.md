# Check a job

Found a job yourself? Paste it into JobMeCloud, let an AI say how well it fits you, and decide what to do, all in one place.

## How to use it

1. Open **Jobs** and press **Check a job**.
2. Paste either the job's **text** (copy the whole posting) or its **link**.
3. Pick the **AI for the fit** from the list. It starts on the AI you use for scoring, which is the cheapest sensible choice. Pick a stronger one when a job matters.
4. Press **Check fit**.

JobMeCloud reads the job and saves it straight away as a **New** job, so nothing is lost if the next step fails. Then it judges the fit and shows:

- the score out of 100 beside your cutoff,
- why it fits, what is missing, and anything worth a second look,
- any of your rules the job breaks (for example pay below your minimum).

## Then you decide

- **Mark applied** (with a date and a note). JobMeCloud sets a check-in for a week later, and the **Follow-ups** menu shows a number whenever follow-ups are overdue or due today.
- **Skip** (with a reason and a note), **Rejected**, or **Leave it for now**, which keeps the job as New.
- Once a job is applied, you can **make a resume and cover letter** for it. This never happens by itself; you press the button.

## What gets recorded

The job's details and fit score are saved on the job. Its history records that you added it with AI (naming the model), the fit check (model and cost, for example "about $0.01"), and every decision you make afterwards.

## If the job is already in your tracker

JobMeCloud recognises it (same requisition, same employer and title, or same link), shows the existing job instead of adding another, and offers **Re-check fit**. A re-check replaces the earlier score and notes; it does not pile up.

## Limits

- **Links often cannot be read.** Many job sites need a browser to show the posting. When that happens you are asked to paste the text instead, which always works.
- **LinkedIn links are never opened.** Copy the posting's text and paste that.
- Only text is read. Files and chatting about a job are not available yet.
- Very long text is cut at about 30,000 characters, and you are told when that happens.

## Cost

Two small AI calls per job, usually a cent or two in total; the model and cost are shown with the fit. See [costs.md](costs.md).

Problems? See [troubleshooting.md](troubleshooting.md#checking-a-job).

## Duplicates and repeats

- **Mark a job as a duplicate.** Choose **Duplicate…** from a job's status list (Jobs list, a job's page, or the Daily jobs page). JobMeCloud suggests the likely originals, with why each matches and what you decided about it. You can also search your tracker, or press **Ask the AI if I have seen this before** (one small call, about a cent), which compares the job's description with the closest earlier jobs. The duplicate keeps a link to the original, which shows "Also seen as" back. **Reopen** undoes it.
- **Daily runs look through your history first.** After a job is read and before it is scored, it is checked against everything in your tracker, including jobs you skipped, rejected or applied for. The same job (same link, requisition, or employer and title) is saved as a Duplicate with a link and is not scored. A possible repeat (a reworded title, a new requisition, or the same posting text under another company name) stays New with a "Looks like ..." note, a button to mark it a duplicate, and a note of what you decided before.

## A job that could not be read

If JobMeCloud could not open a job's page, the job has no fit. Open it, find **Fit**, paste the job description, and press **Re-evaluate**. The description is saved first (and its details, such as pay and location, are read to fill in blanks), then the fit is judged with the AI you pick. A failed judgment keeps your description so you can retry. **Re-evaluate** also works on any job, for a second opinion from a different AI.
