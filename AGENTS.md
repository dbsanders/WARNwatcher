# WARNwatcher project guidance

## Project and layout

Serverless WARN-notice ingestion, company watchlists, and SES email alerts. Read `README.md` for the current API and deployment flow.

- Python handlers: `lambda/ingest/`, `lambda/match_notify/`, `lambda/monthly_digest/`, and `lambda/watchlist_api/`.
- Static browser UI: `frontend/`; packaging/deployment helpers: `scripts/`.
- Main Terraform stack: `infra/`. `infra/bootstrap/` is legacy rollback history: do not apply or destroy it.

## Preserve these behaviors

- Keep source ingestion and outgoing alerts deduplicated; retries must not create duplicate notices or repeat notifications.
- Preserve email verification, password-reset protections, and user ownership checks when editing the custom-auth API. This project does not use MissingMoneyWatch's Cognito flow.
- Monthly digests list enabled subscriptions, grouped by subscriber. Preserve Pacific-time scheduling semantics.
- Keep build output in ignored `build/` and `dist/`; retain Terraform provider lock files.

## Checks and packaging

- Digest tests: `python3 scripts/test_monthly_digest.py` from the repository root; AWS clients are mocked.
- `scripts/test_parse_ca.py` is a parser smoke helper, not an isolated unit suite: importing ingest initializes AWS clients and requires its environment variables. Inspect it and use isolated dummy configuration/mocks before running locally.
- Check changed browser JavaScript with `node --check <file>` and inspect affected pages in a browser.
- Build Lambda ZIPs with `bash scripts/build_lambdas.sh` when packaging changes; this rebuilds `build/` and `dist/` and installs handler dependencies.
- Frontend deployment is separate from Terraform: `scripts/deploy_frontend.sh` uploads assets and invalidates CloudFront. Use it only for an authorized deployment with the explicit production profile.

## Working agreements

- Suggest useful features when coding and ask when intended direction is unclear.
- Preserve unrelated user changes. Never commit credentials, SSO caches, Terraform state, `.terraform/`, or secret variable files.

## AWS and Terraform

These rules are included here so this repository and its worktrees do not depend on a parent-directory instructions file.

- Production profile: `warnwatcher-prod`; expected account: `591132358443`; primary region: `us-west-2`. Choose credentials from this project, never from the open Console tab or default profile.
- Terraform root: `infra`. Read its backend configuration and deployment documentation before initialization. Use its dedicated remote state; do not invent a backend or silently switch to local state.
- Before Terraform commands that inspect/change remote state or AWS resources, explicitly set `AWS_PROFILE=warnwatcher-prod`, `AWS_REGION=us-west-2`, and `AWS_DEFAULT_REGION=us-west-2`, run `aws sts get-caller-identity`, and compare `Account` with `591132358443`. Stop on mismatch. If SSO expired, run `aws sso login --profile warnwatcher-prod` and repeat the check.
- Keep the profile explicit on AWS/Terraform invocations. Preserve configured provider region overrides, such as `us-east-1` for CloudFront certificates where present.
- Do not use `[default]`, legacy `warnwatcher`, or `grammy-cookbook` profiles. Use sandbox account `029939160999` only when explicitly requested. Shared AWS Organizations/bootstrap work belongs to the separate account-infrastructure project.
- Run `terraform fmt -check`, `terraform validate`, and `terraform plan` in the relevant root before applying, when applicable. Inspect the full plan and call out replacements, deletions, IAM, DNS, and public-access changes.
- Apply only when the task authorizes the change. Do not use `-auto-approve` unless unattended application was explicitly requested. Re-plan after applying; a completed deployment should normally have no pending changes.
- Stop on missing backend configuration or unexpected state. Before moving/importing/deleting/recreating resources, identify their account, Terraform addresses, dependencies, migration needs, and rollback implications. Prefer importing existing resources when appropriate; remove old cross-account copies only after authorized cleanup.
- Use IAM Identity Center/SSO, not long-lived IAM user keys. Console and CLI sessions are independent; routine Console work uses the project account's `TerraformAdministrator` role, not root credentials.
