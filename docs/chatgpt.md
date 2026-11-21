# Use JobMe from ChatGPT (and Claude on the web or phone)

Connect ChatGPT, or Claude on the web or phone, to JobMe so a chat can review, update and create jobs, statuses and follow-ups, with the same tools as [Claude Desktop](claude-desktop.md). You sign in with your normal JobMe login and choose what the connection may do. There is no key to copy.

## Before you start

- JobMeCloud deployed with **your own address** (`site_domain` and `certificate_arn`, see [deploy.md](deploy.md)). The sign-in is anchored to that address; without it the connector cannot work.
- Updated to a version with this feature: run the full update in [operations.md](operations.md), including `migrate_db.py`.
- Check it is live: opening `https://<your site>/.well-known/oauth-authorization-server` in a browser shows a short block of settings, not an error.

## Connect ChatGPT

1. In ChatGPT open **Plugins**, then **+**, then **Add custom MCP server**.
2. Name it `JobMeCloud` and enter `https://<your site>/api/mcp`.
3. Choose OAuth for authentication (leave the client id and secret empty: the app registers itself), then create it.
4. ChatGPT opens your JobMe site. Sign in with your password and two-step code if asked.
5. JobMe shows who is asking, and where you will be sent back to. Choose **Read only** (start here) or **Read and change**, then **Approve**.
6. Ask: "What JobMe tools do you have? Show my five newest jobs."

Claude on the web and phone works the same way: add a custom connector with the same address.

## What you can do

The same tools as Claude Desktop: look at jobs, fit scores, notes, contacts, resume and follow-ups; with **Read and change** also change statuses, add notes, create and complete follow-ups, record interviews, add jobs, check a posting, and attach documents. See the table in [claude-desktop.md](claude-desktop.md). It cannot delete anything or see your settings and keys.

## See and end a connection

**Settings, Claude access** lists each connection with "Connected via sign-in" and the app's name. **Revoke** ends it straight away. A connection lasts up to 30 days from its last use, then ChatGPT asks you to approve again.

## Safety

- Job postings are text from outside. Prefer **Read only**, and use **Read and change** only in chats where you watch what happens.
- Only approve a request you just started yourself. The page tells you which app is asking and where it returns to.
- If something looks wrong, revoke the connection in Settings.

## Troubleshooting

**The connector cannot be created / "does not support OAuth".** Check the address ends in `/api/mcp` and that `https://<your site>/.well-known/oauth-authorization-server` loads. If it says to set `site_domain`, deploy with your own address.

**"This link is not valid" on the approval page.** Go back to ChatGPT and start connecting again. A request expires after a few minutes.

**It worked, then stopped.** The connection may have been revoked or reached 30 days: reconnect.
