#!/usr/bin/env bash
set -euo pipefail
cd /root/nutrition-coach
set -a
. ./.env
set +a
manifest="$(docker compose run --rm nutrition-coach python -m app.cli automation-manifest)"
echo "$manifest" | jq -c '.[]' | while read -r job; do
  name="$(echo "$job" | jq -r '.name')"
  schedule="$(echo "$job" | jq -r '.schedule')"
  command="$(echo "$job" | jq -r '.command')"
  existing="$(cd /root/openclaw-runtime && docker compose run --rm openclaw-cli automations list --json 2>/dev/null | jq -r --arg name "$name" '.jobs[]? | select(.name==$name) | .id' | head -n1 || true)"
  if [ -n "$existing" ]; then
    (cd /root/openclaw-runtime && docker compose run --rm openclaw-cli automations edit "$existing" --cron "$schedule" --tz Asia/Kolkata --exact --command "$command")
  else
    (cd /root/openclaw-runtime && docker compose run --rm openclaw-cli automations create "$schedule" --name "$name" --tz Asia/Kolkata --exact --command "$command")
  fi
done
