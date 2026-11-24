# Your resumes, and which one documents start from

You can keep several resumes in JobMe, for example one for leadership roles and one for hands-on technical roles. When JobMe writes a tailored resume and cover letter for a job, it starts from one of them. This page explains how that choice is made.

## Add and manage resumes

In **Settings**, open the resume section. You can:

- **Upload** a resume (`.docx`, `.pdf`, `.txt` or `.md`). JobMe reads it and shows what it read so you can correct it before saving. A `.docx` also keeps its layout: the tailored resume is written into your own file.
- **Make default**: the default is the resume JobMe uses unless you say otherwise. The first resume you add becomes the default.
- **Check mapping**, **Edit what JobMe read** and **Remove** (the default cannot be removed until another one is the default).

You can also upload a different resume from a job's page, under **Make docs** or **Regenerate**, with **Upload a different resume**.

## Which resume does a job start from?

| How the documents are made | Resume used |
|---|---|
| You press **Make docs** or **Regenerate** and pick a resume in **Start from** | That resume, exactly |
| You pick **Best match (automatic)**, or the documents are made automatically after a run | The closest resume if every resume has a profile (below), otherwise your default |
| You use **Use my resume as-is** | That resume's file is copied unchanged and nothing is rewritten |

### Automatic matching and profiles

For automatic matching JobMe needs a short **profile** of each resume (the roles it targets, seniority, industries, skills). Press **Build context** in the resume section to write them. It costs a cent or two per resume, and only resumes that are new or changed are done again.

When JobMe makes documents automatically it then asks the AI which profile is closest to the job and starts from that resume. The note on the job says which one it used, for example "Started from Platform (best match: platform migration work)".

Two rules keep this predictable:

- **Your default is used when it has no profile.** If you upload a new resume and make it the default, it has no profile until you press **Build context**. Until then JobMe uses it directly, rather than choosing among your older resumes.
- **Once every resume has a profile, the closest match wins.** That can be a resume other than the default. If you want a particular resume every time, choose it in **Start from**, or remove the resumes you do not want used.

Documents already made keep the resume they were made from. Use **Regenerate** to make them again.

## Troubleshooting

**Documents use an older resume than my default.** Check the note on the job: if it says "Started from ... (best match ...)", every resume has a profile and the closest one was chosen. Pick your default in **Start from**, or choose it when you regenerate. (Before the fix in November 2026, a new default without a profile was skipped by the automatic choice; update to the latest version, see [operations.md](operations.md).)

**"Build context" says a resume needs a profile but nothing happens.** It needs an AI connection for the reading step; set one up in Settings first. A resume with no jobs in it (a cover letter, say) has nothing to profile and is ignored.
