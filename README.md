# OpenClaw Nutrition Coach

Self-hosted OpenClaw nutrition coach for Telegram.

The plugin contains:

- An OpenClaw skill for meal photos, text logs, corrections, target changes, and daily coaching.
- A Node MCP server exposing nutrition ledger tools to OpenClaw.
- A Dockerized private backend with SQLite persistence for meals, macros, water, steps, weight, workouts, targets, known foods, preferences, and reminders.
- Scripts for backups, health checks, and schedule installation.

## What It Does

- Sends a personalized morning plan at 08:00 in the configured timezone.
- Tracks calories, protein, carbs, fat, fibre, water, steps, weight, and workouts.
- Supports correction tools for existing meal, weight, water, step, and workout logs.
- Runs an initial setup stage for each user before regular coaching.
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

## Per-User Configuration

Configure household members in `backend/config/coach.yaml` under `users`. Each user can have separate targets, demographics, timezone, Telegram identity, and preferences:

```yaml
timezone: Asia/Kolkata

defaults:
  targets:
    calories_kcal: 2000
    protein_g: 100
    fibre_g: 30
    water_l: 2.5
    steps: 8000

users:
  - id: 1
    name: Primary User
    role: primary
    telegram_user_id: "123456789"
    timezone: Asia/Kolkata
    targets:
      calories_kcal: 2000
      protein_g: 100
      fibre_g: 35
      water_l: 3
      steps: 8000
    preferences:
      diet: vegetarian plus eggs

  - id: 2
    name: Household Member
    role: member
    telegram_user_id: "987654321"
    targets:
      calories_kcal: 1800
      protein_g: 90
```

The backend also supports the older single-user `user` plus `targets` config shape, but new installs should use `users`.

All MCP tools accept `user_id`, `user_name`, or `telegram_user_id`. Scheduled jobs should include the intended identity, for example:

```bash
curl -fsS "http://nutrition-jobs:8080/morning-plan?user_id=1&send=1&token=${NUTRITION_JOB_TOKEN}"
curl -fsS "http://nutrition-jobs:8080/check-meal?user_id=2&meal=lunch&level=1&token=${NUTRITION_JOB_TOKEN}"
```

## Initial Setup Flow

OpenClaw should call `setup_status` when a new Telegram sender appears or when profile data may be incomplete. If setup is incomplete, the coach asks for:

- name
- age
- height
- current weight
- goal weight
- primary goal
- activity/training pattern
- diet preferences or restrictions
- known calorie/protein targets, if any

OpenClaw then saves the answers with `upsert_user`. If calorie/protein targets are unknown, use configurable defaults first and adjust after real logs and weight trend data accumulate.

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
- `setup_status`
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

The automation manifest generator creates those jobs for every configured user in `users`.

Meal-window checks should run as silent command jobs calling `/check-meal`, because that endpoint directly sends Telegram only when a reminder is needed and returns no output for quiet runs.

## Development

```bash
cd backend
PYTHONPATH=. pytest -q
python -m py_compile app/jobs_api.py

cd ../mcp
node --check nutrition_mcp.mjs
```
