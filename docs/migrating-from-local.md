# Moving over from the local JobMe app

If you already use the local JobMe app, `scripts/import_local.py` copies your jobs, history, watchlist, profile and settings into your deployed JobMeCloud. Your local data is only read (from a copy) and never changed.

## 1. Find your local data folder

It is the folder that holds `jobme.db`. By default that is `JobMe` in your home folder, but the app lets you move it (for example into Dropbox). If the default folder looks empty, check the saved location: on Windows it is the `data_dir` value in `%LOCALAPPDATA%\JobMe\JobMe\location.json`.

## 2. Prepare

- Close the local app, so the database is not being written to.
- Turn off its scheduled searches, or both apps will search.
- Sign in to AWS the way you did for deploying (`aws sso login --profile <name>`, then set `AWS_PROFILE` and `AWS_REGION`).

## 3. Rehearse, then import

```
uv run python scripts/import_local.py --from "<your local data folder>"
```

This imports everything into a throwaway database to check it fits, prints what it found, and writes nothing to AWS. When you are happy:

```
uv run --with keyring python scripts/import_local.py --from "<your local data folder>" --apply --copy-api-key
```

`--copy-api-key` moves your AI provider key from your computer's credential store into AWS Parameter Store. It is never printed. Leave the flag off and paste the key in the app's Settings instead if you prefer.

## What moves, and what does not

| Moves | Does not move |
|---|---|
| Jobs, activity history, custom fields, watchlist, runs | The schedule. Set it again in Settings, which creates the cloud schedule |
| Profile, resumes, run logs, generated document folders that jobs point at | Document folders no job points at |
| Settings (AI connection, models, limits) with the local documents folder removed | Stale run locks |

Rows keep their original ids, so links between jobs, runs and history still hold.

## Safe to repeat

Running it again adds nothing that is already there. Settings in the cloud are replaced each time; the data bucket is versioned, so an older copy can be restored from the S3 console.
