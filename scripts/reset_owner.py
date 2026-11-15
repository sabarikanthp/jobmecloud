"""Recover a lost password or authenticator app (see docs/account-recovery.md).

    uv run python scripts/reset_owner.py --email you@example.com
"""

import argparse
import sys

from jobmecloud.admin.owner import OwnerNotFound, pool_id_from_stack, reset_owner

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--email", required=True)
parser.add_argument("--pool-id", help="defaults to the UserPoolId of your deployed stack")
parser.add_argument("--stack-name", default="JobMeCloud")
args = parser.parse_args()
try:
    pool_id = args.pool_id or pool_id_from_stack(args.stack_name)
    reset_owner(args.email, pool_id)
except (LookupError, OwnerNotFound) as e:
    sys.exit(str(e))
print(f"Reset {args.email}. Check that inbox for a new temporary password; you will set up MFA again at sign-in.")
