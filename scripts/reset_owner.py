"""Recover a lost password or authenticator app (see docs/account-recovery.md).

    uv run python scripts/reset_owner.py --email you@example.com --pool-id <UserPoolId>
"""

import argparse
import sys

from jobmecloud.admin.owner import OwnerNotFound, reset_owner

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--email", required=True)
parser.add_argument("--pool-id", required=True)
args = parser.parse_args()
try:
    reset_owner(args.email, args.pool_id)
except OwnerNotFound as e:
    sys.exit(str(e))
print(f"Reset {args.email}. Check that inbox for a new temporary password; you will set up MFA again at sign-in.")
