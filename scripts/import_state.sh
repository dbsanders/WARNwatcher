#!/usr/bin/env bash
set -euo pipefail

PROJECT_NAME="${PROJECT_NAME:-WARNwatcher}"
REGION="${REGION:-us-west-2}"
BUCKET_NAME="${BUCKET_NAME:-}"
SUBSCRIPTION_ARN="${SUBSCRIPTION_ARN:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project-name)
      PROJECT_NAME="$2"
      shift 2
      ;;
    --region)
      REGION="$2"
      shift 2
      ;;
    --bucket-name)
      BUCKET_NAME="$2"
      shift 2
      ;;
    --subscription-arn)
      SUBSCRIPTION_ARN="$2"
      shift 2
      ;;
    *)
      echo "Unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="$REPO_ROOT/infra"

tf_import() {
  local address="$1"
  local import_id="$2"
  if terraform -chdir="$INFRA_DIR" state show "$address" >/dev/null 2>&1; then
    echo "Skipping $address (already in state)"
    return 0
  fi
  echo "Importing $address -> $import_id"
  terraform -chdir="$INFRA_DIR" import "$address" "$import_id"
}

terraform -chdir="$INFRA_DIR" init

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET_PREFIX="$(echo "$PROJECT_NAME" | tr '[:upper:]' '[:lower:]')-$ACCOUNT_ID-$REGION-"

if [[ -z "$BUCKET_NAME" ]]; then
  BUCKET_NAME="$(aws s3api list-buckets --query "Buckets[?starts_with(Name, '$BUCKET_PREFIX')].Name | [0]" --output text)"
fi

if [[ -z "$BUCKET_NAME" || "$BUCKET_NAME" == "None" ]]; then
  echo "Could not infer bucket name. Pass --bucket-name." >&2
  exit 1
fi

SUFFIX="${BUCKET_NAME##*-}"
TOPIC_NAME="$PROJECT_NAME-new-notice"
TOPIC_ARN="$(aws sns list-topics --region "$REGION" --query "Topics[?contains(TopicArn,':$TOPIC_NAME')].TopicArn | [0]" --output text)"

if [[ -z "$TOPIC_ARN" || "$TOPIC_ARN" == "None" ]]; then
  echo "Could not find SNS topic for $TOPIC_NAME." >&2
  exit 1
fi

MATCHER_LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${PROJECT_NAME}-match-notify"
if [[ -z "$SUBSCRIPTION_ARN" ]]; then
  SUBSCRIPTION_ARN="$(
    aws sns list-subscriptions-by-topic \
      --region "$REGION" \
      --topic-arn "$TOPIC_ARN" \
      --query "Subscriptions[?Endpoint=='${MATCHER_LAMBDA_ARN}'].SubscriptionArn | [0]" \
      --output text
  )"
fi

if [[ -z "$SUBSCRIPTION_ARN" || "$SUBSCRIPTION_ARN" == "None" ]]; then
  echo "Could not find SNS subscription ARN. Pass --subscription-arn." >&2
  exit 1
fi

tf_import "random_id.suffix" "$SUFFIX"

tf_import "aws_s3_bucket.raw" "$BUCKET_NAME"
tf_import "aws_s3_bucket_versioning.raw" "$BUCKET_NAME"
tf_import "aws_s3_bucket_server_side_encryption_configuration.raw" "$BUCKET_NAME"

tf_import "aws_dynamodb_table.source_state" "$PROJECT_NAME-warn-source-state"
tf_import "aws_dynamodb_table.notices" "$PROJECT_NAME-warn-notices"
tf_import "aws_dynamodb_table.watchlists" "$PROJECT_NAME-watchlists"
tf_import "aws_dynamodb_table.notifications" "$PROJECT_NAME-notifications"

tf_import "aws_sns_topic.new_notice" "$TOPIC_ARN"
tf_import "aws_sns_topic_subscription.matcher_subscription" "$SUBSCRIPTION_ARN"

tf_import "aws_iam_role.ingest_lambda" "$PROJECT_NAME-ingest-lambda-role"
tf_import "aws_iam_role_policy.ingest_policy" "$PROJECT_NAME-ingest-lambda-role:$PROJECT_NAME-ingest-lambda-policy"
tf_import "aws_iam_role.matcher_lambda" "$PROJECT_NAME-matcher-lambda-role"
tf_import "aws_iam_role_policy.matcher_policy" "$PROJECT_NAME-matcher-lambda-role:$PROJECT_NAME-matcher-lambda-policy"
tf_import "aws_iam_role.scheduler_invoke" "$PROJECT_NAME-scheduler-invoke-role"
tf_import "aws_iam_role_policy.scheduler_invoke_policy" "$PROJECT_NAME-scheduler-invoke-role:$PROJECT_NAME-scheduler-invoke-policy"

tf_import "aws_cloudwatch_log_group.ingest" "/aws/lambda/$PROJECT_NAME-ingest"
tf_import "aws_cloudwatch_log_group.matcher" "/aws/lambda/$PROJECT_NAME-match-notify"

tf_import "aws_lambda_function.ingest" "$PROJECT_NAME-ingest"
tf_import "aws_lambda_function.matcher" "$PROJECT_NAME-match-notify"
tf_import "aws_lambda_permission.allow_sns" "$PROJECT_NAME-match-notify/AllowExecutionFromSNS"
tf_import "aws_lambda_permission.allow_scheduler" "$PROJECT_NAME-ingest/AllowExecutionFromScheduler"

tf_import "aws_scheduler_schedule_group.this" "$PROJECT_NAME-group"
tf_import "aws_scheduler_schedule.ingest" "$PROJECT_NAME-group/$PROJECT_NAME-ingest-schedule"

echo
echo "Import complete. Next step:"
echo "terraform -chdir=$INFRA_DIR plan"
