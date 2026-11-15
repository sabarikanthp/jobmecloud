# Account recovery

Read this once now, so a lost phone is an inconvenience and not a crisis.

**Short version:** you can get back in by yourself using the **email code** (if you set that up). If you cannot, the person who deployed the stack (you) runs one command with AWS admin access, and the system emails a new temporary password. Your jobs, resumes and settings are never lost, because they are not stored in the sign-in account.

## Why there is no "forgot password" link

JobMeCloud's sign-in uses your email address as one of its two-step factors (the **email code**). AWS Cognito will not let the same email address be both a second factor and the channel for resetting a password, because then anyone with your inbox could reset the password and pass the second step too. So self-service password reset is turned off on purpose. Recovery needs your AWS admin access instead, which is the stronger proof that the account is yours.

## What happened to you?

### I forgot my password

If you are still signed in on another device, there is no way to change a password from the app yet, so use the reset below. Otherwise:

1. Run the reset below (it needs your AWS admin sign-in, not your JobMeCloud password).
2. Cognito emails a new temporary password.
3. Sign in, choose a new password, and set up your second step again.

### I lost my phone or my authenticator app, but I can still read my email

Sign in with your email and password. When asked for the second step, choose **Email message** (or **Try another method**) and type the code sent to your inbox. You are in.

JobMeCloud has no account page, so you cannot add your authenticator app to a new phone from inside the app. Until you do, keep signing in with the email code. To start fresh with an authenticator on the new phone, use the reset below: it lets you choose your second steps again.

### I lost both my authenticator and my email access

This is the reset case. You must be able to sign in to your **AWS account** (see "Lost your AWS access too" if you cannot).

1. Open a terminal in the project folder and sign the AWS CLI in to your account (`aws sso login --profile <your profile>`, as in [deploy.md](deploy.md)).
2. Run, with your own address:

   ```
   uv run python scripts/reset_owner.py --email you@example.com
   ```

   It finds your user pool from the deployed stack. If it cannot, add `--pool-id <UserPoolId>` (shown in the deploy output and in the Cognito console).
3. The script deletes the sign-in account and creates it again. Cognito emails a **temporary password** to that address. The email has to be one you can read: SES sends it, and a new account sends only to verified addresses (see "Change the owner email").
4. Open the site, sign in with the temporary password, choose a new password, and set up your second step again.

Nothing else changes. Your jobs, contacts, resumes, documents, API keys and schedule stay exactly as they were.

### Lost your AWS access too

If you cannot sign in to AWS itself, JobMeCloud cannot help; AWS must restore your access. Start at <https://aws.amazon.com/support/> and choose the account and billing support option, which is free. Having a second AWS admin user (see the checklist below) avoids this.

### Change the owner email

The sign-in is tied to one email address and it cannot be edited in place. To move to a new address:

1. In **Amazon SES**, verify the new address (SES is in sandbox mode, so it can only send to verified addresses). If you also use it as the sender, pass it as `sender_email` and run `cdk deploy` again.
2. Run `uv run python scripts/create_owner.py --email new@example.com`.
3. Sign in as the new user and check everything is there.
4. Delete the old user in the **Cognito console** (User pools, your pool, Users).

## Prevent a lockout: a five-minute checklist

- [ ] Set up **both** second steps: an authenticator app **and** the email code. Either one rescues you from losing the other.
- [ ] Save the authenticator's recovery codes if the app offers them, in a password manager.
- [ ] Make sure you can always read the email inbox you signed up with.
- [ ] Keep a **second AWS admin user** (for example a partner you trust, or a second IAM Identity Center user), so losing one AWS login does not lock you out of the account.
- [ ] Keep your AWS root user's two-step verification device somewhere safe (you should almost never need it).
- [ ] Write down the stack name (default `JobMeCloud`) and the region you deployed to.

## See also

- [operations.md](operations.md) for updates and backups
- [troubleshooting.md](troubleshooting.md) if the email never arrives
- [security.md](security.md) for how sign-in is protected
