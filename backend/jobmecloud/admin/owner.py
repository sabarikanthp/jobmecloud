"""Create or reset the single sign-in account. Run by the person who deployed the stack, with AWS admin credentials."""

import boto3


class OwnerNotFound(Exception):
    pass


def _client(client):
    return client or boto3.client("cognito-idp")


def create_owner(email: str, pool_id: str, client=None) -> None:
    """Create the account. Cognito emails a temporary password; MFA is set up at first sign-in. Safe to repeat."""
    cognito = _client(client)
    try:
        cognito.admin_create_user(
            UserPoolId=pool_id, Username=email,
            UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}],
            DesiredDeliveryMediums=["EMAIL"],
        )
    except cognito.exceptions.UsernameExistsException:
        pass


def reset_owner(email: str, pool_id: str, client=None) -> None:
    """Recover a lost password or authenticator: replace the account and email a new temporary password.

    The account holds only the sign-in, so nothing in the app is lost. Cognito has no admin call that removes a
    registered authenticator, so the account is deleted and created again.
    """
    cognito = _client(client)
    try:
        cognito.admin_get_user(UserPoolId=pool_id, Username=email)
    except cognito.exceptions.UserNotFoundException:
        raise OwnerNotFound(
            f"No account for {email} in user pool {pool_id}. Run scripts/create_owner.py first."
        ) from None
    cognito.admin_delete_user(UserPoolId=pool_id, Username=email)
    create_owner(email, pool_id, cognito)
