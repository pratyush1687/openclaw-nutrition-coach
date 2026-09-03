# OpenClaw Nutrition Coach

Self-hosted OpenClaw nutrition coach for Telegram.

The plugin contains:

- An OpenClaw skill for meal photos, text logs, corrections, target changes, and daily coaching.
- A Node MCP server exposing nutrition ledger tools to OpenClaw.
- A Dockerized private backend with SQLite persistence for meals, macros, water, steps, weight, workouts, targets, known foods, preferences, and reminders.
- Scripts for backups, health checks, and schedule installation.

## What It Does

- Sends a personalized morning plan at 08:00 Asia/Kolkata.
- Tracks calories, protein, carbs, fat, fibre, water, steps, weight, and workouts.
- Supports correction tools for existing meal, weight, water, step, and workout logs.
- Sends meal-window accountability reminders without duplicate messages when meals are already logged or skipped.
- Sends an evening scorecard and weekly 7-day adherence summary.
- Supports household-aware users with shared foods and separate personal ledgers.

## Runtime Shape

Run the backend beside OpenClaw on a private Docker network. OpenClaw talks to the backend only through the bundled MCP server and the backend's private HTTP API.

Required environment:

```bash
NUTRITION_API_BASE=http://nutrition-jobs:8080
NUTRITION_JOB_TOKEN=<private random token>
TELEGRAM_BOT_TOKEN=<telegram bot token>
TELEGRAM_CHAT_ID=<telegram chat id>
```

Do not commit `.env`, SQLite databases, backups, Telegram tokens, OpenClaw gateway tokens, or auth profiles.

## Backend Install

```bash
cd backend
cp .env.example .env
openssl rand -hex 32
```

Put the generated token in `NUTRITION_JOB_TOKEN`, fill Telegram credentials, then start the backend:

```bash
docker compose up -d --build nutrition-jobs
docker compose exec -T nutrition-jobs curl -fsS http://127.0.0.1:8080/health
```

## MCP Install

```bash
cd mcp
npm install
```

Configure OpenClaw to launch `node ./mcp/nutrition_mcp.mjs` with `NUTRITION_API_BASE` and `NUTRITION_JOB_TOKEN` set.

The MCP tools include:

- `get_today`
- `get_logs`
- `log_meal`
- `update_meal`
- `log_weight`
- `update_weight`
- `log_water`
- `update_water`
- `log_steps`
- `update_steps`
- `log_workout`
- `update_workout`
- `update_targets`
- `upsert_known_food`
- `set_preference`
- `morning_plan`
- `scorecard`
- `weekly_summary`
- `upsert_user`

## Scheduled Jobs

Use OpenClaw automations for:

- 08:00 daily morning plan.
- Meal-window checks.
- Evening scorecard.
- Weekly summary.

Meal-window checks should run as silent command jobs calling `/check-meal`, because that endpoint directly sends Telegram only when a reminder is needed and returns no output for quiet runs.

## Development

```bash
cd backend
PYTHONPATH=. pytest -q
python -m py_compile app/jobs_api.py

cd ../mcp
node --check nutrition_mcp.mjs
```
