# Use JobMe from Claude Desktop

Connect your Claude Desktop chats to JobMe. In a chat you can say "look at JobMe job 123", ask whether it fits you, and carry on the conversation there. Claude can also update JobMe for you: change a job's status, add notes, set up follow-ups, record interviews, and attach a resume or cover letter that you wrote in the chat.

This works with **Claude Desktop** only. Claude on the web and phone connects to outside tools in a different way (sign-in with OAuth) that does not accept a key.

## Before you start

You need:

- **JobMeCloud deployed in your AWS account** ([deploy.md](deploy.md)), with this feature. If you deployed earlier, update first (next section).
- **Claude Desktop** installed and signed in.
- **Node.js** installed ([nodejs.org](https://nodejs.org), the LTS version). Claude Desktop uses it to run the small `mcp-remote` helper that adds your key to each request. Check with `node -v` in a terminal.

### If you deployed before this feature existed

The feature needs a new API route, a new database table and a new website, so run the normal update from [operations.md](operations.md), with the same `-c` values you deployed with:

```
git pull
uv sync
uv run python scripts/build_lambdas.py
cdk deploy -c owner_email=you@example.com -c sender_email=you@example.com
uv run python scripts/migrate_db.py
(cd frontend && npm install && npm run build)
uv run python scripts/publish_site.py
```

`cdk deploy` will list a new API Gateway route, `POST /api/mcp`, that has no sign-in check. That is intended: the app checks your key on that route instead. See [security.md](security.md).

## 1. Create a key

1. Sign in to JobMe and open **Settings**. Scroll to **Claude access**.
2. Give the key a name (for example "Laptop"), choose what it can do, and optionally choose an expiry.
   - **Read only** lets a chat look at your jobs, resume, contacts and follow-ups. It cannot change anything. **Start here.**
   - **Read and change** also lets a chat make the changes listed below.
3. Press **Create key**. Copy the key (it starts with `jmc_`). **It is shown once.** If you lose it, revoke it and make another.

Use one key per computer or purpose, so you can revoke one without breaking the others.

## 2. Connect Claude Desktop

1. In Claude Desktop open **Settings, Developer, Edit config**. This opens `claude_desktop_config.json`.
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`
2. The page shows a ready-made settings block after you create the key (**Copy Claude Desktop settings**). Paste its `jobme` entry into the `mcpServers` part of the file. If the file is empty, paste the whole block. It looks like this (JobMe fills in your address and key):

   ```json
   {
     "mcpServers": {
       "jobme": {
         "command": "npx",
         "args": ["-y", "mcp-remote", "https://your-site/api/mcp", "--header", "Authorization:${AUTH_HEADER}"],
         "env": { "AUTH_HEADER": "Bearer jmc_your-key" }
       }
     }
   }
   ```

   `your-site` is the address you open JobMe at (the `SiteUrl` from your deploy). Keep the key in the `env` line, not in `args`: a space inside an argument is mangled on Windows.
3. **Fully quit and reopen Claude Desktop** (close it from the system tray or menu bar, not just the window).

## 3. Check it works

Start a new chat and ask:

> What JobMe tools do you have? Then show my five newest jobs.

Claude should list JobMe tools (`list_jobs`, `get_job`, and so on) and answer with your jobs. In **Settings, Claude access** the key's **Last used** changes from "Never used" to today. If it does not work, see Troubleshooting below.

## 4. Use it

Press **Copy for Claude** on a job (or a contact, or a follow-up) and paste the text into a chat, for example:

> JobMe job 123: Acme – Staff Engineer. Does this fit me? What should I prepare for the interview?

Claude reads the job, your fit score and gaps, your notes, contacts, follow-ups and your resume, then you carry on the conversation in the chat. More to try:

- "Show my top five jobs I haven't applied to."
- "Add a note to job 123: recruiter says the team is hiring two people."
- "Remind me to follow up on job 123 next Friday."
- "Move job 123 to Applied."
- "Add Jane Doe, a recruiter at Acme, as a contact on job 123."
- "I had a phone screen for job 123 yesterday. Record it."
- "I wrote this cover letter. Attach it to job 123." (Needs a read and change key.)
- "Check this posting for me: (paste the text or a link)." (Uses your AI connection and costs a little.)

### What Claude can do

| Needs only a read key | Needs a read and change key |
|---|---|
| `list_jobs`, `get_job`, `get_job_documents` | `set_job_status`, `update_job`, `append_job_note`, `add_job` |
| `get_resume_context`, `get_dashboard` | `check_job`, `re_evaluate_job` (use your AI connection) |
| `list_followups`, `list_contacts` | `create_followup`, `complete_followup`, `snooze_followup`, `reschedule_followup`, `cancel_followup` |
| | `create_contact`, `update_contact`, `add_interview`, `update_interview` |
| | `attach_documents` (a resume and/or cover letter) |

Changes made this way appear in the job's history as "by Claude: *key name*".

### Attached documents

`attach_documents` saves a resume and/or cover letter into the job's documents folder, so the **Open** and **Download** buttons on the job page work on them.

- Text is saved as `.md` (a resume can also be `.txt`). A Word (`.docx`) or `.pdf` file can be sent too, up to about 3 MB.
- Earlier files are moved to the folder's `previous` archive, never overwritten. Attaching only a cover letter leaves the resume where it is.
- JobMe does not convert attached text into Word. If you need Word, ask Claude to produce the `.docx`.
- `get_job_documents` brings the attached documents back into a chat so you can keep editing them.

## What Claude cannot do

- Delete anything (jobs, contacts, interviews). Do that in JobMe.
- See or change your settings, your AI and search keys, or these Claude keys.
- Generate documents with JobMe's own **Make docs**. That stays in the app.

## Limits

- 60 requests a minute per key.
- 30 uses a day, per key, of the two tools that spend your AI money (`check_job`, `re_evaluate_job`).

## Safety

- Job postings and notes are text from outside. JobMe marks them as untrusted when it hands them to Claude, but a read and change key means a hostile posting could try to steer a chat into editing your tracker. Prefer a **read-only** key, and keep read and change keys for chats where you are watching what happens.
- Treat a key like a password. Do not paste it into chats, screenshots, issues or commits. It lives in your Claude Desktop config file.
- **If a key leaks, revoke it:** Settings, Claude access, **Revoke**. It stops working straight away. Then create a new one.
- Give keys an expiry when you can.

## Troubleshooting

**Claude does not show any JobMe tools.** Fully quit and reopen Claude Desktop after editing the config. Check the file is valid JSON (a missing comma is the usual cause) and that `jobme` sits inside `mcpServers`. Check `node -v` works in a terminal. In Claude Desktop, **Settings, Developer** shows the server and its log.

**The server shows an error or "failed" in Developer settings.** Open its log from there. Common causes: Node.js is not installed or not on the PATH; the address is wrong (it must end in `/api/mcp`); or the key was revoked or has expired (create a new one).

**"This key is read-only."** The chat tried to change something with a read-only key. Create a read and change key, replace the key in the config, and restart Claude Desktop.

**"The daily limit for AI-cost tools on this key has been reached."** `check_job` and `re_evaluate_job` are limited to 30 a day per key. Try again tomorrow, or paste the posting into JobMe itself.

**"No job with that id".** The job was deleted, or the number is wrong. Use **Copy for Claude** on the job page.

**Everything fails with a 401 or "unauthorized".** The key is wrong, revoked or expired, or the config has a stray space or line break in the key. Create a fresh key and paste it again.

**The Windows `npx` command is not found.** Install Node.js from nodejs.org (the LTS installer adds it to the PATH), then restart Claude Desktop.

## Remove access

Revoke each key in **Settings, Claude access**, and delete the `jobme` entry from `claude_desktop_config.json`.  With no active keys, the route accepts nothing.

## Sources

The Claude Desktop settings follow the [mcp-remote](https://github.com/geelen/mcp-remote) README: the `--header` option, the environment-variable pattern, and the note about spaces in arguments on Windows.
