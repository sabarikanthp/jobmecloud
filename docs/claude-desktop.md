# Use JobMe from Claude Desktop

You can connect your Claude Desktop chats to JobMe. In a chat you can then say "look at JobMe job 123", ask whether it fits you, and carry on the conversation there. Claude can also update JobMe for you: change a job's status, add notes, set up follow-ups, record interviews, and attach a resume or cover letter that you wrote in the chat.

This works with **Claude Desktop** only. Claude on the web and phone connects to outside tools in a different way that does not accept a key.

## 1. Create a key

1. Open **Settings** in JobMe and scroll to **Claude access**.
2. Give the key a name (for example "Laptop"), choose what it can do, and press **Create key**.
   - **Read only** lets a chat look at your jobs, resume, contacts and follow-ups. It cannot change anything. Start here.
   - **Read and change** also lets a chat make the changes listed below. Use it only when you need that.
3. Copy the key and the settings block shown. **The key is shown once.** If you lose it, revoke it and create another.

## 2. Add it to Claude Desktop

1. In Claude Desktop open **Settings, Developer, Edit config**. This opens `claude_desktop_config.json`.
2. Paste the `jobme` entry from JobMe into the `mcpServers` part of the file. It looks like this (JobMe fills in your address and key):

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

3. Fully quit and reopen Claude Desktop. You need [Node.js](https://nodejs.org) installed, because the connection uses the `mcp-remote` helper.

The key is kept in an environment setting instead of the argument line because a space inside an argument is mangled on Windows.

## 3. Use it

Press **Copy for Claude** on a job (or a contact, or a follow-up) and paste the text into a chat, for example:

> JobMe job 123: Acme – Staff Engineer. Does this fit me? What should I prepare for the interview?

Other things to try:

- "Show my top five jobs I haven't applied to."
- "Add a note to job 123: recruiter says the team is hiring two people."
- "Remind me to follow up on job 123 next Friday."
- "I wrote this cover letter. Attach it to job 123." (Needs a read and change key.)
- "Check this posting for me: (paste the text or a link)."

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

`attach_documents` saves a resume and/or cover letter into the job's documents folder, so the Open and Download buttons on the job page work on them. Text is saved as `.md` (resume also `.txt`). A Word (`.docx`) or `.pdf` file can be sent too, up to about 3 MB. Earlier files are moved to the folder's `previous` archive, never overwritten. JobMe does not convert attached text into Word; if you need Word, ask Claude to produce the `.docx`.

## What Claude cannot do

- Delete anything (jobs, contacts, interviews). Do that in JobMe.
- See or change your settings, your AI and search keys, or these Claude keys.
- Generate documents with JobMe's own Make docs. That stays in the app.

## Limits

- 60 requests a minute per key.
- 30 uses a day of the two tools that spend your AI money (`check_job`, `re_evaluate_job`) per key.

## Safety

- Job postings and notes are text from outside. JobMe marks them as untrusted when it hands them to Claude, but a read and change key means a hostile posting could try to steer a chat into editing your tracker. Prefer a **read-only** key, and keep read and change keys for chats where you are watching.
- **If a key leaks, revoke it:** Settings, Claude access, **Revoke**. It stops working straight away. Then create a new one.
- Keys can be given an expiry when you create them.
- Sources for the Claude Desktop settings: the [mcp-remote](https://github.com/geelen/mcp-remote) README (header and environment-variable pattern, and the Windows space problem).
