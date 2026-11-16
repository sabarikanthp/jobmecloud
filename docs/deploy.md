# Deploy JobMeCloud

This guide takes you from nothing to a working site in your own AWS account. It assumes you are comfortable copying commands into a terminal, but not that you know AWS. Plan about an hour the first time. Most of it is waiting for AWS.

If anything goes wrong, see [troubleshooting.md](troubleshooting.md). If you ever lose your password or phone, see [account-recovery.md](account-recovery.md). For what this costs, see [costs.md](costs.md).

## 1. Create an AWS account

1. Go to <https://aws.amazon.com/> and choose **Create an AWS account**. You need an email address, a payment card and a phone that can receive a verification code. Pick the free **Basic support** plan.
2. Sign in once as the **root user** (the email and password you just created) and turn on **two-step verification** for it: top-right account menu, **Security credentials**, **Multi-factor authentication**. Then stop using the root user. It can do everything, including close the account, so it should be locked away. Everything below uses a normal admin user instead.

## 2. Set a billing alert

Do this before you deploy anything. In the console open **Billing and Cost Management**, then **Budgets**, then **Create budget**, choose **Monthly cost budget**, set **$5**, and enter your email for alerts. Click the confirmation link AWS emails you (check spam and, on Gmail, the Promotions tab). The stack also creates its own $5 budget, so once it is deployed you can delete this hand-made one. AWS gives you two budgets free; if you have other projects in the account, count them first ([costs.md](costs.md)).

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
| Git | Gets the code | <https://git-scm.com/downloads> |
| AWS CLI v2 | Talks to your account | <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html> |
| uv | Installs Python 3.12 and the project's packages | <https://docs.astral.sh/uv/getting-started/installation/> |
| Node.js 22 or 24 (LTS) | Builds the website and runs the AWS CDK. A newer Node works, but the CDK prints a warning that it has not been tested with it | <https://nodejs.org/> |
| AWS CDK | Creates the AWS resources | `npm install -g aws-cdk` |

Check them: `git --version`, `aws --version` (must say `aws-cli/2`), `uv --version`, `node --version`, `cdk --version`. You do not install Python yourself: `uv` fetches Python 3.12 and every package the project needs.

**Windows notes.** If `aws --version` says `aws-cli/1`, an old copy is earlier on your PATH. Open a new terminal, or call the new one by its full path (`C:\Program Files\Amazon\AWSCLIV2\aws.exe`). If the installer fails with error 1618, another install is running: wait for it or restart. In **Git Bash**, an argument that starts with `/` (such as a Parameter Store name like `/jobmecloud/...`) is rewritten into a Windows path; run `export MSYS_NO_PATHCONV=1` first, or use PowerShell.

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

Pick one region and use it for everything: set `AWS_REGION` (for example `us-east-1`) and `AWS_DEFAULT_REGION` to the same value. JobMeCloud uses Aurora DSQL, Cognito, SES, CloudFront and Lambda, so the region must offer all of them. `us-east-1` (N. Virginia) is a safe default. Check the list at <https://aws.amazon.com/about-aws/global-infrastructure/regional-product-services/> if you want another. If you plan to use [emailed reports](email-ingest.md), SES must also be able to *receive* email in that region (`us-east-1` can), and a CloudFront certificate for your own address must be requested in `us-east-1` whatever region you deploy to.

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
3. Open the email AWS sends and click the link (check spam and, on Gmail, Promotions). The identity must say **Verified** before you continue.

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
- Optional settings, each explained in its own section or guide: `site_domain` and `certificate_arn` (your own web address, see below), and `inbound_address`, `inbound_sender` and `inbound_daily_limit` (runs driven by an emailed report, see [email-ingest.md](email-ingest.md)). If you set any of them, set them again on every later deploy.
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

**Check the backend is live.** After the first sign-in (next step) open the **Jobs** page. If it shows an error, the running functions are older than your code: repeat `build_lambdas.py` and `cdk deploy`, then reload. The same rule applies after any code change.

## 14. Sign in and set up two-step verification

