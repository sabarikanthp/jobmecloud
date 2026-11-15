"""Upload the built website to your deployed stack.

    cd frontend && npm install && npm run build && cd ..
    uv run python scripts/publish_site.py
"""

import argparse
from pathlib import Path

from jobmecloud.admin.site import publish_site

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--stack-name", default="JobMeCloud")
parser.add_argument("--dist", default=str(Path(__file__).resolve().parents[1] / "frontend" / "dist"))
args = parser.parse_args()
print("Published:", publish_site(args.stack_name, Path(args.dist)))
