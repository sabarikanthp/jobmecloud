from aws_cdk import assertions


def pool(template):
    return list(template.find_resources("AWS::Cognito::UserPool").values())[0]["Properties"]


def test_self_signup_disabled(template):
    assert pool(template)["AdminCreateUserConfig"]["AllowAdminCreateUserOnly"] is True


def test_mfa_required_totp_and_email_only(template):
    p = pool(template)
    assert p["MfaConfiguration"] == "ON"
    assert sorted(p["EnabledMfas"]) == ["EMAIL_OTP", "SOFTWARE_TOKEN_MFA"]


def test_no_sms_configuration(template):
    p = pool(template)
    assert "SmsConfiguration" not in p and "SMS_MFA" not in p["EnabledMfas"]


def test_feature_plan_essentials(template):
    assert pool(template)["UserPoolTier"] == "ESSENTIALS"


def test_account_recovery_disabled(template):
    mechanisms = pool(template)["AccountRecoverySetting"]["RecoveryMechanisms"]
    assert mechanisms == [{"Name": "admin_only", "Priority": 1}]


def test_login_email_is_sent_from_the_verified_sender_through_ses(template):
    email = pool(template)["EmailConfiguration"]
    assert email["EmailSendingAccount"] == "DEVELOPER"
    assert email["From"] == "JobMeCloud <noreply@example.com>"
    assert "identity/noreply@example.com" in str(email["SourceArn"])


def test_pool_is_protected_from_deletion(template):
    assert pool(template)["DeletionProtection"] == "ACTIVE"


def test_spa_client_has_no_secret_and_uses_code_flow(template):
    clients = template.find_resources("AWS::Cognito::UserPoolClient")
    assert len(clients) == 1
    props = list(clients.values())[0]["Properties"]
    assert props.get("GenerateSecret", False) is False
    assert props["AllowedOAuthFlows"] == ["code"]
    assert "implicit" not in props["AllowedOAuthFlows"]


def test_hosted_login_domain_exists(template):
    template.resource_count_is("AWS::Cognito::UserPoolDomain", 1)
