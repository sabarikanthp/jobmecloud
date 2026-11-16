# What JobMeCloud costs

**AWS: about $0 to $2 a month** for one person, mostly inside free allowances. **The AI provider is the real cost**, and you control it.

Prices change. The figures below were checked against AWS's own pricing pages on 2026-11-15 where a link says so; everything else is an estimate. Re-check the pages before relying on them.

## AWS, per service

Assumptions: one user, a few hundred web requests a month, a couple of search runs a week, a handful of emails.

| Service | What it does here | Free allowance | Typical bill |
|---|---|---|---|
| **Lambda** | Runs the web API and the search and document workers | 1 million requests and 400,000 GB-seconds a month ([pricing](https://aws.amazon.com/lambda/pricing/)) | $0 |
| **Aurora DSQL** | The database | 100,000 DPUs and 1 GB a month, always free; $8 per million DPUs after ([pricing](https://aws.amazon.com/rds/aurora/dsql/pricing/)) | $0 |
| **Cognito** (Essentials) | Sign-in with MFA | First 10,000 monthly users free ([pricing](https://aws.amazon.com/cognito/pricing/)) | $0 |
| **API Gateway** (HTTP API) | Checks your sign-in token, passes requests on | 1 million calls a month for the first 12 months of an account; about $1 per million after ([pricing](https://aws.amazon.com/api-gateway/pricing/)) | $0, then cents |
| **CloudFront** | Serves the website over HTTPS | See the [pricing page](https://aws.amazon.com/cloudfront/pricing/) for the current free allowance | Cents at most |
| **S3** | The website files and your resumes and documents | Small allowance for new accounts ([pricing](https://aws.amazon.com/s3/pricing/)) | A few cents |
| **SES** | Sign-in and MFA emails (and digests in a later stage) | None for most accounts; $0.10 per 1,000 emails ([pricing](https://aws.amazon.com/ses/pricing/)) | Under $0.01 |
| **Parameter Store** (SSM) | Your encrypted API keys | Standard parameters are free ([pricing](https://aws.amazon.com/systems-manager/pricing/)) | $0 |
| **EventBridge Scheduler** | Starts the automatic searches | Millions of invocations a month ([pricing](https://aws.amazon.com/eventbridge/pricing/)) | $0 |
| **CloudWatch** | Lambda logs, kept 14 days | A small ingestion allowance ([pricing](https://aws.amazon.com/cloudwatch/pricing/)) | $0 to cents |
| **AWS Budgets** | Your spending alert | The first two budgets are free ([pricing](https://aws.amazon.com/aws-cost-management/pricing/)) | $0 |

Verified on 2026-11-15: Lambda, Aurora DSQL, Cognito, API Gateway and SES figures. CloudFront changed its plans recently, so check it yourself.

Nothing here has a fixed monthly fee: there is no server, no NAT gateway, no database instance and no load balancer. If you stop using JobMeCloud, the cost drops to nearly zero without you turning anything off.

## The AI provider (the real cost)

You pay your AI provider directly for the model calls that read postings, score them and write documents. A search run reads up to 40 postings. The cost depends on the model you pick and how many runs you do. The Today screen shows roughly what each run cost.

Control it in **Settings**:

- **Spending limit per run** (default $2): a run stops spending when it reaches the limit.
- **Searches per run** (default 20) and **applications per run** (default 10).
- Choose cheaper models for the reading and scoring steps.

Estimate your monthly total as: runs per month x the cost shown on Today.

## Set a spending alert

The stack creates a **$5 monthly budget** that emails the `owner_email` you gave when you deployed, at 80% of actual spend and when the forecast passes 100%. [deploy.md](deploy.md) also has you create a first budget by hand before deploying. Change the amount in **Billing and Cost Management > Budgets**.

A budget alerts you, it does not stop spending. If you see an alert you did not expect, open **Cost Explorer**, group by service, and look at what grew. The most likely cause is the AI provider, which is billed outside AWS.

## Emailed reports (optional)

If you use [email-ingest.md](email-ingest.md), SES charges a very small amount per received email, and the AI provider charges for one small call to read each report plus one per role. This usually replaces the much larger cost of a paid web search per run.

## Things that would add cost

- Using a custom domain (about $0.50 a month for a Route 53 zone). The default `*.cloudfront.net` address is free.
- Turning on SMS two-step verification. It is not offered: SMS is billed per message and needs extra setup.
- Moving SES out of the sandbox and sending a lot of email.
- Leaving the stack deployed after you stop using it is nearly free, but not exactly zero (stored files, logs).
