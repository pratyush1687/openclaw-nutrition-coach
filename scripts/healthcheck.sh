#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
echo "nutrition-coach container:"
docker compose ps
echo
echo "app health:"
docker compose run --rm nutrition-coach python -m app.cli health
echo
echo "OpenClaw gateway:"
if [ -d /root/openclaw-runtime ]; then
  cd /root/openclaw-runtime
  docker compose ps || true
  docker compose run --rm openclaw-cli gateway status || true
else
  echo "OpenClaw runtime not found"
fi
echo
echo "disk:"
df -h / /root/nutrition-coach/data
