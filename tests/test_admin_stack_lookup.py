import json
from unittest.mock import MagicMock

import boto3
import pytest

from jobmecloud.admin.database import migrate_deployed
from jobmecloud.admin.owner import create_owner, pool_id_from_stack


@pytest.fixture
def deployed():
    template = {
        "Resources": {"Topic": {"Type": "AWS::SNS::Topic"}},
        "Outputs": {"DatabaseEndpoint": {"Value": "abc123.dsql.us-east-1.on.aws"},
                    "UserPoolId": {"Value": "us-east-1_TESTPOOL"}},
    }
    boto3.client("cloudformation").create_stack(StackName="JobMeCloud", TemplateBody=json.dumps(template))


def test_migrate_deployed_migrates_the_clusters_database(deployed):
    engine, migrate = MagicMock(), MagicMock(return_value=["job", "run"])
    make_engine = MagicMock(return_value=engine)
    changes = migrate_deployed("JobMeCloud", make_engine=make_engine, migrate=migrate)
    make_engine.assert_called_once_with("dsql://abc123.dsql.us-east-1.on.aws")
    migrate.assert_called_once_with(engine)
    assert changes == ["job", "run"]
    engine.dispose.assert_called_once()


def test_pool_id_comes_from_the_stack_outputs(deployed):
    assert pool_id_from_stack("JobMeCloud") == "us-east-1_TESTPOOL"


def test_missing_stack_says_to_deploy_first():
    with pytest.raises(LookupError, match="cdk deploy"):
        pool_id_from_stack("JobMeCloud")


def test_create_owner_still_takes_an_explicit_pool_id():
    pool = boto3.client("cognito-idp").create_user_pool(PoolName="x")["UserPool"]["Id"]
    create_owner("o@example.com", pool)
