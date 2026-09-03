from __future__ import annotations

import json

from openai import OpenAI

from app.config import env
from app.nutrition.parser import rough_macro_estimate


def estimate_photo_meal(image_b64: str, caption: str = "") -> dict:
    if not env("OPENAI_API_KEY"):
        return {**rough_macro_estimate(caption or "meal photo"), "notes": "OpenAI key missing; used rough fallback estimate."}
    client = OpenAI(api_key=env("OPENAI_API_KEY"))
    model = env("OPENAI_VISION_MODEL", "gpt-5.1")
    prompt = (
        "Estimate nutrition for this meal photo. Return only JSON with calories, protein, carbs, fat, fibre, "
        "confidence, notes. Be honest about uncertainty. Caption: " + caption
    )
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{image_b64}"},
                ],
            }
        ],
    )
    text = response.output_text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {**rough_macro_estimate(caption or text), "notes": text[:500], "confidence": "ai-estimated"}
    return {
        "calories": float(data.get("calories", 0)),
        "protein": float(data.get("protein", 0)),
        "carbs": float(data.get("carbs", 0)),
        "fat": float(data.get("fat", 0)),
        "fibre": float(data.get("fibre", 0)),
        "confidence": data.get("confidence", "ai-estimated"),
        "notes": data.get("notes", "AI-estimated from meal photo."),
    }
