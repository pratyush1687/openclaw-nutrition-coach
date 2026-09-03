from __future__ import annotations

import base64
from datetime import datetime

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import env, load_config
from app.database import connect, init_db
from app.nutrition.ai import estimate_text_meal
from app.nutrition.coach import current_targets, morning_plan, scorecard, today, totals_for_date
from app.nutrition.parser import detect_meal_type, looks_like_food_log, parse_steps, parse_target_update, parse_water, parse_weight
from app.nutrition.vision import estimate_photo_meal


def remember_chat(update: Update) -> None:
    if not update.effective_chat:
        return
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value)
            VALUES ('telegram_chat_id', ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
            """,
            (str(update.effective_chat.id),),
        )


def fmt_status(conn) -> str:
    targets = current_targets(conn)
    totals = totals_for_date(conn, today())
    return "\n".join(
        [
            "TODAY",
            f"{totals['calories']:.0f} / {targets['calories_kcal']} kcal",
            f"{totals['protein']:.0f} / {targets['protein_g']} g protein",
            f"Carbs: {totals['carbs']:.0f} g",
            f"Fat: {totals['fat']:.0f} g",
            f"Fibre: {totals['fibre']:.0f} / {targets['fibre_g']} g",
            "",
            "Remaining:",
            f"{max(0, targets['calories_kcal'] - totals['calories']):.0f} kcal",
            f"{max(0, targets['protein_g'] - totals['protein']):.0f} g protein",
            "",
            "Next meal: keep it protein-forward. Tofu/soy/egg whites + vegetables fits well.",
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    init_db()
    remember_chat(update)
    await update.message.reply_text("Coach online. Send meals, weight, water, steps, or /today.")


async def today_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    init_db()
    remember_chat(update)
    with connect() as conn:
        await update.message.reply_text(fmt_status(conn))


async def plan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_chat(update)
    await update.message.reply_text(morning_plan())


async def scorecard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    remember_chat(update)
    await update.message.reply_text(scorecard())


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    init_db()
    remember_chat(update)
    text = update.message.text or ""
    cfg = load_config()
    now = datetime.now().astimezone()
    with connect() as conn:
        target_updates = parse_target_update(text)
        if target_updates:
            targets = current_targets(conn)
            merged = {**dict(targets), **target_updates}
            conn.execute(
                """
                INSERT INTO daily_targets
                  (user_id, effective_date, calories_kcal, protein_g, fibre_g, water_l, steps)
                VALUES (1, date('now'), ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, effective_date) DO UPDATE SET
                  calories_kcal=excluded.calories_kcal,
                  protein_g=excluded.protein_g,
                  fibre_g=excluded.fibre_g,
                  water_l=excluded.water_l,
                  steps=excluded.steps
                """,
                (
                    merged["calories_kcal"],
                    merged["protein_g"],
                    merged["fibre_g"],
                    merged["water_l"],
                    merged["steps"],
                ),
            )
            await update.message.reply_text(
                "Targets updated.\n"
                f"{merged['calories_kcal']} kcal / {merged['protein_g']} g protein\n"
                f"Fibre target: {merged['fibre_g']} g\n"
                "I already track carbs, fat, and fibre on meal logs."
            )
            return
        weight = parse_weight(text)
        if weight is not None and "weight" in text.lower():
            conn.execute("INSERT INTO weight_logs (user_id, logged_at, weight_kg) VALUES (1, ?, ?)", (now.isoformat(), weight))
            await update.message.reply_text(f"Weight logged: {weight:.1f} kg.")
            return
        steps = parse_steps(text)
        if steps is not None:
            conn.execute("INSERT INTO step_logs (user_id, logged_at, steps) VALUES (1, ?, ?)", (now.isoformat(), steps))
            await update.message.reply_text(f"Steps logged: {steps:,}.")
            return
        water = parse_water(text)
        if water is not None:
            conn.execute("INSERT INTO water_logs (user_id, logged_at, litres) VALUES (1, ?, ?)", (now.isoformat(), water))
            await update.message.reply_text(f"Water logged: {water:g} L.")
            return
        if "workout" in text.lower() or "training" in text.lower():
            conn.execute("INSERT INTO workout_logs (user_id, logged_at, workout_type, notes) VALUES (1, ?, ?, ?)", (now.isoformat(), "strength training", text))
            await update.message.reply_text("Workout logged. Good.")
            return
        if "skip" in text.lower() and any(m in text.lower() for m in cfg.get("meal_windows", {})):
            meal = detect_meal_type(text, now.hour)
            conn.execute(
                "INSERT INTO meal_logs (user_id, timestamp, meal_type, estimated_calories, estimated_protein, notes, skipped) VALUES (1, ?, ?, 0, 0, ?, 1)",
                (now.isoformat(), meal, text),
            )
            await update.message.reply_text(f"{meal.title()} marked skipped. Reminders stopped for that window.")
            return
        if not looks_like_food_log(text):
            await update.message.reply_text("I did not log that as food. Send a meal/photo, weight, water, steps, workout, or /today.")
            return
        estimate = estimate_text_meal(text)
        meal = detect_meal_type(text, now.hour)
        conn.execute(
            """
            INSERT INTO meal_logs
              (user_id, timestamp, meal_type, telegram_message_id, estimated_calories, estimated_protein,
               estimated_carbs, estimated_fat, estimated_fibre, confidence, notes)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.isoformat(),
                meal,
                update.message.message_id,
                estimate["calories"],
                estimate["protein"],
                estimate["carbs"],
                estimate["fat"],
                estimate["fibre"],
                estimate["confidence"],
                text,
            ),
        )
        await update.message.reply_text(f"{meal.title()} logged.\n\nEstimated:\n{estimate['calories']:.0f} kcal\n{estimate['protein']:.0f} g protein\n\n{fmt_status(conn)}")


async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    init_db()
    remember_chat(update)
    caption = update.message.caption or ""
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image = bytes(await file.download_as_bytearray())
    estimate = estimate_photo_meal(base64.b64encode(image).decode("ascii"), caption)
    now = datetime.now().astimezone()
    meal = detect_meal_type(caption, now.hour)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO meal_logs
              (user_id, timestamp, meal_type, telegram_message_id, estimated_calories, estimated_protein,
               estimated_carbs, estimated_fat, estimated_fibre, confidence, notes)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.isoformat(), meal, update.message.message_id, estimate["calories"], estimate["protein"],
                estimate.get("carbs"), estimate.get("fat"), estimate.get("fibre"), estimate.get("confidence", "ai-estimated"),
                estimate.get("notes", caption),
            ),
        )
        await update.message.reply_text(f"{meal.title()} logged.\n\nEstimated:\n{estimate['calories']:.0f} kcal\n{estimate['protein']:.0f} g protein\n\n{fmt_status(conn)}")


def main() -> None:
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required for the bot service")
    init_db()
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("today", today_cmd))
    app.add_handler(CommandHandler("plan", plan_cmd))
    app.add_handler(CommandHandler("scorecard", scorecard_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
