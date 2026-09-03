#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "" ]; then
  echo "Usage: $0 /path/to/backup.sqlite" >&2
  exit 2
fi
cd "$(dirname "$0")/.."
docker compose stop nutrition-coach
cp "$1" data/nutrition.sqlite
docker compose up -d nutrition-coach
