from aws_cdk import assertions
from aws_cdk import aws_lambda as lambda_


def test_data_bucket_private_and_versioned(template):
    template.has_resource_properties("AWS::S3::Bucket", {
        "VersioningConfiguration": {"Status": "Enabled"},
        "PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "BlockPublicPolicy": True,
            "IgnorePublicAcls": True, "RestrictPublicBuckets": True},
    })


def test_every_bucket_blocks_public_access(template):
    for bucket in template.find_resources("AWS::S3::Bucket").values():
        assert bucket["Properties"]["PublicAccessBlockConfiguration"]["BlockPublicPolicy"] is True


def test_no_nat_gateway_or_vpc(template):
    template.resource_count_is("AWS::EC2::NatGateway", 0)
    template.resource_count_is("AWS::EC2::VPC", 0)


def test_dsql_cluster_is_protected_from_deletion(template):
    template.has_resource_properties("AWS::DSQL::Cluster", {"DeletionProtectionEnabled": True})


def test_budget_5_usd_alerts_the_owner(template):
    template.has_resource_properties("AWS::Budgets::Budget", {
        "Budget": assertions.Match.object_like({
            "BudgetType": "COST", "TimeUnit": "MONTHLY",
            "BudgetLimit": {"Amount": 5, "Unit": "USD"}}),
        "NotificationsWithSubscribers": assertions.Match.array_with([
            assertions.Match.object_like({
                "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "owner@example.com"}]})]),
    })


def test_functions_are_arm64_python312_with_14_day_logs(stack, lambda_dist):
    from aws_cdk import App

    from infra.jobmecloud_stack import JobMeCloudStack
    s = JobMeCloudStack(App(), "F", owner_email="o@example.com", sender_email="n@example.com",
                        lambda_dist=lambda_dist)
    s.make_function("api", "jobmecloud.handlers.api.handler", timeout=30, memory=512)
    t = assertions.Template.from_stack(s)
    t.has_resource_properties("AWS::Lambda::Function", {
        "Architectures": ["arm64"], "Runtime": "python3.12", "Timeout": 30, "MemorySize": 512})
    t.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 14})
    assert lambda_.Architecture.ARM_64.name == "arm64"


def test_function_is_wired_to_data_stores(lambda_dist):
    from aws_cdk import App

    from infra.jobmecloud_stack import JobMeCloudStack
    s = JobMeCloudStack(App(), "W", owner_email="o@example.com", sender_email="n@example.com",
                        lambda_dist=lambda_dist)
    s.make_function("api", "jobmecloud.handlers.api.handler", timeout=30, memory=512)
    t = assertions.Template.from_stack(s)
    env = list(t.find_resources("AWS::Lambda::Function").values())[0]["Properties"]["Environment"]["Variables"]
    assert {"JOBMECLOUD_BUCKET", "JOBMECLOUD_DB_URL", "JOBMECLOUD_PREFIX"} <= set(env)
    t.has_resource_properties("AWS::IAM::Policy", {"PolicyDocument": {"Statement": assertions.Match.array_with([
        assertions.Match.object_like({"Action": "dsql:DbConnectAdmin"})])}})
    t.has_resource_properties("AWS::IAM::Policy", {"PolicyDocument": {"Statement": assertions.Match.array_with([
        assertions.Match.object_like({"Action": assertions.Match.array_with(
            ["ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter"])})])}})
