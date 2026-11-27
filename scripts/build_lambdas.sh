#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="$ROOT_DIR/build"
DIST_DIR="$ROOT_DIR/dist"

if [[ $# -eq 0 ]]; then
  rm -rf "$BUILD_DIR" "$DIST_DIR"
  set -- ingest match_notify monthly_digest watchlist_api
fi

mkdir -p "$BUILD_DIR" "$DIST_DIR"

build_lambda() {
  local name="$1"
  local src_dir="$ROOT_DIR/lambda/$name"
  local out_dir="$BUILD_DIR/$name"

  case "$name" in
    ingest|match_notify|monthly_digest|watchlist_api) ;;
    *) echo "Unknown Lambda: $name" >&2; exit 1 ;;
  esac

  rm -rf "$out_dir" "$DIST_DIR/$name.zip"
  mkdir -p "$out_dir"
  cp "$src_dir/app.py" "$out_dir/app.py"

  if [[ -f "$src_dir/requirements.txt" ]]; then
    # Terraform deploys Python 3.11 on Lambda's default x86_64 architecture.
    # Resolve wheels for that runtime even when packaging on macOS or newer Python.
    python3 -m pip install -r "$src_dir/requirements.txt" -t "$out_dir" --upgrade \
      --platform manylinux2014_x86_64 --python-version 3.11 \
      --implementation cp --abi cp311 --only-binary=:all:
  fi

  (
    cd "$out_dir"
    find . -type d -name "__pycache__" -prune -exec rm -rf {} +
    zip -r "$DIST_DIR/$name.zip" .
  )
}

for name in "$@"; do
  build_lambda "$name"
done

echo "Built:"
for name in "$@"; do
  echo " - $DIST_DIR/$name.zip"
done
