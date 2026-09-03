from __future__ import annotations

import json

from openai import OpenAI

from app.config import env, load_config
from app.nutrition.parser import rough_macro_estimate


def estimate_text_meal(text: str) -> dict:
    if not env("OPENAI_API_KEY"):
        return {**rough_macro_estimate(text), "notes": text}
    cfg = load_config()
    client = OpenAI(api_key=env("OPENAI_API_KEY"))
    model = env("OPENAI_MODEL", "gpt-5.1-mini")
    prompt = {
        "task": "Estimate nutrition for a user's logged meal text.",
        "meal_text": text,
        "diet_context": cfg.get("preferences", {}),
        "instructions": [
            "Return only JSON.",
            "Fields: calories, protein, carbs, fat, fibre, confidence, notes, items.",
            "Use Indian home-food assumptions when relevant.",
            "Clearly treat values as estimates unless serving sizes are explicit.",
            "Do not moralize food choices.",
        ],
    }
    response = client.responses.create(
        model=model,
        input=[{"role": "user", "content": json.dumps(prompt)}],
    )
    try:
        data = json.loads(response.output_text.strip())
    except json.JSONDecodeError:
        return {**rough_macro_estimate(text), "notes": response.output_text[:500], "confidence": "ai-estimated"}
    return {
        "calories": float(data.get("calories", 0)),
        "protein": float(data.get("protein", 0)),
        "carbs": float(data.get("carbs", 0)),
        "fat": float(data.get("fat", 0)),
        "fibre": float(data.get("fibre", 0)),
        "confidence": data.get("confidence", "ai-estimated"),
        "notes": data.get("notes", text),
        "items": data.get("items", []),
    }
