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

You pay your AI provider directly for the model calls that read postings, score them and write documents. The cost depends on the model you pick and how you start runs. The Today screen shows roughly what each run cost (the app's own estimate from the token counts and the price table in Settings; your provider's usage page has the real figure).

**What it cost in practice** (measured on a real account, with Anthropic models):

| How the run started | Typical cost |
|---|---|
| AI web search (the model searches the web and reads pages) | **$0.70 to $2.10 per run.** Almost all of it is input tokens: the search results are large and are re-read at each step inside one provider call |
| An emailed report (another tool did the searching; JobMeCloud reads, checks and scores each role, and writes documents for the best) | **About $0.07** for a report naming one role |

A subscription to a chat assistant does not help here: it is a separate product from the API key JobMeCloud uses, which is billed per token. If you already have a tool that does your searching on a flat plan, such as a ChatGPT scheduled task, [emailed reports](email-ingest.md) let you keep that and use JobMeCloud for everything after the search: the task searches and emails its report, and JobMeCloud reads, scores and writes documents.

Control it in **Settings**:

- **Spending limit per run** (default $2): a run stops spending when it reaches the limit. It is checked between AI calls, so one web-search call can overshoot it (one run was measured at $2.06 against a $2 limit).
- **Searches per run** (default 20; around 6 costs far less) and **applications per run** (default 10).
- Choose cheaper models for the reading and scoring steps.

Estimate your monthly total as: runs per month x the cost shown on Today.

## Set a spending alert

The stack creates a **$5 monthly budget** that emails the `owner_email` you gave when you deployed, at 80% of actual spend and when the forecast passes 100%. [deploy.md](deploy.md) also has you create a first budget by hand before deploying. Change the amount in **Billing and Cost Management > Budgets**.

A budget alerts you, it does not stop spending. If you see an alert you did not expect, open **Cost Explorer**, group by service, and look at what grew. The most likely cause is the AI provider, which is billed outside AWS.

## Emailed reports (optional)

If you use [email-ingest.md](email-ingest.md), SES charges a very small amount per received email, and the AI provider charges for one small call to read each report plus one per role. This usually replaces the much larger cost of a paid web search per run.

## Checking a job

Checking a job you pasted makes two small AI calls, one to read it and one to judge the fit, usually a cent or two together. The cost is shown beside each fit and recorded in the job's history. A stronger model costs more; the default is your scoring model. See [check-a-job.md](check-a-job.md).

## Things that would add cost

- Using your own web address. The certificate and the CloudFront hostname are free, and so are Cloudflare's DNS records. A domain name costs roughly a dozen dollars a year if you do not already own one, and hosting its DNS in Route 53 is about $0.50 a month. The default `*.cloudfront.net` address is free.
- Turning on SMS two-step verification. It is not offered: SMS is billed per message and needs extra setup.
- Moving SES out of the sandbox and sending a lot of email.
- Leaving the stack deployed after you stop using it is nearly free, but not exactly zero (stored files, logs).
