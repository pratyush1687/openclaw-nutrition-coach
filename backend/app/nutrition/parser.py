from __future__ import annotations

import re
from datetime import datetime


def detect_meal_type(text: str, hour: int | None = None) -> str:
    lower = text.lower()
    for meal in ("breakfast", "lunch", "snack", "dinner"):
        if meal in lower:
            return meal
    h = hour if hour is not None else datetime.now().hour
    if h < 11:
        return "breakfast"
    if h < 16:
        return "lunch"
    if h < 19:
        return "snack"
    return "dinner"


def parse_weight(text: str) -> float | None:
    match = re.search(r"(?:weight|wt)?\s*(\d{2,3}(?:\.\d+)?)\s*(?:kg|kgs)?\b", text.lower())
    if not match:
        return None
    value = float(match.group(1))
    return value if 40 <= value <= 250 else None


def parse_steps(text: str) -> int | None:
    match = re.search(r"(\d{3,6})\s*(?:steps|step)\b", text.lower())
    return int(match.group(1)) if match else None


def parse_water(text: str) -> float | None:
    lower = text.lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:l|litre|liter|litres|liters)\b", lower)
    if match and "water" in lower:
        return float(match.group(1))
    return None


def parse_target_update(text: str) -> dict:
    lower = text.lower()
    if not any(word in lower for word in ("target", "calorie", "protein", "protien", "fibre", "fiber", "water", "steps", "permanent")):
        return {}
    updates = {}
    calories = re.search(r"(?:calories?|kcal)[^\d]{0,20}(\d{3,5})|(\d{3,5})\s*(?:calories?|kcal)", lower)
    if calories:
        updates["calories_kcal"] = int(next(group for group in calories.groups() if group))
    protein = re.search(r"(?:protein|protien)[^\d]{0,20}(\d{2,3})|(\d{2,3})\s*g?\s*(?:protein|protien)", lower)
    if protein:
        updates["protein_g"] = int(next(group for group in protein.groups() if group))
    fibre = re.search(r"(?:fibre|fiber)[^\d]{0,20}(\d{1,3})|(\d{1,3})\s*g?\s*(?:fibre|fiber)", lower)
    if fibre:
        updates["fibre_g"] = int(next(group for group in fibre.groups() if group))
    water = re.search(r"(?:water)[^\d]{0,20}(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:l|litres?|liters?)\s*(?:water)?", lower)
    if water and "water" in lower:
        updates["water_l"] = float(next(group for group in water.groups() if group))
    steps = re.search(r"(?:steps?)[^\d]{0,20}(\d{3,6})|(\d{3,6})\s*steps?", lower)
    if steps:
        updates["steps"] = int(next(group for group in steps.groups() if group))
    return updates


def looks_like_food_log(text: str) -> bool:
    lower = text.lower()
    food_words = {
        "ate", "had", "meal", "breakfast", "lunch", "dinner", "snack", "roti", "rotis",
        "egg", "eggs", "toast", "dal", "curd", "paneer", "tofu", "soy", "rice", "whey",
        "fruit", "sabzi", "vegetables", "salad", "poha", "upma", "idli", "dosa",
    }
    return any(word in lower for word in food_words)


def rough_macro_estimate(text: str) -> dict:
    lower = text.lower()
    calories = 0
    protein = 0
    carbs = 0
    fat = 0
    fibre = 0
    patterns = [
        (r"(\d+)\s*eggs?", 72, 6, 1, 5, 0),
        (r"(\d+)\s*egg whites?", 17, 4, 0, 0, 0),
        (r"(\d+)\s*rotis?", 110, 3, 22, 3, 3),
        (r"(\d+)\s*toast", 75, 3, 14, 1, 2),
        (r"(\d+)\s*scoops?\s*whey", 120, 24, 3, 2, 0),
    ]
    for pattern, kcal, pro, carb, f, fib in patterns:
        for match in re.finditer(pattern, lower):
            qty = int(match.group(1))
            calories += qty * kcal
            protein += qty * pro
            carbs += qty * carb
            fat += qty * f
            fibre += qty * fib
    keywords = [
        ("dal", 220, 14, 32, 4, 9),
        ("curd", 120, 10, 8, 4, 0),
        ("yogurt", 120, 10, 8, 4, 0),
        ("paneer", 300, 18, 8, 22, 0),
        ("tofu", 190, 22, 6, 10, 2),
        ("soy", 250, 28, 18, 8, 7),
        ("rice", 250, 5, 55, 1, 1),
        ("fruit", 100, 1, 25, 0, 4),
    ]
    for word, kcal, pro, carb, f, fib in keywords:
        if word in lower:
            calories += kcal
            protein += pro
            carbs += carb
            fat += f
            fibre += fib
    if calories == 0:
        calories = 500
        protein = 20
        carbs = 55
        fat = 18
        fibre = 6
    return {
        "calories": calories,
        "protein": protein,
        "carbs": carbs,
        "fat": fat,
        "fibre": fibre,
        "confidence": "rough-estimate",
    }
