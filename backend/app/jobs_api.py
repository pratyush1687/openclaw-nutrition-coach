from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app.config import default_targets, env, load_config
from app.database import connect, init_db
from app.nutrition.coach import current_targets, morning_plan, scorecard, today, totals_for_date, weekly_summary
from app.reminders.jobs import check_meal
from app.telegram.client import send_message


def find_user_id(conn, payload: dict | None = None, query: dict[str, list[str]] | None = None) -> int | None:
    payload = payload or {}
    query = query or {}
    if payload.get("user_id") is not None:
        return int(payload["user_id"])
    if query.get("user_id"):
        return int(query["user_id"][0])
    telegram_user_id = payload.get("telegram_user_id") or (query.get("telegram_user_id", [None])[0])
    if telegram_user_id:
        row = conn.execute("SELECT id FROM users WHERE telegram_user_id=?", (str(telegram_user_id),)).fetchone()
        if row:
            return int(row["id"])
    user_name = payload.get("user_name") or (query.get("user_name", [None])[0])
    if user_name:
        row = conn.execute("SELECT id FROM users WHERE lower(name)=lower(?) AND active=1", (user_name,)).fetchone()
        if row:
            return int(row["id"])
    return None


def resolve_user_id(conn, payload: dict | None = None, query: dict[str, list[str]] | None = None) -> int:
    found = find_user_id(conn, payload, query)
    if found is not None:
        return found
    return 1


def authorized(query: dict[str, list[str]]) -> bool:
    expected = env("NUTRITION_JOB_TOKEN")
    if not expected:
        return True
    return query.get("token", [""])[0] == expected


def apply_update(conn, table: str, row_id: int, user_id: int, fields: dict, allowed: dict[str, str]) -> dict:
    updates = []
    values = []
    for key, column in allowed.items():
        if key in fields and fields[key] is not None:
            updates.append(f"{column}=?")
            values.append(fields[key])
    if not updates:
        return {"ok": False, "error": "no supported fields supplied"}
    values.extend([row_id, user_id])
    cur = conn.execute(
        f"UPDATE {table} SET {', '.join(updates)} WHERE id=? AND user_id=?",
        values,
    )
    return {"ok": cur.rowcount == 1, "updated": cur.rowcount}


def setup_status(conn, payload: dict | None = None, query: dict[str, list[str]] | None = None) -> dict:
    payload = payload or {}
    query = query or {}
    telegram_user_id = payload.get("telegram_user_id") or (query.get("telegram_user_id", [None])[0])
    user_id = find_user_id(conn, payload, query)
    if user_id is None:
        return {
            "ok": True,
            "configured": False,
            "needs_user": True,
            "telegram_user_id": str(telegram_user_id) if telegram_user_id else None,
            "missing_profile_fields": ["name", "age", "height_cm", "starting_weight_kg", "goal_weight_kg"],
            "missing_target_fields": ["calories_kcal", "protein_g"],
            "prompt": "Ask for name, age, height, current weight, goal weight, activity/training pattern, diet preferences, and whether they already know their calorie/protein targets.",
        }
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    targets = current_targets(conn, user_id)
    missing_profile = [
        field
        for field in ["age", "height_cm", "starting_weight_kg", "goal_weight_kg"]
        if user[field] in (None, "")
    ]
    missing_targets = [
        field
        for field in ["calories_kcal", "protein_g", "fibre_g", "water_l", "steps"]
        if targets.get(field) in (None, "")
    ]
    return {
        "ok": True,
        "configured": not missing_profile and not missing_targets,
        "needs_user": False,
        "user": dict(user),
        "targets": targets,
        "missing_profile_fields": missing_profile,
        "missing_target_fields": missing_targets,
    }


def active_users(conn) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT id, name, telegram_user_id FROM users WHERE id > 0 AND active=1 ORDER BY id"
        ).fetchall()
    ]


