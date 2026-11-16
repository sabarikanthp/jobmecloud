import pytest
from aws_cdk import App, assertions

from infra.jobmecloud_stack import JobMeCloudStack

from conftest import ENV

DOMAIN = "jobs.example.com"
CERT = "arn:aws:acm:us-east-1:123456789012:certificate/11111111-2222-3333-4444-abcdefabcdef"


def build(lambda_dist, **kwargs):
    return JobMeCloudStack(App(), "T", owner_email="owner@example.com", sender_email="noreply@example.com",
                           lambda_dist=lambda_dist, env=ENV, **kwargs)


@pytest.fixture(scope="module")
def custom(lambda_dist):
    return assertions.Template.from_stack(build(lambda_dist, site_domain=DOMAIN, certificate_arn=CERT))


def only(template, type_):
    found = template.find_resources(type_)
    assert len(found) == 1
    return list(found.values())[0]["Properties"]


def test_distribution_answers_to_the_custom_hostname_with_the_certificate(custom):
    dist = only(custom, "AWS::CloudFront::Distribution")["DistributionConfig"]
    assert dist["Aliases"] == [DOMAIN]
    cert = dist["ViewerCertificate"]
    assert cert["AcmCertificateArn"] == CERT and cert["SslSupportMethod"] == "sni-only"


def test_sign_in_returns_to_the_custom_site_and_still_to_the_cloudfront_address(custom):
    client = only(custom, "AWS::Cognito::UserPoolClient")
    assert f"https://{DOMAIN}/" in client["CallbackURLs"]
    assert f"https://{DOMAIN}/" in client["LogoutURLs"]
    assert any("cloudfront" in str(u).lower() or "Fn::GetAtt" in str(u) for u in client["CallbackURLs"])
    assert "http://localhost:5173/" in client["CallbackURLs"]


def test_site_url_output_is_the_custom_address_and_the_dns_target_is_published(custom):
    outputs = custom.to_json()["Outputs"]
    assert outputs["SiteUrl"]["Value"] == f"https://{DOMAIN}/"
    assert "DistributionDomain" in outputs  # what the DNS CNAME must point to


def test_without_a_custom_domain_nothing_changes(template):
    dist = only(template, "AWS::CloudFront::Distribution")["DistributionConfig"]
    assert "Aliases" not in dist
    assert "ViewerCertificate" not in dist  # the default *.cloudfront.net certificate


def test_hostname_and_certificate_must_be_given_together(lambda_dist):
    with pytest.raises(ValueError, match="both"):
        build(lambda_dist, site_domain=DOMAIN)
    with pytest.raises(ValueError, match="both"):
        build(lambda_dist, certificate_arn=CERT)


def test_certificate_must_be_in_us_east_1(lambda_dist):
    with pytest.raises(ValueError, match="us-east-1"):
        build(lambda_dist, site_domain=DOMAIN, certificate_arn=CERT.replace("us-east-1", "eu-west-1"))
