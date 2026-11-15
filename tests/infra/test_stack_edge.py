from aws_cdk import assertions

CACHING_DISABLED = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"  # AWS managed cache policy


def only(template, type_):
    found = template.find_resources(type_)
    assert len(found) == 1, f"expected one {type_}, found {len(found)}"
    return list(found.values())[0]["Properties"]


def test_api_routes_require_authorizer(template):
    routes = template.find_resources("AWS::ApiGatewayV2::Route")
    assert routes, "the API has no routes"
    for route in routes.values():
        props = route["Properties"]
        assert props["AuthorizationType"] == "JWT" and "AuthorizerId" in props
        assert props["RouteKey"].endswith("/api/{proxy+}")


def test_authorizer_checks_the_user_pool_and_client(template):
    auth = only(template, "AWS::ApiGatewayV2::Authorizer")
    assert auth["AuthorizerType"] == "JWT"
    assert auth["IdentitySource"] == ["$request.header.Authorization"]
    assert "Audience" in auth["JwtConfiguration"] and "Issuer" in auth["JwtConfiguration"]


def test_cloudfront_api_behavior_targets_http_api(template):
    dist = only(template, "AWS::CloudFront::Distribution")["DistributionConfig"]
    behavior = dist["CacheBehaviors"][0]
    assert behavior["PathPattern"] == "/api/*"
    assert behavior["ViewerProtocolPolicy"] == "https-only"
    assert behavior["CachePolicyId"] == CACHING_DISABLED
    assert sorted(behavior["AllowedMethods"]) == ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]


def test_api_errors_are_never_rewritten_into_the_web_page(template):
    """CloudFront error pages apply to the whole distribution, so none may be set: a real 404 from the
    API (no such job, no documents yet) must reach the browser as a 404, not as index.html with a 200."""
    dist = only(template, "AWS::CloudFront::Distribution")["DistributionConfig"]
    assert "CustomErrorResponses" not in dist
    assert dist["DefaultRootObject"] == "index.html"


def test_site_bucket_only_readable_through_cloudfront(template):
    policies = template.find_resources("AWS::S3::BucketPolicy")
    statements = [s for p in policies.values() for s in p["Properties"]["PolicyDocument"]["Statement"]]
    cloudfront = [s for s in statements if s.get("Principal") == {"Service": "cloudfront.amazonaws.com"}]
    assert cloudfront and all("AWS:SourceArn" in s["Condition"]["StringEquals"] for s in cloudfront)


def test_browser_client_sends_users_back_to_the_site(template):
    client = only(template, "AWS::Cognito::UserPoolClient")
    assert any("https://" in str(url) for url in client["CallbackURLs"])
    assert "http://localhost:5173/" in client["CallbackURLs"]


def test_api_function_accepts_api_gateway_hosts(template):
    fn = next(f["Properties"] for f in template.find_resources("AWS::Lambda::Function").values()
              if f["Properties"]["Handler"] == "jobmecloud.handlers.api.handler")
    hosts = fn["Environment"]["Variables"]["JOBMECLOUD_ALLOWED_HOSTS"]
    assert hosts == "*.execute-api.us-east-1.amazonaws.com"
    assert fn["Handler"] == "jobmecloud.handlers.api.handler" and fn["Timeout"] == 30 and fn["MemorySize"] == 512


def test_outputs_the_deploy_scripts_need(template):
    outputs = template.to_json()["Outputs"]
    for name in ("SiteUrl", "UserPoolId", "ClientId", "SiteBucketName", "DistributionId", "LoginDomain", "Region",
                 "DatabaseEndpoint"):
        assert name in outputs, name
