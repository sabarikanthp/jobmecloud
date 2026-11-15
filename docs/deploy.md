# Deploy JobMeCloud

This guide takes you from nothing to a working site in your own AWS account. It assumes you are comfortable copying commands into a terminal, but not that you know AWS. Plan about an hour the first time. Most of it is waiting for AWS.

If anything goes wrong, see [troubleshooting.md](troubleshooting.md). If you ever lose your password or phone, see [account-recovery.md](account-recovery.md). For what this costs, see [costs.md](costs.md).

## 1. Create an AWS account

1. Go to <https://aws.amazon.com/> and choose **Create an AWS account**. You need an email address, a payment card and a phone that can receive a verification code. Pick the free **Basic support** plan.
2. Sign in once as the **root user** (the email and password you just created) and turn on **two-step verification** for it: top-right account menu, **Security credentials**, **Multi-factor authentication**. Then stop using the root user. It can do everything, including close the account, so it should be locked away. Everything below uses a normal admin user instead.

## 2. Set a billing alert

Do this before you deploy anything. In the console open **Billing and Cost Management**, then **Budgets**, then **Create budget**, choose **Monthly cost budget**, set **$5**, and enter your email for alerts. (The stack also creates its own $5 budget, so this is a second safety net while you set up. See [costs.md](costs.md).)

## 3. Create an admin user (not the root user)

The recommended way is **IAM Identity Center**, which gives you short-lived logins instead of permanent keys:

1. In the console, search for **IAM Identity Center** and choose **Enable**.
2. Create a **user** with your email, then create a **permission set** called `AdministratorAccess` (use the predefined policy of that name), and assign the user to your account with that permission set.
3. Open the invitation email, set a password and register an authenticator app.

Guide: <https://docs.aws.amazon.com/singlesignon/latest/userguide/getting-started.html>

If you would rather use a classic IAM user: create a user with the `AdministratorAccess` policy, turn on MFA for it, and create an access key. Keys do not expire, so keep them out of files and chat.

## 4. Install the tools

| Tool | Why | Install |
|---|---|---|
| AWS CLI v2 | Talks to your account | <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html> |
| uv | Installs Python 3.12 and the project's packages | <https://docs.astral.sh/uv/getting-started/installation/> |
| Node.js (current LTS) | Builds the website and runs the AWS CDK | <https://nodejs.org/> |
| AWS CDK | Creates the AWS resources | `npm install -g aws-cdk` |

Check them: `aws --version` (must say `aws-cli/2`), `uv --version`, `node --version`, `cdk --version`.

## 5. Sign the CLI in to your account

With IAM Identity Center:

```
aws configure sso
aws sso login --profile <the profile name you chose>
export AWS_PROFILE=<the profile name you chose>
```

On Windows PowerShell use `$env:AWS_PROFILE = "<name>"`. With an IAM user, run `aws configure` and paste the key.

Check it worked: `aws sts get-caller-identity` should print your account number.

## 6. Choose a region

Pick one region and use it for everything: set `AWS_REGION` (for example `us-east-1`) and `AWS_DEFAULT_REGION` to the same value. JobMeCloud uses Aurora DSQL, Cognito, SES, CloudFront and Lambda, so the region must offer all of them. `us-east-1` (N. Virginia) is a safe default. Check the list at <https://aws.amazon.com/about-aws/global-infrastructure/regional-product-services/> if you want another.

## 7. Get the code

```
git clone https://github.com/<your-fork-or-the-project>/jobmecloud.git
cd jobmecloud
uv sync
cd frontend && npm install && cd ..
```

## 8. Verify your email address with SES

AWS only sends email from addresses you have verified, and a new account starts in the SES **sandbox**, where it can also only send *to* verified addresses. That is exactly what you want here: the only email goes to you.

1. In the console, in your chosen region, open **Amazon SES**, then **Identities**, then **Create identity**.
2. Choose **Email address**, enter the address you will sign in with, and create it.
3. Open the email AWS sends and click the link. The identity must say **Verified** before you continue.

Sign-in invitations and MFA codes are sent from this address. If you use a different address for sending (`sender_email` below), verify that one too.

## 9. Bootstrap the CDK (once per account and region)

```
cdk bootstrap
```

If it asks for the account and region, use `aws://<your account number>/<your region>`. This creates a small bucket the CDK uses for deployments.

## 10. Build and deploy

```
uv run python scripts/build_lambdas.py
cdk deploy -c owner_email=you@example.com -c sender_email=you@example.com -c timezone=America/Chicago
```

- `owner_email` gets the spending alerts. `sender_email` is the verified SES address. They can be the same.
- `timezone` is your own time zone as an IANA name (for example `Europe/London`, `Asia/Kolkata`). Searches rotate employers by weekday, and your schedule runs in this zone. The default is `UTC`.
- The first deploy takes about ten minutes. CDK lists what it will create and asks you to confirm. When it finishes it prints outputs, including `SiteUrl`, `UserPoolId` and `DatabaseEndpoint`. The scripts below read them for you.
- AWS Budgets emails you to confirm the alert address. Click that link.

## 11. Create the database tables

```
uv run python scripts/migrate_db.py
```

Expected: `Created or changed: job, run, ...`. Run it again after every update.

## 12. Create your sign-in

```
uv run python scripts/create_owner.py --email you@example.com
```

Cognito emails you a temporary password. There is no public sign-up, so this is the only way in.

## 13. Publish the website

```
cd frontend && npm run build && cd ..
uv run python scripts/publish_site.py
```

It prints your site address (the `SiteUrl`).

## 14. Sign in and set up two-step verification

1. Open the site address. You are sent to the sign-in page.
2. Sign in with your email and the temporary password, then choose a new password (12 characters or more).
3. You must set up a second step. Choose an **authenticator app** (Google Authenticator, Microsoft Authenticator, 1Password, Authy and others all work): scan the code and type the six digits. You can also choose an **email code**. Set up both if you can: either one gets you back in if you lose the other. Save your authenticator's recovery codes if it offers them.
4. You land in the JobMeCloud setup guide.

Read [account-recovery.md](account-recovery.md) now, once, so you know what to do if you ever lose your phone.

## 15. Connect an AI and run your first search

Follow the setup guide in the app. In the **Connect an AI** step choose Anthropic (or an OpenAI-compatible service), paste your **API key**, and press **Test**. The key is stored in your account's Parameter Store as an encrypted value and is never shown again. Then add your resume, say what you are looking for, and press **Run now** on the **Today** screen. A first search takes a few minutes.

Searches need a web-search source. With Anthropic the built-in web search is used. With other providers, add a Tavily or Brave search key in Settings.

Set the **spending limit per run** in Settings (the default is $2) so one run can never cost more than you expect.

## You are done

Updating later is covered in [operations.md](operations.md). Questions or fixes are welcome: see [CONTRIBUTING.md](../CONTRIBUTING.md).
