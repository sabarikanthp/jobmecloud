import json
from unittest.mock import MagicMock

import boto3
import pytest

from jobmecloud.admin.site import publish_site

BUCKET = "jobmecloud-site-test"


@pytest.fixture
def deployed():
    boto3.client("s3").create_bucket(Bucket=BUCKET)
    template = {
        "Resources": {"Topic": {"Type": "AWS::SNS::Topic"}},
        "Outputs": {
            "SiteBucketName": {"Value": BUCKET}, "ClientId": {"Value": "client123"},
            "LoginDomain": {"Value": "login.example.com"}, "DistributionId": {"Value": "EDIST123"},
            "SiteUrl": {"Value": "https://d111.cloudfront.net/"},
        },
    }
    boto3.client("cloudformation").create_stack(StackName="JobMeCloud", TemplateBody=json.dumps(template))


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "assets" / "app-1a2b.js").write_text("console.log(1)")
    return tmp_path


def body(key):
    return boto3.client("s3").get_object(Bucket=BUCKET, Key=key)


def test_uploads_the_built_site_with_content_types(deployed, dist):
    publish_site("JobMeCloud", dist, cloudfront=MagicMock())
    assert body("index.html")["ContentType"] == "text/html"
    assert body("assets/app-1a2b.js")["ContentType"] in ("text/javascript", "application/javascript")


def test_index_is_never_cached_but_hashed_assets_are(deployed, dist):
    publish_site("JobMeCloud", dist, cloudfront=MagicMock())
    assert body("index.html")["CacheControl"] == "no-cache"
    assert "immutable" in body("assets/app-1a2b.js")["CacheControl"]


def test_writes_sign_in_config_from_stack_outputs(deployed, dist):
    publish_site("JobMeCloud", dist, cloudfront=MagicMock())
    config = json.loads(body("config.json")["Body"].read())
    assert config == {"domain": "login.example.com", "clientId": "client123"}
    assert body("config.json")["CacheControl"] == "no-cache"


def test_invalidates_the_cdn(deployed, dist):
    cloudfront = MagicMock()
    publish_site("JobMeCloud", dist, cloudfront=cloudfront)
    kwargs = cloudfront.create_invalidation.call_args.kwargs
    assert kwargs["DistributionId"] == "EDIST123"
    assert kwargs["InvalidationBatch"]["Paths"]["Items"] == ["/*"]


def test_missing_build_says_how_to_build(deployed, tmp_path):
    with pytest.raises(FileNotFoundError, match="npm run build"):
        publish_site("JobMeCloud", tmp_path / "nope", cloudfront=MagicMock())
