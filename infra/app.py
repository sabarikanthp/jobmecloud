#!/usr/bin/env python3
"""CDK entry point: `cdk deploy -c owner_email=you@example.com -c sender_email=you@example.com`."""

import os

import aws_cdk as cdk

from infra.jobmecloud_stack import JobMeCloudStack

app = cdk.App()
owner_email = app.node.try_get_context("owner_email")
if not owner_email:
    raise SystemExit("Pass your email: cdk deploy -c owner_email=you@example.com -c sender_email=you@example.com")
JobMeCloudStack(
    app, "JobMeCloud",
    owner_email=owner_email,
    sender_email=app.node.try_get_context("sender_email") or owner_email,
    lambda_dist=app.node.try_get_context("lambda_dist") or "dist/lambda",
    timezone=app.node.try_get_context("timezone") or "UTC",
    site_domain=app.node.try_get_context("site_domain"),
    certificate_arn=app.node.try_get_context("certificate_arn"),
    inbound_address=app.node.try_get_context("inbound_address"),
    inbound_sender=app.node.try_get_context("inbound_sender"),
    inbound_daily_limit=int(app.node.try_get_context("inbound_daily_limit") or 5),
    env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=os.environ.get("CDK_DEFAULT_REGION")),
)
app.synth()
