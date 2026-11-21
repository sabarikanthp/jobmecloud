import pytest
from aws_cdk import App, assertions

from infra.jobmecloud_stack import JobMeCloudStack

from conftest import ENV

DOMAIN = "jobs.example.com"
CERT = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-abcdefabcdef"
PUBLIC = {"POST /api/mcp", "GET /.well-known/{proxy+}", "POST /api/oauth/register", "GET /api/oauth/authorize",
          "POST /api/oauth/token"}


def build(lambda_dist, **kwargs):
    return JobMeCloudStack(App(), "T", owner_email="owner@example.com", sender_email="noreply@example.com",
                           lambda_dist=lambda_dist, env=ENV, **kwargs)


@pytest.fixture(scope="module")
def custom(lambda_dist):
    return assertions.Template.from_stack(build(lambda_dist, site_domain=DOMAIN, certificate_arn=CERT))


def api_function_env(template):
    fn = next(f["Properties"] for f in template.find_resources("AWS::Lambda::Function").values()
              if f["Properties"]["Handler"] == "jobmecloud.handlers.api.handler")
    return fn["Environment"]["Variables"]


def test_only_the_sign_in_routes_skip_the_authorizer(template):
    open_routes = {r["Properties"]["RouteKey"] for r in template.find_resources("AWS::ApiGatewayV2::Route").values()
                   if r["Properties"]["AuthorizationType"] == "NONE"}
    assert open_routes == PUBLIC


def test_approving_and_client_lookup_stay_behind_the_authorizer(template):
    keys = {r["Properties"]["RouteKey"]: r["Properties"]["AuthorizationType"]
            for r in template.find_resources("AWS::ApiGatewayV2::Route").values()}
    assert keys["ANY /api/{proxy+}"] == "JWT"
    for needed in ("POST /api/oauth/approve", "GET /api/oauth/clients/x"):
        assert needed not in PUBLIC and needed not in keys  # only the authorized catch-all can match them


def test_cloudfront_sends_well_known_to_the_api(template):
    dist = list(template.find_resources("AWS::CloudFront::Distribution").values())[0]["Properties"]["DistributionConfig"]
    paths = [b["PathPattern"] for b in dist["CacheBehaviors"]]
    assert paths == ["/api/*", "/.well-known/*"]
    behavior = dist["CacheBehaviors"][1]
    assert behavior["CachePolicyId"] == "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    assert behavior["ViewerProtocolPolicy"] == "https-only"
    assert sorted(behavior["AllowedMethods"]) == ["GET", "HEAD"]
    assert behavior["TargetOriginId"] == dist["CacheBehaviors"][0]["TargetOriginId"]


def test_site_url_is_set_with_a_custom_domain_and_absent_without(template, custom):
    assert api_function_env(custom)["JOBMECLOUD_SITE_URL"] == f"https://{DOMAIN}"
    assert "JOBMECLOUD_SITE_URL" not in api_function_env(template)


def test_the_site_cannot_be_framed(template):
    """The consent page must refuse to be shown inside another site's frame."""
    dist = list(template.find_resources("AWS::CloudFront::Distribution").values())[0]["Properties"]["DistributionConfig"]
    policy_id = dist["DefaultCacheBehavior"]["ResponseHeadersPolicyId"]
    policies = template.find_resources("AWS::CloudFront::ResponseHeadersPolicy")
    config = next(iter(policies.values()))["Properties"]["ResponseHeadersPolicyConfig"]
    assert policy_id["Ref"] in policies
    assert config["SecurityHeadersConfig"]["FrameOptions"] == {"FrameOption": "DENY", "Override": True}
