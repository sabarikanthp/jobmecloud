"""The JobMeCloud stack: data stores and the helper every Lambda is built with.

Nothing here has a fixed monthly charge: no VPC or NAT gateway, no provisioned capacity, no database
instances. Costs scale with use and sit inside the AWS free tiers for one person.
"""

from pathlib import Path

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_dsql as dsql
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct

from infra.auth import Auth
from infra.edge import Edge

WORKSPACE_PREFIX = "workspace"
BUDGET_USD = 5


def _private_bucket(scope: Construct, id: str, *, versioned: bool) -> s3.Bucket:
    return s3.Bucket(
        scope, id,
        versioned=versioned,
        block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        encryption=s3.BucketEncryption.S3_MANAGED,
        enforce_ssl=True,
        removal_policy=RemovalPolicy.RETAIN,  # never delete the owner's files by accident
    )


class JobMeCloudStack(Stack):
    def __init__(self, scope: Construct, id: str, *, owner_email: str, sender_email: str,
                 lambda_dist: str, timezone: str = "UTC", **kwargs) -> None:
        super().__init__(scope, id, **kwargs)
        self.owner_email = owner_email
        self.sender_email = sender_email
        self.lambda_dist = Path(lambda_dist)

        self.dsql_cluster = dsql.CfnCluster(self, "Database", deletion_protection_enabled=True)
        self.data_bucket = _private_bucket(self, "DataBucket", versioned=True)
        self.site_bucket = _private_bucket(self, "SiteBucket", versioned=False)

        self.layer = lambda_.LayerVersion(
            self, "DependenciesLayer",
            code=lambda_.Code.from_asset(str(self.lambda_dist / "layer.zip")),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            compatible_architectures=[lambda_.Architecture.ARM_64],
        )

        self.auth = Auth(self, "Auth", sender_email=sender_email, account=self.account, region=self.region)

        # Workers run long jobs outside the web request. They are never retried automatically: a failed run
        # is recorded on its Run, and a second invoke would start a duplicate.
        self.run_worker = self.make_function(
            "run-worker", "jobmecloud.handlers.run_worker.handler", timeout=900, memory=1024,
            env={"TZ": timezone}, no_retries=True,
        )
        self.docs_worker = self.make_function(
            "docs-worker", "jobmecloud.handlers.docs_worker.handler", timeout=300, memory=1024,
            env={"TZ": timezone}, no_retries=True,
        )

        # EventBridge Scheduler starts the run-worker on the owner's chosen days and times, using this role.
        self.scheduler_role = iam.Role(self, "SchedulerRole", assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"))
        self.run_worker.grant_invoke(self.scheduler_role)

        # API Gateway puts its own host in the request (CloudFront does not pass the viewer's host through).
        self.api_function = self.make_function(
            "api", "jobmecloud.handlers.api.handler", timeout=30, memory=512,
            env={
                "JOBMECLOUD_ALLOWED_HOSTS": f"*.execute-api.{self.region}.amazonaws.com",
                "JOBMECLOUD_RUN_FUNCTION": self.run_worker.function_name,
                "JOBMECLOUD_DOCS_FUNCTION": self.docs_worker.function_name,
                "JOBMECLOUD_RUN_FUNCTION_ARN": self.run_worker.function_arn,
                "JOBMECLOUD_SCHEDULER_ROLE_ARN": self.scheduler_role.role_arn,
                "JOBMECLOUD_TIMEZONE": timezone,
            },
        )
        self.run_worker.grant_invoke(self.api_function)
        self._allow_scheduling(timezone)
        self.docs_worker.grant_invoke(self.api_function)
        self.edge = Edge(
            self, "Edge", api_function=self.api_function, site_bucket=self.site_bucket,
            user_pool=self.auth.user_pool, client=self.auth.spa_client, region=self.region,
        )
        for name, value in {
            "SiteUrl": self.edge.site_url,
            "UserPoolId": self.auth.user_pool.user_pool_id,
            "ClientId": self.auth.spa_client.user_pool_client_id,
            "SiteBucketName": self.site_bucket.bucket_name,
            "DistributionId": self.edge.distribution.distribution_id,
            "LoginDomain": f"{self.auth.domain.domain_name}.auth.{self.region}.amazoncognito.com",
            "Region": self.region,
            "DatabaseEndpoint": self.dsql_cluster.attr_endpoint,
        }.items():
            CfnOutput(self, name, value=value)

        budgets.CfnBudget(
            self, "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_type="COST", time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=BUDGET_USD, unit="USD"),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        notification_type=kind, comparison_operator="GREATER_THAN",
                        threshold=threshold, threshold_type="PERCENTAGE"),
                    subscribers=[budgets.CfnBudget.SubscriberProperty(
                        subscription_type="EMAIL", address=owner_email)],
                )
                for kind, threshold in (("ACTUAL", 80), ("FORECASTED", 100))
            ],
        )

    def _allow_scheduling(self, timezone: str) -> None:
        """The API may create, change and delete only the jobmecloud-run-* schedules, and hand them the role."""
        self.api_function.add_to_role_policy(iam.PolicyStatement(
            actions=["scheduler:CreateSchedule", "scheduler:UpdateSchedule", "scheduler:DeleteSchedule",
                     "scheduler:GetSchedule"],
            resources=[self.format_arn(service="scheduler", resource="schedule", resource_name="default/jobmecloud-run-*")],
        ))
        self.api_function.add_to_role_policy(iam.PolicyStatement(actions=["scheduler:ListSchedules"], resources=["*"]))
        self.api_function.add_to_role_policy(iam.PolicyStatement(
            actions=["iam:PassRole"], resources=[self.scheduler_role.role_arn],
            conditions={"StringEquals": {"iam:PassedToService": "scheduler.amazonaws.com"}},
        ))

    def make_function(self, name: str, handler: str, *, timeout: int, memory: int,
                      env: dict[str, str] | None = None, no_retries: bool = False) -> lambda_.Function:
        """A Lambda with the shared settings: arm64, Python 3.12, 14-day logs, access to the data stores."""
        pascal = "".join(part.capitalize() for part in name.split("-"))
        fn = lambda_.Function(
            self, f"{pascal}Function",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=handler,
            code=lambda_.Code.from_asset(str(self.lambda_dist / f"{name}.zip")),
            layers=[self.layer],
            timeout=Duration.seconds(timeout),
            memory_size=memory,
            log_group=logs.LogGroup(self, f"{pascal}Logs", retention=logs.RetentionDays.TWO_WEEKS,
                                    removal_policy=RemovalPolicy.DESTROY),
            environment={
                "JOBMECLOUD_BUCKET": self.data_bucket.bucket_name,
                "JOBMECLOUD_PREFIX": WORKSPACE_PREFIX,
                "JOBMECLOUD_DB_URL": f"dsql://{self.dsql_cluster.attr_endpoint}",
                **(env or {}),
            },
        )
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["dsql:DbConnectAdmin"], resources=[self.dsql_cluster.attr_resource_arn]))
        fn.add_to_role_policy(iam.PolicyStatement(
            actions=["ssm:GetParameter", "ssm:PutParameter", "ssm:DeleteParameter"],
            resources=[self.format_arn(service="ssm", resource="parameter", resource_name="jobmecloud/*")]))
        self.data_bucket.grant_read_write(fn)
        if no_retries:
            fn.configure_async_invoke(retry_attempts=0)
        return fn
