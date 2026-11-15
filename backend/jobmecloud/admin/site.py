"""Upload the built frontend to the site bucket, with the sign-in settings the browser needs."""

import json
import mimetypes
from pathlib import Path

import boto3

NO_CACHE = "no-cache"
IMMUTABLE = "public, max-age=31536000, immutable"  # Vite file names contain a content hash


def _outputs(stack_name: str, cfn=None) -> dict[str, str]:
    cfn = cfn or boto3.client("cloudformation")
    stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def publish_site(stack_name: str, dist_dir: Path, *, s3=None, cloudfront=None, cfn=None) -> str:
    """Upload `dist_dir`, write config.json, refresh the CDN. Returns the site address."""
    dist_dir = Path(dist_dir)
    if not (dist_dir / "index.html").is_file():
        raise FileNotFoundError(f"No built site in {dist_dir}. Run `npm run build` in the frontend folder first.")
    s3 = s3 or boto3.client("s3")
    cloudfront = cloudfront or boto3.client("cloudfront")
    out = _outputs(stack_name, cfn)
    bucket = out["SiteBucketName"]

    for path in sorted(p for p in dist_dir.rglob("*") if p.is_file()):
        key = path.relative_to(dist_dir).as_posix()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        s3.put_object(Bucket=bucket, Key=key, Body=path.read_bytes(), ContentType=content_type,
                      CacheControl=IMMUTABLE if key.startswith("assets/") else NO_CACHE)
    config = {"domain": out["LoginDomain"], "clientId": out["ClientId"]}
    s3.put_object(Bucket=bucket, Key="config.json", Body=json.dumps(config).encode(),
                  ContentType="application/json", CacheControl=NO_CACHE)
    cloudfront.create_invalidation(
        DistributionId=out["DistributionId"],
        InvalidationBatch={"Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": f"publish-{id(config)}"},
    )
    return out["SiteUrl"]
