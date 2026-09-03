from __future__ import annotations

from app.config import load_config
from app.database import connect, init_db
from app.nutrition.coach import today
from app.telegram.client import send_message
from app.voice.twilio_call import maybe_call


MESSAGES = {
    1: "Where's {meal}? Send the photo.",
    2: "You asked me to keep you accountable. What did you eat for {meal}?",
    3: "Meal. Photo. Now. Log {meal}, or tell me you intentionally skipped it.",
}


def meal_logged(conn, meal: str, date_text: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM meal_logs WHERE user_id=1 AND meal_type=? AND date(timestamp)=? LIMIT 1",
        (meal, date_text),
    ).fetchone()
    return row is not None


def check_meal(meal: str, level: int) -> str:
    init_db()
    date_text = today()
    with connect() as conn:
        if meal_logged(conn, meal, date_text):
            print("NO_REPLY")
            return "NO_REPLY"
        state = conn.execute(
            "SELECT status FROM reminder_state WHERE user_id=1 AND reminder_date=? AND meal_type=?",
            (date_text, meal),
        ).fetchone()
        if state and state["status"] in {"skipped", "done"}:
            print("NO_REPLY")
            return "NO_REPLY"
        conn.execute(
            """
            INSERT INTO reminder_state (user_id, reminder_date, meal_type, level, status)
            VALUES (1, ?, ?, ?, 'pending')
            ON CONFLICT(user_id, reminder_date, meal_type)
            DO UPDATE SET level=excluded.level, updated_at=CURRENT_TIMESTAMP
            """,
            (date_text, meal, level),
        )
    text = MESSAGES.get(level, MESSAGES[3]).format(meal=meal)
    sent = send_message(text)
    if level >= 3:
        maybe_call(f"You have not logged {meal}. Tell me what you ate, or log it on Telegram.")
    return text if sent else "NO_REPLY"


def install_manifest() -> list[dict]:
    cfg = load_config()
    jobs = [
        {
            "name": "nutrition-morning-plan",
            "schedule": cfg["schedule"]["morning_plan"],
            "command": "curl -fsS \"http://nutrition-jobs:8080/morning-plan?send=1&token=${NUTRITION_JOB_TOKEN}\"",
        },
        {
            "name": "nutrition-evening-scorecard",
            "schedule": cfg["schedule"]["evening_scorecard"],
            "command": "curl -fsS \"http://nutrition-jobs:8080/scorecard?send=1&token=${NUTRITION_JOB_TOKEN}\"",
        },
        {
            "name": "nutrition-weekly-summary",
            "schedule": cfg["schedule"]["weekly_summary"],
            "command": "curl -fsS \"http://nutrition-jobs:8080/weekly?send=1&token=${NUTRITION_JOB_TOKEN}\"",
        },
    ]
    for meal, spec in cfg["meal_windows"].items():
        for idx, when in enumerate(spec["reminders"], start=1):
            minute, hour = when.split(":")[1], when.split(":")[0]
            jobs.append(
                {
                    "name": f"nutrition-{meal}-reminder-{idx}",
                    "schedule": f"{int(minute)} {int(hour)} * * *",
                    "command": f"curl -fsS \"http://nutrition-jobs:8080/check-meal?meal={meal}&level={idx}&token=${{NUTRITION_JOB_TOKEN}}\"",
                }
            )
    return jobs
