"""Optional: a daily report emailed to a dedicated address starts a run (see docs/email-ingest.md).

SES delivers each message to a private mail bucket; the bucket notifies a small ingest function, which checks
the message and starts the run worker. Nothing here exists unless inbound_address and inbound_sender are set.
"""

from collections.abc import Callable

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
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
