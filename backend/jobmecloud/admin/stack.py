"""Read a deployed stack's outputs (the addresses and ids the helper scripts need)."""

import boto3
from botocore.exceptions import ClientError


def stack_outputs(stack_name: str, cfn=None) -> dict[str, str]:
    cfn = cfn or boto3.client("cloudformation")
    try:
        stack = cfn.describe_stacks(StackName=stack_name)["Stacks"][0]
    except ClientError:
        raise LookupError(
            f"No stack named {stack_name} was found in this account and region. "
            "Deploy it first with `uv run cdk deploy`, and check AWS_REGION is the one you deployed to."
        ) from None
    return {o["OutputKey"]: o["OutputValue"] for o in stack.get("Outputs", [])}


def data_bucket(stack_name: str, cfn=None, lam=None) -> str:
    """The data bucket's name. It is not a stack output, so read it from the API function's settings."""
    cfn = cfn or boto3.client("cloudformation")
    lam = lam or boto3.client("lambda")
    for page in cfn.get_paginator("list_stack_resources").paginate(StackName=stack_name):
        for res in page["StackResourceSummaries"]:
            if res["ResourceType"] == "AWS::Lambda::Function" and res["LogicalResourceId"].startswith("ApiFunction"):
                env = lam.get_function_configuration(FunctionName=res["PhysicalResourceId"])["Environment"]["Variables"]
                return env["JOBMECLOUD_BUCKET"]
    raise LookupError(f"Could not find the API function in stack {stack_name}.")
