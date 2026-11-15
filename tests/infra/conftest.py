import zipfile
from pathlib import Path

import pytest
from aws_cdk import App, Environment, assertions

from infra.jobmecloud_stack import JobMeCloudStack


ENV = Environment(account="123456789012", region="us-east-1")


@pytest.fixture(scope="session")
def lambda_dist(tmp_path_factory):
    """Stand-in build output so the stack can synthesize without running the real build."""
    dist = tmp_path_factory.mktemp("dist")
    for name in ("layer", "api", "run-worker", "docs-worker", "ext-api", "presignup"):
        with zipfile.ZipFile(dist / f"{name}.zip", "w") as z:
            z.writestr("placeholder.py", "")
    return str(dist)


@pytest.fixture(scope="session")
def stack(lambda_dist):
    app = App()
    return JobMeCloudStack(app, "T", owner_email="owner@example.com", sender_email="noreply@example.com",
                           lambda_dist=lambda_dist, env=ENV)


@pytest.fixture(scope="session")
def template(stack) -> assertions.Template:
    return assertions.Template.from_stack(stack)
