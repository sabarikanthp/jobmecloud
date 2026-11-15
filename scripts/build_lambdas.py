"""Package the Lambda functions into dist/lambda (run before `cdk deploy`).

    uv run python scripts/build_lambdas.py
"""

import argparse
from pathlib import Path

from jobmecloud.admin.build import BuildError, build_all

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--dist", default=str(root / "dist" / "lambda"))
args = parser.parse_args()
try:
    for path in build_all(Path(args.dist), root):
        print(f"{path.name}: {path.stat().st_size / 1024 / 1024:.1f} MB")
except BuildError as e:
    raise SystemExit(f"Build failed: {e}")
