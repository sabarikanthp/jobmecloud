import boto3
import pytest

from jobmecloud.admin.owner import OwnerNotFound, create_owner, reset_owner

EMAIL = "owner@example.com"


@pytest.fixture
def pool_id():
    cognito = boto3.client("cognito-idp")
    return cognito.create_user_pool(PoolName="jobmecloud-test")["UserPool"]["Id"]


def get_user(pool_id):
    return boto3.client("cognito-idp").admin_get_user(UserPoolId=pool_id, Username=EMAIL)


def attrs(user):
    return {a["Name"]: a["Value"] for a in user["UserAttributes"]}


def test_create_owner_creates_confirmed_email_user(pool_id):
    create_owner(EMAIL, pool_id)
    user = get_user(pool_id)
    assert attrs(user)["email"] == EMAIL and attrs(user)["email_verified"] == "true"
    assert user["UserStatus"] == "FORCE_CHANGE_PASSWORD"


def test_create_owner_idempotent(pool_id):
    create_owner(EMAIL, pool_id)
    create_owner(EMAIL, pool_id)
    users = boto3.client("cognito-idp").list_users(UserPoolId=pool_id)["Users"]
    assert len(users) == 1


def test_reset_owner_recreates_user_with_forced_password_change(pool_id):
    create_owner(EMAIL, pool_id)
    before = attrs(get_user(pool_id))["sub"]
    boto3.client("cognito-idp").admin_set_user_password(
        UserPoolId=pool_id, Username=EMAIL, Password="Perm4nent!Pass", Permanent=True)
    assert get_user(pool_id)["UserStatus"] == "CONFIRMED"
    reset_owner(EMAIL, pool_id)
    user = get_user(pool_id)
    assert user["UserStatus"] == "FORCE_CHANGE_PASSWORD"
    assert attrs(user)["sub"] != before
    assert not user.get("UserMFASettingList")


def test_reset_owner_unknown_user_errors_clearly(pool_id):
    with pytest.raises(OwnerNotFound, match="create_owner"):
        reset_owner("nobody@example.com", pool_id)
