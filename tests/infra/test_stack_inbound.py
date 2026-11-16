import pytest
from aws_cdk import App, assertions

from infra.jobmecloud_stack import JobMeCloudStack

from conftest import ENV

ADDRESS = "reports@mail.example.com"
SENDER = "sender@example.com"


def build(lambda_dist, **kwargs):
    return JobMeCloudStack(App(), "T", owner_email="owner@example.com", sender_email="noreply@example.com",
                           lambda_dist=lambda_dist, env=ENV, **kwargs)


@pytest.fixture(scope="module")
def inbound(lambda_dist):
    return assertions.Template.from_stack(build(lambda_dist, inbound_address=ADDRESS, inbound_sender=SENDER))


def function(template, handler):
    found = {f["Properties"]["Handler"]: (name, f["Properties"]) for name, f in template.find_resources("AWS::Lambda::Function").items()}
    return found[handler]


def role_statements(template, logical_function_name):
    """Every IAM statement attached to a function's execution role."""
    fn = template.to_json()["Resources"][logical_function_name]["Properties"]
    role = fn["Role"]["Fn::GetAtt"][0]
    out = []
    for policy in template.find_resources("AWS::IAM::Policy").values():
        if {"Ref": role} in policy["Properties"]["Roles"]:
            out += policy["Properties"]["PolicyDocument"]["Statement"]
    return out


def actions(statement):
    value = statement["Action"]
    return [value] if isinstance(value, str) else value


def mail_bucket(template):
    buckets = template.find_resources("AWS::S3::Bucket")
    named = [(n, b) for n, b in buckets.items() if "LifecycleConfiguration" in b["Properties"]]
    assert len(named) == 1
    return named[0]


def test_without_inbound_settings_nothing_is_added(template):
    handlers = {f["Properties"]["Handler"] for f in template.find_resources("AWS::Lambda::Function").values()}
    assert "jobmecloud.handlers.ingest.handler" not in handlers
    assert len(template.find_resources("AWS::S3::Bucket")) == 2
    assert "MailBucketName" not in template.to_json()["Outputs"]
    assert not template.find_resources("AWS::SES::ReceiptRuleSet")


