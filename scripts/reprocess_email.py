r"""Look at, or run again, the emailed reports JobMeCloud has received.

    uv run python scripts/reprocess_email.py --list
    uv run python scripts/reprocess_email.py --key inbound/<message id>            (a waiting or failed email)
    uv run python scripts/reprocess_email.py --key inbound/<message id> --force    (any email, even a finished one)

Needs the same AWS sign-in you deployed with.
"""

import argparse
import sys
from datetime import datetime, timezone

import boto3

from jobmecloud.admin.stack import ingest_settings, stack_outputs
from jobmecloud.db.engine import make_engine
from jobmecloud.inbound import store
from jobmecloud.inbound.replay import ReplayRefused, reprocess_email
from jobmecloud.inbound.trust import TrustConfig
from jobmecloud.jobs.dispatch import LambdaDispatcher

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--list", action="store_true", help="show the most recent emails and what became of them")
parser.add_argument("--key", help="the email's key in the mail bucket (shown by --list)")
parser.add_argument("--force", action="store_true", help="run it again even if it already finished")
parser.add_argument("--stack-name", default="JobMeCloud")
args = parser.parse_args()
if not args.list and not args.key:
    parser.error("give --list or --key")

try:
    outputs = stack_outputs(args.stack_name)
    settings = ingest_settings(args.stack_name)
    bucket = outputs["MailBucketName"]
except (LookupError, KeyError) as e:
    sys.exit(str(e))

engine = make_engine(f"dsql://{outputs['DatabaseEndpoint']}")
try:
    if args.list:
        for row in store.recent(engine):
            print(f"{row.received_at:%Y-%m-%d %H:%M}  {row.status:9}  {row.s3_key}  {row.note or ''}")
    else:
        dispatcher = LambdaDispatcher(run_function=settings["run_function"])
        config = TrustConfig(address=settings["address"], sender=settings["sender"])
        try:
            status = reprocess_email(engine, boto3.client("s3"), dispatcher, bucket=bucket, key=args.key, config=config,
                                     daily_limit=settings["daily_limit"], now=datetime.now(timezone.utc), force=args.force)
        except ReplayRefused as e:
            sys.exit(str(e))
        print(f"Result: {status}")
finally:
    engine.dispose()
