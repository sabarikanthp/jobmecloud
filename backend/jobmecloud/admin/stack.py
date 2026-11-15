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
