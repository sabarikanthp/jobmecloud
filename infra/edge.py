"""The public face: CloudFront serves the site from S3 and forwards /api/* to the API Gateway HTTP API."""

from aws_cdk import Fn
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_cognito as cognito
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from constructs import Construct

LOCAL_DEV_URL = "http://localhost:5173/"


class Edge(Construct):
    def __init__(self, scope: Construct, id: str, *, api_function: lambda_.IFunction, site_bucket: s3.IBucket,
                 user_pool: cognito.IUserPool, client: cognito.UserPoolClient, region: str,
                 site_domain: str | None = None, certificate_arn: str | None = None) -> None:
        super().__init__(scope, id)

        # Every route needs a valid access token from our user pool.
        authorizer = authorizers.HttpJwtAuthorizer(
            "Authorizer",
            f"https://cognito-idp.{region}.amazonaws.com/{user_pool.user_pool_id}",
            jwt_audience=[client.user_pool_client_id],
            identity_source=["$request.header.Authorization"],
        )
        self.api = apigw.HttpApi(self, "Api", create_default_stage=True)
        api_integration = integrations.HttpLambdaIntegration("ApiIntegration", api_function)
        self.api.add_routes(
            path="/api/{proxy+}",
            methods=[apigw.HttpMethod.ANY],
            integration=api_integration,
            authorizer=authorizer,
        )

        # The exceptions: Claude Desktop cannot sign in with Cognito, so it calls /api/mcp with an API key that the
        # app itself checks (hashed, revocable, scoped, rate-limited). ChatGPT and Claude on the web use OAuth: they
        # must find the sign-in metadata, register, start a sign-in and swap a code for tokens before they have any
        # login, so those four routes are open too and each checks what it is given. Approving a connection
        # (/api/oauth/approve) is NOT here: only the owner, signed in, can reach it. All are more specific than the
        # route above.
        for path, method in (
            ("/api/mcp", apigw.HttpMethod.POST),
            ("/.well-known/{proxy+}", apigw.HttpMethod.GET),
            ("/api/oauth/register", apigw.HttpMethod.POST),
            ("/api/oauth/authorize", apigw.HttpMethod.GET),
            ("/api/oauth/token", apigw.HttpMethod.POST),
        ):
            self.api.add_routes(path=path, methods=[method], integration=api_integration)

        api_origin = origins.HttpOrigin(Fn.select(2, Fn.split("/", self.api.api_endpoint)))
        self.distribution = cloudfront.Distribution(
            self, "Distribution",
            default_root_object="index.html",
            domain_names=[site_domain] if site_domain else None,
            certificate=acm.Certificate.from_certificate_arn(self, "SiteCertificate", certificate_arn) if certificate_arn else None,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
                # The sign-in metadata connectors look for at the site root (RFC 8414 and RFC 9728).
                "/.well-known/*": cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
            },
        )

        # Now the site address is known, let the browser app sign users back in to it.
        cloudfront_url = f"https://{self.distribution.distribution_domain_name}/"
        site_url = f"https://{site_domain}/" if site_domain else cloudfront_url
        # With your own hostname the CloudFront address keeps working too, so a sign-in there is never refused.
        allowed = [site_url, *([cloudfront_url] if site_domain else []), LOCAL_DEV_URL]
        cfn_client = client.node.default_child
        cfn_client.callback_ur_ls = allowed
        cfn_client.logout_ur_ls = allowed
        self.site_url = site_url
