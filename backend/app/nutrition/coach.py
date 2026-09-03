from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import default_targets, load_config
from app.database import connect, init_db


def now_local(cfg: dict | None = None) -> datetime:
    config = cfg or load_config()
    return datetime.now(ZoneInfo(config.get("timezone", "Asia/Kolkata")))


def today() -> str:
    return now_local().date().isoformat()


def current_targets(conn, user_id: int = 1) -> dict:
    row = conn.execute(
        "SELECT * FROM daily_targets WHERE user_id=? ORDER BY effective_date DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if row is None:
        cfg = load_config()
        targets = default_targets(cfg)
        return {
            "user_id": user_id,
            "calories_kcal": targets["calories_kcal"],
            "protein_g": targets["protein_g"],
            "fibre_g": targets["fibre_g"],
            "water_l": targets["water_l"],
            "steps": targets["steps"],
        }
    return dict(row)


def totals_for_date(conn, date_text: str, user_id: int = 1) -> dict:
    meal = conn.execute(
        """
        SELECT COALESCE(SUM(estimated_calories),0) calories,
               COALESCE(SUM(estimated_protein),0) protein,
               COALESCE(SUM(estimated_carbs),0) carbs,
               COALESCE(SUM(estimated_fat),0) fat,
               COALESCE(SUM(estimated_fibre),0) fibre,
               COUNT(*) meals
        FROM meal_logs
        WHERE user_id=? AND date(timestamp)=? AND skipped=0
        """,
        (user_id, date_text),
    ).fetchone()
    water = conn.execute(
        "SELECT COALESCE(SUM(litres),0) water FROM water_logs WHERE user_id=? AND date(logged_at)=?",
        (user_id, date_text),
    ).fetchone()
    steps = conn.execute(
        "SELECT COALESCE(MAX(steps),0) steps FROM step_logs WHERE user_id=? AND date(logged_at)=?",
        (user_id, date_text),
    ).fetchone()
    workouts = conn.execute(
        "SELECT COUNT(*) workouts FROM workout_logs WHERE user_id=? AND date(logged_at)=? AND completed=1",
        (user_id, date_text),
    ).fetchone()
    return {**dict(meal), **dict(water), **dict(steps), **dict(workouts)}


def weight_trend(conn, user_id: int = 1) -> str:
    rows = conn.execute(
        "SELECT weight_kg FROM weight_logs WHERE user_id=? ORDER BY logged_at DESC LIMIT 14",
        (user_id,),
    ).fetchall()
    if len(rows) < 2:
        return "Not enough weight data yet."
    latest = rows[0]["weight_kg"]
    older = rows[-1]["weight_kg"]
    diff = latest - older
    if abs(diff) < 0.2:
        return f"Recent weight is broadly stable around {latest:.1f} kg."
    direction = "down" if diff < 0 else "up"
    return f"Recent weight trend is {direction} {abs(diff):.1f} kg from available logs."


def latest_weight_today(conn, date_text: str, user_id: int = 1) -> bool:
    row = conn.execute(
        "SELECT 1 FROM weight_logs WHERE user_id=? AND date(logged_at)=? LIMIT 1",
        (user_id, date_text),
    ).fetchone()
    return row is not None


def yesterday_note(conn, target_kcal: int, user_id: int = 1) -> str:
    yesterday = (now_local().date() - timedelta(days=1)).isoformat()
    totals = totals_for_date(conn, yesterday, user_id)
    if totals["calories"] > target_kcal * 1.2:
        return "Yesterday was high-calorie. Fine. No starvation tax today; resume the normal target."
    if totals["calories"] == 0:
        return "Yesterday has no meal logs yet."
    return f"Yesterday: {totals['calories']:.0f} kcal, {totals['protein']:.0f} g protein."


def known_food_hint(conn, user_id: int = 1) -> str:
    rows = conn.execute(
        """
        SELECT name, serving_description, calories, protein
        FROM known_foods
        WHERE user_id IN (0, ?)
        ORDER BY times_seen DESC, updated_at DESC
        LIMIT 3
        """,
        (user_id,),
    ).fetchall()
    if not rows:
        return "No confirmed repeat meals yet."
    bits = []
    for row in rows:
        serving = f" ({row['serving_description']})" if row["serving_description"] else ""
        bits.append(f"{row['name']}{serving}: {row['calories']:.0f} kcal/{row['protein']:.0f} g protein")
    return "Known foods: " + "; ".join(bits)


def morning_plan(user_id: int = 1) -> str:
    init_db()
    cfg = load_config()
    with connect() as conn:
        targets = current_targets(conn, user_id)
        user = conn.execute("SELECT name FROM users WHERE id=?", (user_id,)).fetchone()
        name = user["name"] if user else "there"
        date_text = today()
        weight_line = "Weight logged today." if latest_weight_today(conn, date_text, user_id) else "Weight? Log it when you wake up."
        workout = conn.execute(
            "SELECT workout_type, notes FROM workout_logs WHERE user_id=? AND date(logged_at)=? ORDER BY logged_at DESC LIMIT 1",
            (user_id, date_text),
        ).fetchone()
        workout_line = workout["workout_type"] if workout else "Strength training if planned"
        target_kcal = int(targets["calories_kcal"])
        target_protein = int(targets["protein_g"])
        flex = 300
        meals = [
            ("Breakfast", "2 eggs + 4 egg whites, 2 toast, tea", 430, 35),
            ("Lunch", "2 rotis, dal, 200 g low-fat curd, soy/tofu sabzi", 650, 42),
            ("Snack", "Whey + fruit", 250, 28),
            ("Dinner", "Tofu/paneer alternative, vegetables, 1-2 rotis", 700, 48),
        ]
        lines = [
            f"GOOD MORNING {name.upper()} - TODAY'S PLAN",
            "",
            "Morning check-in:",
            weight_line,
            f"Today's target: {target_kcal} kcal / {target_protein} g protein",
            f"Steps: {targets['steps']:,}",
            f"Water: {targets['water_l']:g} L",
            f"Workout: {workout_line}",
            "",
            "Context:",
            yesterday_note(conn, target_kcal, user_id),
            weight_trend(conn, user_id),
            known_food_hint(conn, user_id),
            "",
            "Meal plan:",
        ]
        for name, food, kcal, protein in meals:
            lines.extend(["", name, food, f"~{kcal} kcal | {protein} g protein"])
        lines.extend(
            [
                "",
                f"Flexible calories: ~{flex} kcal",
                "",
                f"Main goal today: {cfg['coach']['morning_goal']}",
                "This is a starting plan. If you eat differently, log it and I will recalculate. No drama.",
            ]
        )
        return "\n".join(lines)


def scorecard(user_id: int = 1) -> str:
    init_db()
    with connect() as conn:
        targets = current_targets(conn, user_id)
        totals = totals_for_date(conn, today(), user_id)
        meals_logged = int(totals["meals"])
        content = "\n".join(
            [
                "DAILY SCORECARD",
                "",
                f"Calories: {totals['calories']:.0f} / {targets['calories_kcal']} kcal",
                f"Protein: {totals['protein']:.0f} / {targets['protein_g']} g",
                f"Carbs: {totals['carbs']:.0f} g",
                f"Fat: {totals['fat']:.0f} g",
                f"Fibre: {totals['fibre']:.0f} / {targets['fibre_g']} g",
                f"Water: {totals['water']:.1f} / {targets['water_l']:g} L",
                f"Steps: {int(totals['steps']):,} / {int(targets['steps']):,}",
                f"Workout: {'done' if totals['workouts'] else 'not logged'}",
                f"Meals logged: {meals_logged}/4",
                "",
                "Tomorrow: hit protein early. Future-you is easier to negotiate with after breakfast.",
            ]
        )
        conn.execute(
            """
            INSERT INTO daily_summaries (user_id, summary_date, content)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, summary_date) DO UPDATE SET content=excluded.content
            """,
            (user_id, today(), content),
        )
        return content


def weekly_summary(user_id: int = 1) -> str:
    init_db()
    with connect() as conn:
        end = now_local().date()
        start = end - timedelta(days=6)
        prev_start = start - timedelta(days=7)
        prev_end = start - timedelta(days=1)
        weights = conn.execute(
            "SELECT AVG(weight_kg) avg_weight FROM weight_logs WHERE user_id=? AND date(logged_at) BETWEEN ? AND ?",
            (user_id, start.isoformat(), end.isoformat()),
        ).fetchone()["avg_weight"]
        prev_weights = conn.execute(
            "SELECT AVG(weight_kg) avg_weight FROM weight_logs WHERE user_id=? AND date(logged_at) BETWEEN ? AND ?",
            (user_id, prev_start.isoformat(), prev_end.isoformat()),
        ).fetchone()["avg_weight"]
        meals = conn.execute(
            "SELECT COUNT(*) c FROM meal_logs WHERE user_id=? AND skipped=0 AND date(timestamp) BETWEEN ? AND ?",
            (user_id, start.isoformat(), end.isoformat()),
        ).fetchone()["c"]
        protein_days = 0
        calories = []
        protein = []
        targets = current_targets(conn, user_id)
        for i in range(7):
            date_text = (start + timedelta(days=i)).isoformat()
            totals = totals_for_date(conn, date_text, user_id)
            calories.append(totals["calories"])
            protein.append(totals["protein"])
            if totals["protein"] >= targets["protein_g"] * 0.9:
                protein_days += 1
        change = "Need another week of weight logs."
        if weights is not None and prev_weights is not None:
            change = f"{weights - prev_weights:+.1f} kg versus previous week"
        return "\n".join(
            [
                "WEEKLY CHECK-IN",
                "",
                f"Average weight: {weights:.1f} kg" if weights is not None else "Average weight: not enough data",
                f"Previous week: {prev_weights:.1f} kg" if prev_weights is not None else "Previous week: not enough data",
                f"Change: {change}",
                f"Average calories: {sum(calories) / 7:.0f} kcal",
                f"Average protein: {sum(protein) / 7:.0f} g",
                f"Protein adherence: {protein_days}/7 days",
                f"Meal logging adherence: {min(100, meals / 28 * 100):.0f}%",
                "",
                "Recommendation: keep calories unchanged unless the weekly trend stalls for long enough to matter.",
            ]
        )
