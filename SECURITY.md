# Security policy

JobMeCloud runs in your own AWS account and handles your resume, job history and API keys, so security reports are taken seriously. It is a personal open-source project, maintained on a best-effort basis: there is no guaranteed response time.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Use GitHub's private reporting instead: open the repository's **Security** tab and choose **Report a vulnerability**. Describe what you did, what you expected and what happened. Do not include real personal data, resumes, API keys, AWS account numbers or access keys; made-up examples are enough.

If private reporting is not available to you, open an issue that says only that you have a security report and no details, and the maintainer will arrange a private channel.

## What is in scope

The code and infrastructure in this repository: the web app and API, the Lambda functions, the CDK stack, the optional email-ingest path, and the helper scripts. [docs/security.md](docs/security.md) explains where data lives, who can reach it and what leaves your account, which helps when judging whether something is a vulnerability.

Things that are **not** vulnerabilities in this project:

- Anyone with administrator access to your own AWS account being able to read your data (documented as a limit).
- Problems in AWS, Cognito, SES or your AI provider themselves; report those to the provider.
- Findings that need a stranger to already hold your password and your second factor.

## Supported versions

Only the latest commit on `main` is supported. Fixes are made there; there are no maintained older releases.

## If you think a key has leaked

Revoke the key at your AI provider first, then follow [docs/security.md](docs/security.md#if-an-api-key-leaks). This is the step that matters.
