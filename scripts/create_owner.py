"""Create the account you sign in with.

    uv run python scripts/create_owner.py --email you@example.com --pool-id <UserPoolId from the deploy output>
"""

import argparse

from jobmecloud.admin.owner import create_owner

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--email", required=True)
parser.add_argument("--pool-id", required=True)
args = parser.parse_args()
create_owner(args.email, args.pool_id)
print(f"Created {args.email}. Check that inbox for a temporary password, then open the site and sign in.")
