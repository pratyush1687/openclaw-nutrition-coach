from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path("/app/config/coach.yaml")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path or os.getenv("COACH_CONFIG", str(DEFAULT_CONFIG_PATH)))
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def default_targets(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "calories_kcal": 2000,
        "protein_g": 100,
        "fibre_g": 30,
        "water_l": 2.5,
        "steps": 8000,
        **(cfg.get("defaults", {}).get("targets", {}) or {}),
    }


def configured_users(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    users = cfg.get("users")
    if isinstance(users, list):
        return users

    legacy_user = cfg.get("user", {}) or {}
    legacy_targets = cfg.get("targets", {}) or {}
    return [
        {
            "id": 1,
            "name": legacy_user.get("name", "Primary User"),
            "timezone": cfg.get("timezone", "Asia/Kolkata"),
            "age": legacy_user.get("age"),
            "sex": legacy_user.get("sex"),
            "height_cm": legacy_user.get("height_cm"),
            "starting_weight_kg": legacy_user.get("starting_weight_kg"),
            "goal_weight_kg": legacy_user.get("goal_weight_kg"),
            "telegram_user_id": legacy_user.get("telegram_user_id"),
            "role": legacy_user.get("role", "primary"),
            "targets": {**default_targets(cfg), **legacy_targets},
            "preferences": cfg.get("preferences", {}) or {},
        }
    ]


def env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    return value if value not in ("", None) else default
