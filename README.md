# WARNwatcher

Cloud-native AWS starter project to ingest WARN notices (starting with California XLSX), normalize and store them, match against watchlists, and send SES email alerts.

## Architecture

- EventBridge Scheduler (`aws_scheduler_schedule`) triggers ingest on schedule.
- `ingest` Lambda checks source headers (`ETag` / `Last-Modified`), stores raw files in S3, parses XLSX, normalizes notices, writes deduped notices to DynamoDB, and emits new-notice events to SNS.
- `match_notify` Lambda consumes SNS events, evaluates watchlists, sends SES emails, and records sent notifications for dedupe.
- `monthly_digest` Lambda runs at 9:00 AM Pacific on the first day of each month and emails every subscriber an alphabetized list of their enabled company subscriptions.
- `watchlist_api` Lambda is exposed via API Gateway HTTP API (`POST /signup`, `POST /verify-email`, `POST /resend-verification`, `POST /login`, `POST /forgot-password`, `POST /reset-password`, `POST /subscribe`, `GET /subscriptions`, `GET /notices`, `PUT /subscriptions/{watch_id}`, `DELETE /subscriptions/{watch_id}`) for account auth and watchlist management.
- Static frontend is served from S3 through CloudFront.

## Repo Layout

- `infra/` main Terraform stack (app infrastructure).
- `infra/bootstrap/` one-time Terraform stack for remote state backend (S3 + DynamoDB lock table).
- `lambda/ingest/` ingest Lambda.
- `lambda/match_notify/` matcher/notify Lambda.
- `lambda/monthly_digest/` monthly subscriber summary Lambda.
- `lambda/watchlist_api/` API Lambda for watchlist signup.
- `frontend/` static web app.
- `scripts/` build and helper scripts.

## Prereqs

- Terraform `>= 1.5`
- AWS CLI configured (`aws configure`)
- Python `3.11`
- `pip`
- `zip`

## Build Lambda Artifacts

WSL / Bash:
```bash
bash scripts/build_lambdas.sh
```

## Remote State (shared account S3 backend)

WarnWatcher uses the account-level state bucket managed in `/Users/bret/Development/aws-account-infra`. Its independent state key is `warnwatcher/prod/terraform.tfstate`, with native S3 locking enabled.

### Configure the main stack backend

Create `infra/backend.hcl` from `infra/backend.hcl.example`:

```hcl
bucket       = "terraform-state-<aws_account_id>-us-west-2"
key          = "warnwatcher/prod/terraform.tfstate"
region       = "us-west-2"
encrypt      = true
use_lockfile = true
```

Initialize the main stack:

```bash
AWS_PROFILE=warnwatcher-prod terraform -chdir=infra init -backend-config=backend.hcl
```

The legacy `infra/bootstrap` stack is retained only for rollback history and must not be applied or destroyed.

## Deploy Main Stack

Copy the production domain setting on a fresh checkout:

```bash
cp infra/terraform.tfvars.example infra/terraform.tfvars
```

```bash
AWS_PROFILE=warnwatcher-prod terraform -chdir=infra apply
```

## Domain + Cloudflare Notes

- Certificates are created in ACM and DNS validation records are exposed as outputs:
  - `web_certificate_dns_validation_records`
  - `api_certificate_dns_validation_records`
- Add those records in Cloudflare first, wait for cert issuance, then set:
  - `enable_custom_domains = true`
- Use output `cloudflare_dns_targets` to create CNAME/flattened records for apex, `www`, and `api`.
- For a cross-account CloudFront migration, keep these DNS-only ownership records pointed at the target distribution until the aliases are attached:
  - `_.warnwatcher.com` TXT `<cloudfront_distribution_domain_name>`
  - `_www.warnwatcher.com` TXT `<cloudfront_distribution_domain_name>`

## Frontend Deploy

After Terraform apply, upload `frontend/` to the website bucket and invalidate CloudFront:

```bash
AWS_PROFILE=warnwatcher-prod bash scripts/deploy_frontend.sh <web_bucket_name> <cloudfront_distribution_id>
```

## Pause / Resume Signup API

Temporarily block public signups (without deleting infrastructure):

```bash
AWS_PROFILE=warnwatcher-prod bash scripts/toggle_watchlist_api.sh disable
```

Re-enable:

```bash
AWS_PROFILE=warnwatcher-prod bash scripts/toggle_watchlist_api.sh enable
```

## SES Setup

1. Verify sender identity for `alert_sender_email` in SES.
2. If SES is in sandbox, verify recipient identities.
3. Request SES production access when ready.

## Auth + Watchlist API (AWS CLI)

Create an account:

```bash
curl -X POST "https://api.warnwatcher.com/signup" \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"change-me-123"}'
```

Signup sends a one-time verification link that expires after 24 hours. Opening it verifies the email and signs the user in. Unverified accounts cannot use password login. A new link can be requested with:

```bash
curl -X POST "https://api.warnwatcher.com/resend-verification" \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com"}'
```

Sign in and capture `access_token` from the response:

```bash
curl -X POST "https://api.warnwatcher.com/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"change-me-123"}'
```

Request a password reset email:

```bash
curl -X POST "https://api.warnwatcher.com/forgot-password" \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com"}'
```

Reset password with token from reset link:

```bash
curl -X POST "https://api.warnwatcher.com/reset-password" \
  -H "Content-Type: application/json" \
  -d '{"token":"<reset_token>","password":"new-password-123"}'
```

Create a watchlist using the bearer token:

```bash
curl -X POST "https://api.warnwatcher.com/subscribe" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"company":"Acme","state":"CA","min_employees":25}'
```

`/subscribe` also checks existing notices immediately and returns `existing_match_count` plus sample `existing_matches`. If matches are found, WARNwatcher sends an immediate email alert (deduped per `notice_id` + `user_id`).

List your subscriptions:

```bash
curl -X GET "https://api.warnwatcher.com/subscriptions" \
  -H "Authorization: Bearer <access_token>"

List current WARN notices:

```bash
curl -X GET "https://api.warnwatcher.com/notices" \
  -H "Authorization: Bearer <access_token>"
```
```

Update a subscription:

```bash
curl -X PUT "https://api.warnwatcher.com/subscriptions/<watch_id>" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <access_token>" \
  -d '{"company":"Acme Logistics","state":"CA","min_employees":50,"is_enabled":true}'
```

Delete a subscription:

```bash
curl -X DELETE "https://api.warnwatcher.com/subscriptions/<watch_id>" \
  -H "Authorization: Bearer <access_token>"
```

## Add Watchlists (Direct DynamoDB)

```bash
aws dynamodb put-item \
  --table-name WARNwatcher-watchlists \
  --item '{
    "user_id": {"S":"user-123"},
    "watch_id": {"S":"watch-001"},
    "email": {"S":"bret@cybersand.com"},
    "patterns": {"L":[{"S":"Acme"},{"S":"Logistics"}]},
    "states": {"L":[{"S":"CA"}]},
    "min_employees": {"N":"25"},
    "is_enabled": {"BOOL":true}
  }'
```

## Manual Ingest Trigger

```bash
aws lambda invoke \
  --function-name WARNwatcher-ingest \
  --payload '{"force": true}' \
  out.json
cat out.json
```

## Notes

- `infra/.terraform.lock.hcl` should be committed.
- `build/` and `dist/` are build artifacts and are ignored.
- Keep `infra/backend.hcl` local to each environment and do not commit it.