def user_chat_id(conn, user_id: int) -> str | None:
    row = conn.execute("SELECT telegram_user_id FROM users WHERE id=? AND active=1", (user_id,)).fetchone()
    return str(row["telegram_user_id"]) if row and row["telegram_user_id"] else None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/health":
            self.reply(200, "OK")
            return
        if parsed.path == "/today":
            init_db()
            with connect() as conn:
                user_id = resolve_user_id(conn, query=query)
                prefs = conn.execute("SELECT key, value FROM app_settings WHERE key LIKE 'preference.%'").fetchall()
                known = conn.execute(
                    "SELECT name, serving_description, calories, protein, carbs, fat, fibre, source, user_id FROM known_foods WHERE user_id IN (0, ?) ORDER BY times_seen DESC, updated_at DESC LIMIT 20",
                    (user_id,),
                ).fetchall()
                self.reply_json(
                    {
                        "ok": True,
                        "user_id": user_id,
                        "today": totals_for_date(conn, today(), user_id),
                        "targets": current_targets(conn, user_id),
                        "preferences": {row["key"].replace("preference.", "", 1): row["value"] for row in prefs},
                        "known_foods": [dict(row) for row in known],
                    }
                )
            return
        if parsed.path == "/logs":
            if not authorized(query):
                self.reply(403, "forbidden")
                return
            init_db()
            with connect() as conn:
                user_id = resolve_user_id(conn, query=query)
                limit = min(50, max(1, int(query.get("limit", ["10"])[0])))
                kind = query.get("kind", ["all"])[0]
                payload = {"ok": True, "user_id": user_id}
                if kind in ("all", "meals", "meal"):
                    payload["meals"] = [
                        dict(row)
                        for row in conn.execute(
                            """
                            SELECT id, timestamp, meal_type, estimated_calories calories,
                                   estimated_protein protein, estimated_carbs carbs,
                                   estimated_fat fat, estimated_fibre fibre, confidence,
                                   notes, source, confirmed_by_user, skipped
                            FROM meal_logs
                            WHERE user_id=?
                            ORDER BY timestamp DESC, id DESC
                            LIMIT ?
                            """,
                            (user_id, limit),
                        ).fetchall()
                    ]
                if kind in ("all", "weights", "weight"):
                    payload["weights"] = [
                        dict(row)
                        for row in conn.execute(
                            "SELECT id, logged_at, weight_kg, source FROM weight_logs WHERE user_id=? ORDER BY logged_at DESC, id DESC LIMIT ?",
                            (user_id, limit),
                        ).fetchall()
                    ]
                if kind in ("all", "water"):
                    payload["water"] = [
                        dict(row)
                        for row in conn.execute(
                            "SELECT id, logged_at, litres, source FROM water_logs WHERE user_id=? ORDER BY logged_at DESC, id DESC LIMIT ?",
                            (user_id, limit),
                        ).fetchall()
                    ]
                if kind in ("all", "steps"):
                    payload["steps"] = [
                        dict(row)
                        for row in conn.execute(
                            "SELECT id, logged_at, steps, source FROM step_logs WHERE user_id=? ORDER BY logged_at DESC, id DESC LIMIT ?",
                            (user_id, limit),
                        ).fetchall()
                    ]
                if kind in ("all", "workouts", "workout"):
                    payload["workouts"] = [
                        dict(row)
                        for row in conn.execute(
                            "SELECT id, logged_at, workout_type, completed, notes FROM workout_logs WHERE user_id=? ORDER BY logged_at DESC, id DESC LIMIT ?",
                            (user_id, limit),
                        ).fetchall()
                    ]
                self.reply_json(payload)
            return
        if not authorized(query):
            self.reply(403, "forbidden")
            return
        init_db()
        if parsed.path == "/setup-status":
            with connect() as conn:
                self.reply_json(setup_status(conn, query=query))
            return
        send = query.get("send", ["0"])[0] == "1"
        if parsed.path == "/morning-plan-all":
            sent = []
            with connect() as conn:
                users = active_users(conn)
            for user in users:
                text = morning_plan(int(user["id"]))
                if send and user.get("telegram_user_id"):
                    send_message(text, chat_id=str(user["telegram_user_id"]))
                sent.append({"user_id": user["id"], "name": user["name"], "sent": bool(send and user.get("telegram_user_id"))})
            self.reply_json({"ok": True, "users": sent})
            return
        if parsed.path == "/scorecard-all":
            sent = []
            with connect() as conn:
                users = active_users(conn)
            for user in users:
                text = scorecard(int(user["id"]))
                if send and user.get("telegram_user_id"):
                    send_message(text, chat_id=str(user["telegram_user_id"]))
                sent.append({"user_id": user["id"], "name": user["name"], "sent": bool(send and user.get("telegram_user_id"))})
            self.reply_json({"ok": True, "users": sent})
            return
        if parsed.path == "/weekly-all":
            sent = []
            with connect() as conn:
                users = active_users(conn)
            for user in users:
                text = weekly_summary(int(user["id"]))
                if send and user.get("telegram_user_id"):
                    send_message(text, chat_id=str(user["telegram_user_id"]))
                sent.append({"user_id": user["id"], "name": user["name"], "sent": bool(send and user.get("telegram_user_id"))})
            self.reply_json({"ok": True, "users": sent})
            return
        if parsed.path == "/morning-plan":
            with connect() as conn:
                user_id = resolve_user_id(conn, query=query)
                chat_id = user_chat_id(conn, user_id)
            text = morning_plan(user_id)
        elif parsed.path == "/scorecard":
            with connect() as conn:
                user_id = resolve_user_id(conn, query=query)
                chat_id = user_chat_id(conn, user_id)
            text = scorecard(user_id)
        elif parsed.path == "/weekly":
            with connect() as conn:
                user_id = resolve_user_id(conn, query=query)
                chat_id = user_chat_id(conn, user_id)
            text = weekly_summary(user_id)
        elif parsed.path == "/check-meal":
            with connect() as conn:
                maybe_user_id = find_user_id(conn, query=query)
                user_ids = [maybe_user_id] if maybe_user_id is not None else [int(user["id"]) for user in active_users(conn)]
            replies = [check_meal(query.get("meal", [""])[0], int(query.get("level", ["1"])[0]), user_id) for user_id in user_ids]
            text = "\n".join(reply for reply in replies if reply != "NO_REPLY") or "NO_REPLY"
            self.reply(200, text)
            return
        else:
            self.reply(404, "not found")
            return
        if send:
            send_message(text, chat_id=chat_id)
        self.reply(200, text)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not authorized(query):
            self.reply(403, "forbidden")
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        init_db()
        with connect() as conn:
            if parsed.path == "/users":
                next_id = payload.get("user_id")
                if next_id is None:
                    row = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 next_id FROM users WHERE id > 0").fetchone()
                    next_id = int(row["next_id"])
                conn.execute(
                    """
                    INSERT INTO users
                      (id, name, timezone, age, sex, height_cm, starting_weight_kg, goal_weight_kg, telegram_user_id, role, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name,
                      timezone=excluded.timezone,
                      age=excluded.age,
                      sex=excluded.sex,
                      height_cm=excluded.height_cm,
                      starting_weight_kg=excluded.starting_weight_kg,
                      goal_weight_kg=excluded.goal_weight_kg,
                      telegram_user_id=excluded.telegram_user_id,
                      role=excluded.role,
                      active=1
                    """,
                    (
                        int(next_id),
                        payload["name"],
                        payload.get("timezone", "Asia/Kolkata"),
                        payload.get("age"),
                        payload.get("sex"),
                        payload.get("height_cm"),
                        payload.get("starting_weight_kg"),
                        payload.get("goal_weight_kg"),
                        str(payload["telegram_user_id"]) if payload.get("telegram_user_id") is not None else None,
                        payload.get("role", "member"),
                    ),
                )
                targets = payload.get("targets", {})
                existing_targets = current_targets(conn, int(next_id))
                merged_targets = {**default_targets(load_config()), **existing_targets, **targets}
                conn.execute(
                    """
                    INSERT INTO daily_targets
                      (user_id, effective_date, calories_kcal, protein_g, fibre_g, water_l, steps)
                    VALUES (?, date('now'), ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, effective_date) DO UPDATE SET
                      calories_kcal=excluded.calories_kcal,
                      protein_g=excluded.protein_g,
                      fibre_g=excluded.fibre_g,
                      water_l=excluded.water_l,
                      steps=excluded.steps
                    """,
                    (
                        int(next_id),
                        merged_targets["calories_kcal"],
                        merged_targets["protein_g"],
                        merged_targets["fibre_g"],
                        merged_targets["water_l"],
                        merged_targets["steps"],
                    ),
                )
                for key in ["goal", "activity_level", "diet_preferences"]:
                    if payload.get(key):
                        conn.execute(
                            """
                            INSERT INTO app_settings (key, value)
                            VALUES (?, ?)
                            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
                            """,
                            (f"preference.{int(next_id)}.{key}", str(payload[key])),
                        )
                self.reply_json({"ok": True, "user_id": int(next_id)})
                return
            user_id = resolve_user_id(conn, payload, query)
            if parsed.path == "/log-meal":
                conn.execute(
                    """
                    INSERT INTO meal_logs
                      (user_id, timestamp, meal_type, telegram_message_id, estimated_calories,
                       estimated_protein, estimated_carbs, estimated_fat, estimated_fibre,
                       confidence, notes, source, confirmed_by_user, skipped)
                    VALUES (?, COALESCE(?, datetime('now')), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        payload.get("timestamp"),
                        payload.get("meal_type", "meal"),
                        payload.get("telegram_message_id"),
                        float(payload.get("calories", 0)),
                        float(payload.get("protein", 0)),
                        float(payload.get("carbs", 0)),
                        float(payload.get("fat", 0)),
                        float(payload.get("fibre", 0)),
                        payload.get("confidence", "ai-estimated"),
                        payload.get("notes", ""),
                        payload.get("source", "openclaw"),
                        1 if payload.get("confirmed_by_user") else 0,
                        1 if payload.get("skipped") else 0,
                    ),
                )
                self.reply_json({"ok": True, "user_id": user_id, "today": totals_for_date(conn, today(), user_id), "targets": current_targets(conn, user_id)})
                return
            if parsed.path == "/update-meal":
                row_id = int(payload["id"])
                meal_fields = {}
                if "timestamp" in payload:
                    meal_fields["timestamp"] = payload["timestamp"]
                if "meal_type" in payload:
                    meal_fields["meal_type"] = payload["meal_type"]
                if "calories" in payload:
                    meal_fields["estimated_calories"] = float(payload["calories"])
                if "protein" in payload:
                    meal_fields["estimated_protein"] = float(payload["protein"])
                if "carbs" in payload:
                    meal_fields["estimated_carbs"] = float(payload["carbs"])
                if "fat" in payload:
                    meal_fields["estimated_fat"] = float(payload["fat"])
                if "fibre" in payload:
                    meal_fields["estimated_fibre"] = float(payload["fibre"])
                if "confidence" in payload:
                    meal_fields["confidence"] = payload["confidence"]
                if "notes" in payload:
                    meal_fields["notes"] = payload["notes"]
                if "confirmed_by_user" in payload:
                    meal_fields["confirmed_by_user"] = 1 if payload["confirmed_by_user"] else 0
                if "skipped" in payload:
                    meal_fields["skipped"] = 1 if payload["skipped"] else 0
                result = apply_update(
                    conn,
                    "meal_logs",
                    row_id,
                    user_id,
                    meal_fields,
                    {
                        "timestamp": "timestamp",
                        "meal_type": "meal_type",
                        "estimated_calories": "estimated_calories",
                        "estimated_protein": "estimated_protein",
                        "estimated_carbs": "estimated_carbs",
                        "estimated_fat": "estimated_fat",
                        "estimated_fibre": "estimated_fibre",
                        "confidence": "confidence",
                        "notes": "notes",
                        "confirmed_by_user": "confirmed_by_user",
                        "skipped": "skipped",
                    },
                )
                self.reply_json({**result, "user_id": user_id, "today": totals_for_date(conn, today(), user_id)})
                return
            if parsed.path == "/log-weight":
                conn.execute(
                    "INSERT INTO weight_logs (user_id, logged_at, weight_kg, source) VALUES (?, COALESCE(?, datetime('now')), ?, 'openclaw')",
                    (user_id, payload.get("timestamp"), float(payload["weight_kg"])),
                )
                self.reply_json({"ok": True})
                return
            if parsed.path == "/update-weight":
                weight_fields = {}
                if "timestamp" in payload:
                    weight_fields["logged_at"] = payload["timestamp"]
                if "weight_kg" in payload:
                    weight_fields["weight_kg"] = float(payload["weight_kg"])
                result = apply_update(
                    conn,
                    "weight_logs",
                    int(payload["id"]),
                    user_id,
                    weight_fields,
                    {"logged_at": "logged_at", "weight_kg": "weight_kg"},
                )
                self.reply_json({**result, "user_id": user_id})
                return
            if parsed.path == "/log-water":
                conn.execute(
                    "INSERT INTO water_logs (user_id, logged_at, litres, source) VALUES (?, COALESCE(?, datetime('now')), ?, 'openclaw')",
                    (user_id, payload.get("timestamp"), float(payload["litres"])),
                )
                self.reply_json({"ok": True})
                return
            if parsed.path == "/update-water":
                water_fields = {}
                if "timestamp" in payload:
                    water_fields["logged_at"] = payload["timestamp"]
                if "litres" in payload:
                    water_fields["litres"] = float(payload["litres"])
                result = apply_update(
                    conn,
                    "water_logs",
                    int(payload["id"]),
                    user_id,
                    water_fields,
                    {"logged_at": "logged_at", "litres": "litres"},
                )
                self.reply_json({**result, "user_id": user_id})
                return
            if parsed.path == "/log-steps":
                conn.execute(
                    "INSERT INTO step_logs (user_id, logged_at, steps, source) VALUES (?, COALESCE(?, datetime('now')), ?, 'openclaw')",
                    (user_id, payload.get("timestamp"), int(payload["steps"])),
                )
                self.reply_json({"ok": True})
                return
            if parsed.path == "/update-steps":
                step_fields = {}
                if "timestamp" in payload:
                    step_fields["logged_at"] = payload["timestamp"]
                if "steps" in payload:
                    step_fields["steps"] = int(payload["steps"])
                result = apply_update(
                    conn,
                    "step_logs",
                    int(payload["id"]),
                    user_id,
                    step_fields,
                    {"logged_at": "logged_at", "steps": "steps"},
                )
                self.reply_json({**result, "user_id": user_id})
                return
            if parsed.path == "/log-workout":
                conn.execute(
                    "INSERT INTO workout_logs (user_id, logged_at, workout_type, completed, notes) VALUES (?, COALESCE(?, datetime('now')), ?, ?, ?)",
                    (user_id, payload.get("timestamp"), payload.get("workout_type", "strength training"), 1 if payload.get("completed", True) else 0, payload.get("notes", "")),
                )
                self.reply_json({"ok": True})
                return
            if parsed.path == "/update-workout":
                workout_fields = {}
                if "timestamp" in payload:
                    workout_fields["logged_at"] = payload["timestamp"]
                if "workout_type" in payload:
                    workout_fields["workout_type"] = payload["workout_type"]
                if "completed" in payload:
                    workout_fields["completed"] = 1 if payload["completed"] else 0
                if "notes" in payload:
                    workout_fields["notes"] = payload["notes"]
                result = apply_update(
                    conn,
                    "workout_logs",
                    int(payload["id"]),
                    user_id,
                    workout_fields,
                    {"logged_at": "logged_at", "workout_type": "workout_type", "completed": "completed", "notes": "notes"},
                )
                self.reply_json({**result, "user_id": user_id})
                return
            if parsed.path == "/targets":
                existing = current_targets(conn, user_id)
                merged = {**existing, **payload}
                conn.execute(
                    """
                    INSERT INTO daily_targets
                      (user_id, effective_date, calories_kcal, protein_g, fibre_g, water_l, steps)
                    VALUES (?, date('now'), ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, effective_date) DO UPDATE SET
                      calories_kcal=excluded.calories_kcal,
                      protein_g=excluded.protein_g,
                      fibre_g=excluded.fibre_g,
                      water_l=excluded.water_l,
                      steps=excluded.steps
                    """,
                    (user_id, merged["calories_kcal"], merged["protein_g"], merged["fibre_g"], merged["water_l"], merged["steps"]),
                )
                self.reply_json({"ok": True, "user_id": user_id, "targets": current_targets(conn, user_id)})
                return
            if parsed.path == "/known-food":
                food_user_id = 0 if payload.get("household", True) else user_id
                conn.execute(
                    """
                    INSERT INTO known_foods
                      (user_id, name, serving_description, calories, protein, carbs, fat, fibre, source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, name, serving_description) DO UPDATE SET
                      calories=excluded.calories,
                      protein=excluded.protein,
                      carbs=excluded.carbs,
                      fat=excluded.fat,
                      fibre=excluded.fibre,
                      source=excluded.source,
                      times_seen=known_foods.times_seen + 1,
                      updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        food_user_id,
                        payload["name"],
                        payload.get("serving_description"),
                        float(payload["calories"]),
                        float(payload["protein"]),
                        float(payload.get("carbs", 0)),
                        float(payload.get("fat", 0)),
                        float(payload.get("fibre", 0)),
                        payload.get("source", "user-confirmed"),
                    ),
                )
                self.reply_json({"ok": True})
                return
            if parsed.path == "/preference":
                scope = "household" if payload.get("household", False) else str(user_id)
                key = f"preference.{scope}." + payload["key"]
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
                    """,
                    (key, payload["value"]),
                )
                self.reply_json({"ok": True})
                return
        self.reply(404, "not found")

    def log_message(self, fmt: str, *args) -> None:
        return

    def reply(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def reply_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    init_db()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()


if __name__ == "__main__":
    main()
