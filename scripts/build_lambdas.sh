#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$ROOT_DIR/dist"

rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

build_lambda() {
  local name="$1"
  local src_dir="$ROOT_DIR/lambda/$name"
  local out_dir="$BUILD_DIR/$name"

  mkdir -p "$out_dir"
  cp "$src_dir/app.py" "$out_dir/app.py"

  if [[ -f "$src_dir/requirements.txt" ]]; then
    python3 -m pip install -r "$src_dir/requirements.txt" -t "$out_dir" --upgrade
  fi

  (
    cd "$out_dir"
    find . -type d -name "__pycache__" -prune -exec rm -rf {} +
    zip -r "$DIST_DIR/$name.zip" .
  )
}

build_lambda "ingest"
build_lambda "match_notify"
build_lambda "monthly_digest"
build_lambda "watchlist_api"

echo "Built:"
echo " - $DIST_DIR/ingest.zip"
echo " - $DIST_DIR/match_notify.zip"
echo " - $DIST_DIR/monthly_digest.zip"
echo " - $DIST_DIR/watchlist_api.zip"