1. Open the site address. You are sent to the sign-in page.
2. Sign in with your email and the temporary password, then choose a new password (12 characters or more).
3. You must set up a second step. Choose an **authenticator app** (Google Authenticator, Microsoft Authenticator, 1Password, Authy and others all work): scan the code and type the six digits. You can also choose an **email code**. Set up both if you can: either one gets you back in if you lose the other. Save your authenticator's recovery codes if it offers them.
4. You land in the JobMeCloud setup guide.

Read [account-recovery.md](account-recovery.md) now, once, so you know what to do if you ever lose your phone.

## 15. Connect an AI and run your first search

Follow the setup guide in the app. In the **Connect an AI** step choose Anthropic (or an OpenAI-compatible service), paste your **API key**, and press **Test**. The key is stored in your account's Parameter Store as an encrypted value and is never shown again. Then add your resume, say what you are looking for, and press **Run now** on the **Today** screen. A first search takes a few minutes.

Searches need a web-search source. With Anthropic the built-in web search is used. With other providers, add a Tavily or Brave search key in Settings.

Set the **spending limit per run** in Settings (the default is $2). Know what a web-search run costs before you schedule one: the AI provider bills the web search by tokens, and one run can cost $1 to $2 even though it reads few postings, because the search results are large. The limit is checked between AI calls, so a single search call can finish a little over it. Lower **Searches per run** (for example to 6) to cut the cost, or skip web search entirely and use the cheaper alternative: **let a chat assistant do the searching and email you the result.** For example, a ChatGPT scheduled task runs your search daily on its own plan and emails its report to an address on your own domain; SES receives it; JobMeCloud reads the roles the report recommends, researches and scores each one itself, and writes documents for the best, for cents per report. The setup is in [email-ingest.md](email-ingest.md) (see "Example: let a ChatGPT scheduled task do the searching"); you can add it any time after your first deploy.

## Optional: use your own address

By default the site lives at a `*.cloudfront.net` address. To use your own hostname (for example `jobs.example.com`) you need a domain whose DNS you can edit (Cloudflare, Route 53, or any other provider). It costs nothing extra: AWS certificates and CloudFront hostnames are free.

1. **Request a certificate in `us-east-1`** (CloudFront only accepts certificates from there, whatever region you deployed to): in the console open **Certificate Manager**, switch to **N. Virginia**, choose **Request**, enter your hostname and pick **DNS validation**. Or run `aws acm request-certificate --domain-name jobs.example.com --validation-method DNS --region us-east-1`.
2. **Add the validation record** it shows (one CNAME) at your DNS provider. If you use Cloudflare, set it to **DNS only** (grey cloud). Wait until the certificate says **Issued**.
3. **Deploy with two extra settings:** `cdk deploy ... -c site_domain=jobs.example.com -c certificate_arn=<the certificate's ARN>`. Both are required together. Use the same two settings on every later deploy.
4. **Point the hostname at CloudFront:** add a CNAME for your hostname with the `DistributionDomain` value from the deploy output as its target (DNS only on Cloudflare).
5. Open `https://jobs.example.com/` and sign in. The `*.cloudfront.net` address keeps working too.

The sign-in page itself stays on its `amazoncognito.com` address; giving it your own hostname needs a second certificate and is not covered here.

## Prefer plain CloudFormation?

The infrastructure is written with the AWS CDK in [`infra/`](../infra). CDK turns it into a CloudFormation template for you: `cdk synth` writes it to `cdk.out/` (ignored by git, because it contains your account number). That template refers to the Lambda code CDK uploads to the bootstrap bucket, so it cannot be deployed on its own with the CloudFormation console. Use `cdk deploy`, or run `cdk synth` and read the template if you want to review what will be created.

## You are done

Want runs driven by an emailed daily report instead of paid searches? See [email-ingest.md](email-ingest.md). Coming from the local JobMe app? Bring your data across with [migrating-from-local.md](migrating-from-local.md). Updating later is covered in [operations.md](operations.md). Questions or fixes are welcome: see [CONTRIBUTING.md](../CONTRIBUTING.md).