def test_mail_bucket_is_private_encrypted_https_only_and_expires_in_30_days(inbound):
    name, bucket = mail_bucket(inbound)
    props = bucket["Properties"]
    assert props["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True, "BlockPublicPolicy": True, "IgnorePublicAcls": True, "RestrictPublicBuckets": True}
    assert "BucketEncryption" in props
    assert props["LifecycleConfiguration"]["Rules"][0]["ExpirationInDays"] == 30
    assert props["LifecycleConfiguration"]["Rules"][0]["Status"] == "Enabled"
    policies = [p["Properties"]["PolicyDocument"]["Statement"] for p in inbound.find_resources("AWS::S3::BucketPolicy").values()
                if p["Properties"]["Bucket"] == {"Ref": name}]
    assert any(s.get("Effect") == "Deny" and "aws:SecureTransport" in str(s.get("Condition")) for st in policies for s in st)


def test_ingest_function_is_256mb_3_minutes_arm64(inbound):
    _, fn = function(inbound, "jobmecloud.handlers.ingest.handler")
    assert (fn["MemorySize"], fn["Timeout"], fn["Architectures"]) == (256, 180, ["arm64"])
    env = fn["Environment"]["Variables"]
    assert env["JOBMECLOUD_INBOUND_ADDRESS"] == ADDRESS and env["JOBMECLOUD_INBOUND_SENDER"] == SENDER
    assert env["JOBMECLOUD_INBOUND_DAILY_LIMIT"] == "5" and "JOBMECLOUD_RUN_FUNCTION" in env
    assert "JOBMECLOUD_DB_URL" in env and "JOBMECLOUD_BUCKET" not in env  # no data bucket


def test_ingest_role_has_no_parameter_store_or_data_bucket_access(inbound):
    name, _ = function(inbound, "jobmecloud.handlers.ingest.handler")
    statements = role_statements(inbound, name)
    assert not any(a.startswith("ssm:") for s in statements for a in actions(s))
    assert not any("DataBucket" in str(s.get("Resource")) for s in statements)


def test_ingest_can_invoke_only_the_run_worker(inbound):
    name, _ = function(inbound, "jobmecloud.handlers.ingest.handler")
    worker_name, _ = function(inbound, "jobmecloud.handlers.run_worker.handler")
    invokes = [s for s in role_statements(inbound, name) if "lambda:InvokeFunction" in actions(s)]
    assert invokes, "ingest cannot start the run worker"
    for s in invokes:
        assert worker_name in str(s["Resource"]) and "*" != s["Resource"]


def test_bucket_notification_targets_the_ingest_function_for_new_mail_only(inbound):
    name, _ = function(inbound, "jobmecloud.handlers.ingest.handler")
    config = next(iter(inbound.find_resources("Custom::S3BucketNotifications").values()))["Properties"]["NotificationConfiguration"]
    target = config["LambdaFunctionConfigurations"][0]
    assert target["Events"] == ["s3:ObjectCreated:*"] and name in str(target["LambdaFunctionArn"])
    assert {"Name": "prefix", "Value": "inbound/"} in target["Filter"]["Key"]["FilterRules"]


def test_run_worker_can_read_the_mail_bucket_and_knows_its_name(inbound):
    name, fn = function(inbound, "jobmecloud.handlers.run_worker.handler")
    bucket_name, _ = mail_bucket(inbound)
    assert fn["Environment"]["Variables"]["JOBMECLOUD_INBOX_BUCKET"] == {"Ref": bucket_name}
    reads = [s for s in role_statements(inbound, name) if "s3:GetObject*" in actions(s) and bucket_name in str(s["Resource"])]
    assert reads, "the run worker cannot read the mail bucket"


def test_mail_bucket_name_is_published_for_the_replay_script(inbound):
    assert "MailBucketName" in inbound.to_json()["Outputs"]


def test_address_and_sender_must_be_given_together(lambda_dist):
    with pytest.raises(ValueError, match="both"):
        build(lambda_dist, inbound_address=ADDRESS)
    with pytest.raises(ValueError, match="both"):
        build(lambda_dist, inbound_sender=SENDER)


def rule(template):
    found = template.find_resources("AWS::SES::ReceiptRule")
    assert len(found) == 1
    return next(iter(found.values()))["Properties"]["Rule"]


def test_receipt_rule_matches_only_the_configured_address(inbound):
    assert rule(inbound)["Recipients"] == [ADDRESS]


def test_rule_scans_for_spam_and_virus_and_requires_tls(inbound):
    r = rule(inbound)
    assert r["ScanEnabled"] is True and r["TlsPolicy"] == "Require" and r["Enabled"] is True


def test_rule_writes_to_the_mail_bucket_under_the_inbound_prefix(inbound):
    bucket_name, _ = mail_bucket(inbound)
    action = rule(inbound)["Actions"][0]["S3Action"]
    assert action["BucketName"] == {"Ref": bucket_name} and action["ObjectKeyPrefix"] == "inbound/"


def test_bucket_policy_lets_ses_write_only_from_this_account(inbound):
    bucket_name, _ = mail_bucket(inbound)
    statements = [s for p in inbound.find_resources("AWS::S3::BucketPolicy").values()
                  if p["Properties"]["Bucket"] == {"Ref": bucket_name}
                  for s in p["Properties"]["PolicyDocument"]["Statement"]]
    ses = [s for s in statements if s.get("Principal") == {"Service": "ses.amazonaws.com"}]
    assert ses and all(s["Action"] == "s3:PutObject" for s in ses)
    assert all(s["Condition"]["StringEquals"]["aws:SourceAccount"] == {"Ref": "AWS::AccountId"} for s in ses)
    assert all(s["Resource"]["Fn::Join"][1][-1] == "/inbound/*" for s in ses)  # only under the inbound prefix


def test_a_custom_resource_activates_the_rule_set(inbound):
    rule_set = next(iter(inbound.find_resources("AWS::SES::ReceiptRuleSet")))
    resources = [r for r in inbound.to_json()["Resources"].values()
                 if r["Type"] == "AWS::CloudFormation::CustomResource" and r["Properties"].get("RuleSetName") == {"Ref": rule_set}]
    assert len(resources) == 1
