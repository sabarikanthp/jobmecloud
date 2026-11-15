"""Create or update the database tables in your deployed stack (run after `cdk deploy`, and again after updates).

    uv run python scripts/migrate_db.py
"""

import argparse

from jobmecloud.admin.database import migrate_deployed

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--stack-name", default="JobMeCloud")
args = parser.parse_args()
try:
    changes = migrate_deployed(args.stack_name)
except LookupError as e:
    raise SystemExit(str(e))
print("Created or changed:", ", ".join(changes) if changes else "nothing (already up to date)")
