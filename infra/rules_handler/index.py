"""Activate (and on delete, deactivate) the SES receipt rule set for JobMeCloud.

CloudFormation can create a rule set but cannot make it the active one, and SES allows only one active rule set
per region. So this never replaces a rule set that something else is using: it fails the deploy with a clear
message instead.
"""

import boto3


def _active(ses) -> str | None:
    return ses.describe_active_receipt_rule_set().get("Metadata", {}).get("Name")


def on_event(event, context, ses=None):
    ses = ses or boto3.client("ses")
    name = event["ResourceProperties"]["RuleSetName"]
    active = _active(ses)
    if event["RequestType"] == "Delete":
        if active == name:
            ses.set_active_receipt_rule_set()  # no name: nothing is active, so the rule set can be deleted
        return {"PhysicalResourceId": name}
    if active and active != name:
        raise Exception(
            f"Another SES receipt rule set named '{active}' is already active in this region, and SES allows only "
            f"one. JobMeCloud will not replace it. Add a rule for the report address to '{active}' yourself, or "
            f"deactivate it, then deploy again.")
    if active != name:
        ses.set_active_receipt_rule_set(RuleSetName=name)
    return {"PhysicalResourceId": name}
