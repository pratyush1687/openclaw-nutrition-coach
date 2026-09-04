#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose run --rm nutrition-coach python -m app.cli backup
