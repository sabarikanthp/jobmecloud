"""Optional: a daily report emailed to a dedicated address starts a run (see docs/email-ingest.md).

SES delivers each message to a private mail bucket; the bucket notifies a small ingest function, which checks
the message and starts the run worker. Nothing here exists unless inbound_address and inbound_sender are set.
"""

from collections.abc import Callable
from pathlib import Path

from aws_cdk import CustomResource, Duration, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_ses as ses
from aws_cdk import aws_ses_actions as ses_actions
from aws_cdk import custom_resources as cr
from constructs import Construct

MAIL_PREFIX = "inbound/"  # SES writes under this prefix; other objects (SES's setup test file) are ignored
MAIL_RETENTION_DAYS = 30


class Inbound(Construct):
    def __init__(self, scope: Construct, id: str, *, make_function: Callable[..., lambda_.Function],
                 run_worker: lambda_.IFunction, address: str, sender: str, daily_limit: int) -> None:
        super().__init__(scope, id)
        self.address, self.sender = address, sender

        self.bucket = s3.Bucket(
            self, "MailBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(MAIL_RETENTION_DAYS))],
            removal_policy=RemovalPolicy.RETAIN,  # the raw reports are the owner's data
        )

        # Small and narrow: it may read the mail bucket, use the database and start the run worker. No secrets,
        # no data bucket.
        self.function = make_function(
            "ingest", "jobmecloud.handlers.ingest.handler", timeout=180, memory=256,
            secrets=False, data_access=False,
            env={
                "JOBMECLOUD_INBOUND_ADDRESS": address,
                "JOBMECLOUD_INBOUND_SENDER": sender,
                "JOBMECLOUD_INBOUND_DAILY_LIMIT": str(daily_limit),
                "JOBMECLOUD_RUN_FUNCTION": run_worker.function_name,
            },
        )
        run_worker.grant_invoke(self.function)
        self.bucket.grant_read(self.function)
        self.bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED, s3n.LambdaDestination(self.function),
            s3.NotificationKeyFilter(prefix=MAIL_PREFIX))

        # The run worker reads the stored message to get its candidates.
        self.bucket.grant_read(run_worker)
        run_worker.add_environment("JOBMECLOUD_INBOX_BUCKET", self.bucket.bucket_name)

        self._receive_into_the_bucket(address)

    def _receive_into_the_bucket(self, address: str) -> None:
        """SES accepts mail for exactly this address (scanned, TLS required) and stores it in the mail bucket."""
        self.rule_set = ses.ReceiptRuleSet(
            self, "RuleSet", receipt_rule_set_name=f"{Stack.of(self).stack_name}-inbound")
        rule = self.rule_set.add_rule(
            "Reports", recipients=[address], scan_enabled=True, tls_policy=ses.TlsPolicy.REQUIRE,
            actions=[ses_actions.S3(bucket=self.bucket, object_key_prefix=MAIL_PREFIX)])

        # CloudFormation cannot activate a rule set, so a tiny function does (and refuses to replace another one).
        activator = lambda_.Function(
            self, "ActivateRulesFunction", runtime=lambda_.Runtime.PYTHON_3_12, architecture=lambda_.Architecture.ARM_64,
            handler="index.on_event", timeout=Duration.seconds(60),
            code=lambda_.Code.from_asset(str(Path(__file__).parent / "rules_handler")))
        activator.add_to_role_policy(iam.PolicyStatement(
            actions=["ses:DescribeActiveReceiptRuleSet", "ses:SetActiveReceiptRuleSet"], resources=["*"]))
        provider = cr.Provider(self, "ActivateProvider", on_event_handler=activator)
        activation = CustomResource(self, "ActivateRules", service_token=provider.service_token,
                                    properties={"RuleSetName": self.rule_set.receipt_rule_set_name})
        activation.node.add_dependency(self.rule_set)
        activation.node.add_dependency(rule)
