from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from app.config import env
from app.database import connect, init_db
from app.nutrition.coach import morning_plan, scorecard, weekly_summary
from app.reminders.jobs import check_meal, install_manifest
from app.telegram.client import send_message


def cmd_health(quiet: bool = False) -> int:
    init_db()
    problems = []
    with connect() as conn:
        conn.execute("SELECT COUNT(*) FROM users").fetchone()
    disk = shutil.disk_usage("/app/data")
    if disk.free / disk.total < 0.1:
        problems.append("data disk has less than 10% free space")
    if not env("TELEGRAM_BOT_TOKEN"):
        problems.append("TELEGRAM_BOT_TOKEN missing")
    if not env("TELEGRAM_CHAT_ID"):
        problems.append("TELEGRAM_CHAT_ID missing")
    if problems:
        if not quiet:
            print("WARN: " + "; ".join(problems))
        return 0
    if not quiet:
        print("OK")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("morning-plan", "scorecard", "weekly"):
        p = sub.add_parser(name)
        p.add_argument("--send", action="store_true")
    p = sub.add_parser("check-meal")
    p.add_argument("meal")
    p.add_argument("level", type=int)
    p = sub.add_parser("health")
    p.add_argument("--quiet", action="store_true")
    sub.add_parser("init-db")
    sub.add_parser("automation-manifest")
    sub.add_parser("backup")
    args = parser.parse_args()

    if args.cmd == "init-db":
        init_db()
        print("database initialized")
    elif args.cmd == "morning-plan":
        text = morning_plan()
        print(text)
        if args.send:
            send_message(text)
    elif args.cmd == "scorecard":
        text = scorecard()
        print(text)
        if args.send:
            send_message(text)
    elif args.cmd == "weekly":
        text = weekly_summary()
        print(text)
        if args.send:
            send_message(text)
    elif args.cmd == "check-meal":
        print(check_meal(args.meal, args.level))
    elif args.cmd == "health":
        raise SystemExit(cmd_health(args.quiet))
    elif args.cmd == "automation-manifest":
        print(json.dumps(install_manifest(), indent=2))
    elif args.cmd == "backup":
        init_db()
        src = Path(os.getenv("DATABASE_PATH", "/app/data/nutrition.sqlite"))
        dest_dir = Path("/app/backups")
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"nutrition-{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}.sqlite"
        shutil.copy2(src, dest)
        for old in sorted(dest_dir.glob("nutrition-*.sqlite"))[:-14]:
            old.unlink()
        print(dest)


if __name__ == "__main__":
    main()
