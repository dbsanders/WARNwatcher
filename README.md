# WARNwatcher

Cloud-native AWS starter project to ingest WARN notices (starting with California XLSX), normalize and store them, match against user watchlists, and send SES email alerts.

## Architecture

- EventBridge Scheduler (`aws_scheduler_schedule`) invokes `ingest` Lambda on a schedule.
- `ingest` Lambda:
  - `HEAD` checks WARN source (`ETag` / `Last-Modified`).
  - Compares with `warn_source_state` DynamoDB.
  - If changed (or forced), downloads XLSX, stores raw file in versioned S3.
  - Parses and normalizes notices.
  - Conditionally inserts into `warn_notices` using `notice_id` hash.
  - Publishes new notice events to SNS.
- SNS triggers `match_notify` Lambda:
  - Loads enabled watchlists from DynamoDB.
  - Matches notices using regex (case-insensitive), state, and min employees.
  - Sends email via SES.
  - Writes dedupe record in `notifications`.

## Repo Layout

- `infra/` Terraform
- `lambda/ingest/` ingest Lambda
- `lambda/match_notify/` matcher/notify Lambda
- `scripts/` build + local parse test

## Prereqs

- Terraform `>= 1.5`
- AWS credentials configured (`aws configure` or environment)
- Python `3.11`
- `pip`
- `zip` command (or use PowerShell script on Windows)

## Build Lambda zips

PowerShell (Windows):
```powershell
./scripts/build_lambdas.ps1
