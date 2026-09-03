from __future__ import annotations

import requests

from app.config import env
from app.database import connect, init_db


def send_message(text: str, chat_id: str | None = None) -> bool:
    token = env("TELEGRAM_BOT_TOKEN")
    target = chat_id or env("TELEGRAM_CHAT_ID")
    if not target:
        init_db()
        with connect() as conn:
            row = conn.execute("SELECT value FROM app_settings WHERE key='telegram_chat_id'").fetchone()
            target = row["value"] if row else None
    if not token or not target:
        print("NO_REPLY")
        return False
    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": target, "text": text},
        timeout=20,
    )
    response.raise_for_status()
    return True
