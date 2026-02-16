#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <web-bucket-name> <cloudfront-distribution-id>"
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$ROOT_DIR/frontend"
WEB_BUCKET="$1"
DIST_ID="$2"

aws s3 sync "$FRONTEND_DIR" "s3://$WEB_BUCKET" --delete
aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*"

echo "Frontend deployed to s3://$WEB_BUCKET"
