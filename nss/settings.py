"""控制台可改配置：资格规则、偏移天数、调度开关。"""

from __future__ import annotations

import copy
from typing import Any

from nss.jsonutil import load_json, save_json
from nss.paths import SETTINGS_EXAMPLE_PATH, SETTINGS_PATH

DEFAULT_SETTINGS: dict[str, Any] = {
    "offset_days": 90,
    "remind_hour": 9,
    "remind_minute": 0,
    "scheduler_enabled": True,
    "eligibility": {
        "series_names": ["全新M817"],
        "excluded_data_types": ["试驾车"],
    },
}


def _normalize_eligibility(raw: Any) -> dict[str, Any]:
    cfg = raw if isinstance(raw, dict) else {}
    defaults = DEFAULT_SETTINGS["eligibility"]

    def _str_list(value: Any, fallback: list[str]) -> list[str]:
        if isinstance(value, str):
            value = [value]
        if not value:
            value = fallback
        return [str(x).strip() for x in value if str(x or "").strip()]

    return {
        "series_names": _str_list(cfg.get("series_names"), defaults["series_names"]),
        "excluded_data_types": _str_list(cfg.get("excluded_data_types"), defaults["excluded_data_types"]),
    }


def load_settings() -> dict[str, Any]:
    raw = load_json(SETTINGS_PATH, None)
    if not isinstance(raw, dict):
        raw = load_json(SETTINGS_EXAMPLE_PATH, {})
        if not isinstance(raw, dict):
            raw = {}
    data = copy.deepcopy(DEFAULT_SETTINGS)
    data.update({k: v for k, v in raw.items() if k in DEFAULT_SETTINGS})
    try:
        data["offset_days"] = max(1, int(data.get("offset_days") or 90))
    except (TypeError, ValueError):
        data["offset_days"] = 90
    try:
        data["remind_hour"] = min(23, max(0, int(data.get("remind_hour") or 9)))
        data["remind_minute"] = min(59, max(0, int(data.get("remind_minute") or 0)))
    except (TypeError, ValueError):
        data["remind_hour"] = 9
        data["remind_minute"] = 0
    data["scheduler_enabled"] = bool(data.get("scheduler_enabled", True))
    data["eligibility"] = _normalize_eligibility(raw.get("eligibility") or data["eligibility"])
    return data


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    merged = load_settings()
    for key in ("offset_days", "remind_hour", "remind_minute"):
        if key in data:
            merged[key] = int(data[key])
    if "scheduler_enabled" in data:
        merged["scheduler_enabled"] = bool(data["scheduler_enabled"])
    if "eligibility" in data:
        merged["eligibility"] = _normalize_eligibility(data["eligibility"])
    save_json(SETTINGS_PATH, merged)
    return load_settings()
