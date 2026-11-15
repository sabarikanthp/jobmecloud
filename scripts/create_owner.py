"""Create the account you sign in with.

    uv run python scripts/create_owner.py --email you@example.com
"""

import argparse
import sys

from jobmecloud.admin.owner import create_owner, pool_id_from_stack

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--email", required=True)
parser.add_argument("--pool-id", help="defaults to the UserPoolId of your deployed stack")
parser.add_argument("--stack-name", default="JobMeCloud")
args = parser.parse_args()
try:
    pool_id = args.pool_id or pool_id_from_stack(args.stack_name)
except LookupError as e:
    sys.exit(str(e))
create_owner(args.email, pool_id)
print(f"Created {args.email}. Check that inbox for a temporary password, then open the site and sign in.")
