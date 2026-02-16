#!/usr/bin/env bash
set -euo pipefail

# Disables/enables the signup API Lambda by setting reserved concurrency.
# - disable: reserved concurrency = 0 (blocks all invocations)
# - enable: removes reserved concurrency limit

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INFRA_DIR="$ROOT_DIR/infra"
DEFAULT_REGION="us-west-2"
DEFAULT_FUNCTION_NAME="WARNwatcher-watchlist-api"

usage() {
  cat <<EOF
Usage:
  $0 disable [function_name] [region]
  $0 enable  [function_name] [region]
  $0 status  [function_name] [region]

Examples:
  $0 disable
  $0 enable WARNwatcher-watchlist-api us-west-2
  $0 status

Notes:
  - If function_name is omitted, the script tries:
    1) terraform output watchlist_api_lambda_name (from infra/)
    2) WARNwatcher-watchlist-api
  - Region defaults to us-west-2.
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

ACTION="$1"
FUNCTION_NAME="${2:-}"
REGION="${3:-$DEFAULT_REGION}"

if ! command -v aws >/dev/null 2>&1; then
  echo "Error: aws CLI not found."
  exit 1
fi

resolve_function_name() {
  if [[ -n "$FUNCTION_NAME" ]]; then
    echo "$FUNCTION_NAME"
    return
  fi

  if command -v terraform >/dev/null 2>&1 && [[ -d "$INFRA_DIR" ]]; then
    set +e
    local tf_name
    tf_name="$(terraform -chdir="$INFRA_DIR" output -raw watchlist_api_lambda_name 2>/dev/null)"
    local rc=$?
    set -e
    if [[ $rc -eq 0 && -n "$tf_name" ]]; then
      echo "$tf_name"
      return
    fi
  fi

  echo "$DEFAULT_FUNCTION_NAME"
}

FUNCTION_NAME="$(resolve_function_name)"

case "$ACTION" in
  disable)
    aws lambda put-function-concurrency \
      --function-name "$FUNCTION_NAME" \
      --reserved-concurrent-executions 0 \
      --region "$REGION" >/dev/null
    echo "Disabled: $FUNCTION_NAME (reserved concurrency set to 0) in $REGION"
    ;;
  enable)
    aws lambda delete-function-concurrency \
      --function-name "$FUNCTION_NAME" \
      --region "$REGION" >/dev/null
    echo "Enabled: $FUNCTION_NAME (reserved concurrency removed) in $REGION"
    ;;
  status)
    aws lambda get-function-concurrency \
      --function-name "$FUNCTION_NAME" \
      --region "$REGION"
    ;;
  *)
    usage
    exit 1
    ;;
esac
