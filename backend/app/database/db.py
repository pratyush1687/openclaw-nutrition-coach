from __future__ import annotations

import os
import sqlite3
from pathlib import Path


def db_path() -> Path:
    return Path(os.getenv("DATABASE_PATH", "/app/data/nutrition.sqlite"))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  timezone TEXT NOT NULL,
  age INTEGER,
  sex TEXT,
  height_cm REAL,
  starting_weight_kg REAL,
  goal_weight_kg REAL,
  telegram_user_id TEXT UNIQUE,
  role TEXT NOT NULL DEFAULT 'member',
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_targets (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  effective_date TEXT NOT NULL,
  calories_kcal INTEGER NOT NULL,
  protein_g INTEGER NOT NULL,
  fibre_g INTEGER NOT NULL,
  water_l REAL NOT NULL,
  steps INTEGER NOT NULL,
  UNIQUE(user_id, effective_date)
);

CREATE TABLE IF NOT EXISTS weight_logs (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  logged_at TEXT NOT NULL,
  weight_kg REAL NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram'
);

CREATE TABLE IF NOT EXISTS meal_logs (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  timestamp TEXT NOT NULL,
  meal_type TEXT NOT NULL,
  telegram_message_id INTEGER,
  photo_reference TEXT,
  estimated_calories REAL NOT NULL,
  estimated_protein REAL NOT NULL,
  estimated_carbs REAL,
  estimated_fat REAL,
  estimated_fibre REAL,
  confidence TEXT NOT NULL DEFAULT 'estimated',
  notes TEXT,
  source TEXT NOT NULL DEFAULT 'telegram',
  confirmed_by_user INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meal_items (
  id INTEGER PRIMARY KEY,
  meal_log_id INTEGER NOT NULL REFERENCES meal_logs(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  quantity TEXT,
  calories REAL,
  protein REAL,
  carbs REAL,
  fat REAL,
  fibre REAL,
  source TEXT NOT NULL DEFAULT 'ai-estimated',
  confirmed_by_user INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS water_logs (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  logged_at TEXT NOT NULL,
  litres REAL NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram'
);

CREATE TABLE IF NOT EXISTS step_logs (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  logged_at TEXT NOT NULL,
  steps INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'telegram'
);

CREATE TABLE IF NOT EXISTS workout_logs (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  logged_at TEXT NOT NULL,
  workout_type TEXT,
  completed INTEGER NOT NULL DEFAULT 1,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS daily_summaries (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  summary_date TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, summary_date)
);

CREATE TABLE IF NOT EXISTS known_foods (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  name TEXT NOT NULL,
  serving_description TEXT,
  calories REAL NOT NULL,
  protein REAL NOT NULL,
  carbs REAL,
  fat REAL,
  fibre REAL,
  source TEXT NOT NULL CHECK(source IN ('user-confirmed','ai-estimated')),
  times_seen INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, name, serving_description)
);

CREATE TABLE IF NOT EXISTS reminder_state (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id),
  reminder_date TEXT NOT NULL,
  meal_type TEXT NOT NULL,
  level INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  next_reminder_at TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, reminder_date, meal_type)
);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def init_db(config: dict | None = None) -> None:
    from app.config import configured_users, default_targets, load_config

    cfg = config or load_config()
    with connect() as conn:
        conn.executescript(SCHEMA)
        migrate(conn)
        conn.execute(
            """
            INSERT INTO users (id, name, timezone, role)
            VALUES (0, 'Household', ?, 'household')
            ON CONFLICT(id) DO UPDATE SET name=excluded.name, timezone=excluded.timezone, role=excluded.role
            """,
            (cfg.get("timezone", "Asia/Kolkata"),),
        )
        fallback_targets = default_targets(cfg)
        for user in configured_users(cfg):
            user_id = int(user.get("id", 1))
            tz = user.get("timezone") or cfg.get("timezone", "Asia/Kolkata")
            role = user.get("role", "primary" if user_id == 1 else "member")
            conn.execute(
                """
            INSERT INTO users (id, name, timezone, age, sex, height_cm, starting_weight_kg, goal_weight_kg, telegram_user_id, role, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, timezone=excluded.timezone, age=excluded.age, sex=excluded.sex,
              height_cm=excluded.height_cm, starting_weight_kg=excluded.starting_weight_kg,
              goal_weight_kg=excluded.goal_weight_kg,
              telegram_user_id=COALESCE(excluded.telegram_user_id, users.telegram_user_id),
              role=excluded.role,
              active=1
                """,
                (
                    user_id,
                    user.get("name", f"User {user_id}"),
                    tz,
                    user.get("age"),
                    user.get("sex"),
                    user.get("height_cm"),
                    user.get("starting_weight_kg"),
                    user.get("goal_weight_kg"),
                    str(user["telegram_user_id"]) if user.get("telegram_user_id") is not None else None,
                    role,
                ),
            )
            targets = {**fallback_targets, **(user.get("targets", {}) or {})}
            conn.execute(
                """
            INSERT INTO daily_targets
              (user_id, effective_date, calories_kcal, protein_g, fibre_g, water_l, steps)
            VALUES (?, date('now'), ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, effective_date) DO NOTHING
                """,
                (
                    user_id,
                    targets["calories_kcal"],
                    targets["protein_g"],
                    targets["fibre_g"],
                    targets["water_l"],
                    targets["steps"],
                ),
            )


def migrate(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    for statement in [
        ("telegram_user_id", "ALTER TABLE users ADD COLUMN telegram_user_id TEXT"),
        ("role", "ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'member'"),
        ("active", "ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1"),
    ]:
        if statement[0] not in columns:
            conn.execute(statement[1])
