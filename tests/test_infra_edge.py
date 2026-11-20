import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import Stack, assertions  # noqa: E402
from aws_cdk import aws_cognito as cognito  # noqa: E402
from aws_cdk import aws_lambda as lambda_  # noqa: E402
from aws_cdk import aws_s3 as s3  # noqa: E402

from infra.edge import Edge  # noqa: E402


@pytest.fixture(scope="module")
def routes():
    app = aws_cdk.App()
    stack = Stack(app, "T", env=aws_cdk.Environment(account="123456789012", region="us-east-1"))
    pool = cognito.UserPool(stack, "Pool")
    client = pool.add_client("Client", o_auth=cognito.OAuthSettings(
        flows=cognito.OAuthFlows(authorization_code_grant=True), callback_urls=["http://localhost/"]))
    fn = lambda_.Function(stack, "Fn", runtime=lambda_.Runtime.PYTHON_3_12, handler="x.y",
                          code=lambda_.Code.from_inline("def y(e, c): pass"))
    Edge(stack, "Edge", api_function=fn, site_bucket=s3.Bucket(stack, "Site"), user_pool=pool, client=client,
         region="us-east-1")
    found = assertions.Template.from_stack(stack).find_resources("AWS::ApiGatewayV2::Route")
    return {r["Properties"]["RouteKey"]: r["Properties"]["AuthorizationType"] for r in found.values()}


def test_only_the_mcp_route_skips_the_sign_in_check(routes):
    open_routes = {k for k, v in routes.items() if v == "NONE"}
    assert open_routes == {"POST /api/mcp"}


def test_every_other_route_needs_a_signed_in_token(routes):
    assert routes["ANY /api/{proxy+}"] == "JWT"
    assert all(v == "JWT" for k, v in routes.items() if k != "POST /api/mcp")
