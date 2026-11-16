"""Sign-in: one Cognito account, password plus required MFA (authenticator app or email code).

No self sign-up, no Google, no SMS. Cognito's Essentials plan includes email MFA and is free for the first
10,000 monthly users. Password reset by email is off (the email address is an MFA factor), so recovery is the
`reset_owner` script, described in docs/account-recovery.md.
"""

from aws_cdk import Duration, RemovalPolicy
from aws_cdk import aws_cognito as cognito
from constructs import Construct


class Auth(Construct):
    def __init__(self, scope: Construct, id: str, *, sender_email: str, account: str, region: str) -> None:
        super().__init__(scope, id)

        self.user_pool = cognito.UserPool(
            self, "UserPool",
            user_pool_name="jobmecloud",
            self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=False)),
            feature_plan=cognito.FeaturePlan.ESSENTIALS,
            mfa=cognito.Mfa.REQUIRED,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False, email=True),
            account_recovery=cognito.AccountRecovery.NONE,
            email=cognito.UserPoolEmail.with_ses(from_email=sender_email, from_name="JobMeCloud", ses_region=region),
            password_policy=cognito.PasswordPolicy(min_length=12),
            user_invitation=cognito.UserInvitationConfig(
                email_subject="Your JobMeCloud sign-in",
                email_body="Sign in with {username} and the temporary password {####}. "
                           "You will choose a new password and set up two-step verification.",
            ),
            deletion_protection=True,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # The browser app: authorization-code flow, no client secret. Task 8 adds the real site address.
        self.spa_client = self.user_pool.add_client(
            "SpaClient",
            generate_secret=False,
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL],
                callback_urls=["http://localhost:5173/"],
                logout_urls=["http://localhost:5173/"],
            ),
            supported_identity_providers=[cognito.UserPoolClientIdentityProvider.COGNITO],
            prevent_user_existence_errors=True,
            access_token_validity=Duration.hours(1),
            id_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
        )

        self.domain = self.user_pool.add_domain(
            "LoginDomain",
            cognito_domain=cognito.CognitoDomainOptions(domain_prefix=f"jobmecloud-{account}"),
            managed_login_version=cognito.ManagedLoginVersion.NEWER_MANAGED_LOGIN,
        )
        cognito.CfnManagedLoginBranding(
            self, "LoginBranding",
            user_pool_id=self.user_pool.user_pool_id,
            client_id=self.spa_client.user_pool_client_id,
            use_cognito_provided_values=True,
        )
