# WARNwatcher

Cloud-native AWS starter project to ingest WARN notices (starting with California XLSX), normalize and store them, match against watchlists, and send SES email alerts.

## Architecture

- EventBridge Scheduler (`aws_scheduler_schedule`) triggers ingest on schedule.
- `ingest` Lambda checks source headers (`ETag` / `Last-Modified`), stores raw files in S3, parses XLSX, normalizes notices, writes deduped notices to DynamoDB, and emits new-notice events to SNS.
- `match_notify` Lambda consumes SNS events, evaluates watchlists, sends SES emails, and records sent notifications for dedupe.

## Repo Layout

- `infra/` main Terraform stack (app infrastructure).
- `infra/bootstrap/` one-time Terraform stack for remote state backend (S3 + DynamoDB lock table).
- `lambda/ingest/` ingest Lambda.
- `lambda/match_notify/` matcher/notify Lambda.
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

PowerShell:
```powershell
./scripts/build_lambdas.ps1
```

## Remote State (S3 + DynamoDB)

### 1) Create backend resources (one-time)

```bash
terraform -chdir=infra/bootstrap init
terraform -chdir=infra/bootstrap apply
```

Capture outputs:

```bash
terraform -chdir=infra/bootstrap output -raw state_bucket_name
terraform -chdir=infra/bootstrap output -raw lock_table_name
terraform -chdir=infra/bootstrap output -raw backend_region
```

### 2) Configure main stack backend

Create `infra/backend.hcl` from `infra/backend.hcl.example`:

```hcl
bucket         = "<state_bucket_name>"
key            = "warnwatcher/terraform.tfstate"
region         = "us-west-2"
dynamodb_table = "<lock_table_name>"
encrypt        = true
```

### 3) Initialize main stack with remote backend

If local state exists and you want to migrate it:
```bash
terraform -chdir=infra init -backend-config=backend.hcl -migrate-state
```

If no local state should be kept:
```bash
terraform -chdir=infra init -backend-config=backend.hcl -reconfigure
```

## Deploy Main Stack

```bash
terraform -chdir=infra apply
```

## SES Setup

1. Verify sender identity for `alert_sender_email` in SES.
2. If SES is in sandbox, verify recipient identities.
3. Request SES production access when ready.

## Add Watchlists (AWS CLI)

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
