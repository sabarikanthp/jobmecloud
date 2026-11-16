r"""Move your data from the local JobMe app into your deployed JobMeCloud.

    uv run python scripts/import_local.py --from "C:\path\to\your\JobMe data folder"            (rehearsal only)
    uv run python scripts/import_local.py --from "..." --apply [--copy-api-key]                   (really do it)

Close the local app first. The local data is only read (from a copy) and is never changed. The rehearsal
imports everything into a throwaway database to check it fits, and writes nothing to AWS. Running it again
is safe: rows and files already in the cloud are skipped.

Not moved: the schedule (set it again in Settings), contacts and follow-ups exist only if you have them,
and API keys, unless you pass --copy-api-key (they go straight to AWS Parameter Store and are never printed).
"""

import argparse
import sys
import tempfile
from pathlib import Path

import boto3
import yaml

from jobmecloud.admin import importer
from jobmecloud.admin.database import migrate_deployed
from jobmecloud.admin.stack import data_bucket, stack_outputs
from jobmecloud.config import paths
from jobmecloud.db.engine import make_engine
from jobmecloud.db.migrate import migrate

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--from", dest="source", required=True, help="the local app's data folder (it contains jobme.db)")
parser.add_argument("--apply", action="store_true", help="write to AWS (without it, only a rehearsal)")
parser.add_argument("--copy-api-key", action="store_true", help="copy your AI provider key to AWS Parameter Store")
parser.add_argument("--stack-name", default="JobMeCloud")
args = parser.parse_args()

data_dir = Path(args.source)
db_file = data_dir / "jobme.db"
if not db_file.is_file():
    sys.exit(f"No jobme.db in {data_dir}. Point --from at the folder the local app keeps its data in.")
raw = yaml.safe_load((data_dir / "settings.yaml").read_text(encoding="utf-8")) if (data_dir / "settings.yaml").is_file() else {}
raw = raw or {}
apps_dir = Path(raw.get("applications_dir") or data_dir / "applications")
cloud_apps = f"{paths.DEFAULT_DATA_DIR}/applications"
settings = importer.cloud_settings(raw)

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
    snap = importer.snapshot_db(db_file, Path(tmp) / "snap")
    src = importer.open_local(snap)
    folders = importer.job_folder_names(src, apps_dir)
    files = importer.plan_files(data_dir, apps_dir, folders)
    size = sum(p.stat().st_size for p, _ in files)

    print("Rehearsal: importing into a throwaway database to check everything fits...")
    scratch = Path(tmp) / "scratch"
    scratch.mkdir()
    rehearsal = make_engine(data_dir=scratch)
    migrate(rehearsal)
    counts = importer.copy_rows(src, rehearsal, apps_dir=apps_dir, cloud_apps_dir=cloud_apps)
    rehearsal.dispose()
    for table, n in counts.items():
        print(f"  {table:20} {n:>5} rows")
    print(f"  files: {len(files)} ({size / 1_000_000:.1f} MB) from {len(folders)} job document folders, plus settings")
    print(f"  AI providers in settings: {', '.join(p.id for p in settings.providers) or 'none'}")
    if not args.apply:
        print("\nRehearsal passed. Nothing was written to AWS. Add --apply to do it for real.")
        sys.exit(0)

    print(f"\nWriting to AWS stack {args.stack_name}...")
    outputs = stack_outputs(args.stack_name)
    migrate_deployed(args.stack_name)  # make sure every table and column exists first
    dst = make_engine(f"dsql://{outputs['DatabaseEndpoint']}")
    try:
        added = importer.copy_rows(src, dst, apps_dir=apps_dir, cloud_apps_dir=cloud_apps)
    finally:
        dst.dispose()
    for table, n in added.items():
        print(f"  {table:20} {n:>5} rows added")
    bucket = data_bucket(args.stack_name)
    written = importer.upload_files(boto3.client("s3"), bucket, "workspace", files, settings)
    print(f"  files written to the data bucket: {written} of {len(files) + 1}")
    if args.copy_api_key:
        moved = importer.copy_api_keys(p.id for p in settings.providers)
        print(f"  API key copied to Parameter Store for: {', '.join(moved) or 'nothing (no key found locally)'}")
    src.dispose()
print("Done.")
