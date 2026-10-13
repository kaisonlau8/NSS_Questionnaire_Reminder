"""控制台可改配置：全国收件人、偏移天数、调度开关。"""

from __future__ import annotations

import copy
from typing import Any

from nss.jsonutil import load_json, save_json
from nss.paths import SETTINGS_EXAMPLE_PATH, SETTINGS_PATH

DEFAULT_SETTINGS: dict[str, Any] = {
    "national_recipients": [
        {"name": "刘明轩", "phone": "", "open_id": ""},
        {"name": "胡进", "phone": "", "open_id": ""},
    ],
    "offset_days": 90,
    "remind_hour": 9,
    "remind_minute": 0,
    "scheduler_enabled": True,
    "skip_store_keywords": ["虚拟店", "出口车"],
    "exclusions": {
        "enabled": True,
        "series": ["917"],
        "data_types": ["试驾车"],
        "model_keyword_test_drive": True,
    },
}


def _normalize_recipients(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(raw, list):
        return copy.deepcopy(DEFAULT_SETTINGS["national_recipients"])
    for item in raw:
        if isinstance(item, str):
            name = item.strip()
            if name:
                out.append({"name": name, "phone": "", "open_id": ""})
            continue
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        phone = str(item.get("phone") or "").strip()
        open_id = str(item.get("open_id") or "").strip()
        if not name and not phone and not open_id:
            continue
        out.append({"name": name, "phone": phone, "open_id": open_id})
    return out


def _normalize_exclusions(raw: Any) -> dict[str, Any]:
    cfg = raw if isinstance(raw, dict) else {}
    defaults = DEFAULT_SETTINGS["exclusions"]

    def _str_list(value: Any, fallback: list[str]) -> list[str]:
        if isinstance(value, str):
            value = [value]
        if not value:
            value = fallback
        return [str(x).strip() for x in value if str(x or "").strip()]

    return {
        "enabled": bool(cfg.get("enabled", defaults["enabled"])),
        "series": _str_list(cfg.get("series"), defaults["series"]),
        "data_types": _str_list(cfg.get("data_types"), defaults["data_types"]),
        "model_keyword_test_drive": bool(
            cfg.get("model_keyword_test_drive", defaults["model_keyword_test_drive"])
        ),
    }


def load_settings() -> dict[str, Any]:
    raw = load_json(SETTINGS_PATH, None)
    if not isinstance(raw, dict):
        raw = load_json(SETTINGS_EXAMPLE_PATH, {})
        if not isinstance(raw, dict):
            raw = {}
    data = copy.deepcopy(DEFAULT_SETTINGS)
    data.update({k: v for k, v in raw.items() if k in DEFAULT_SETTINGS})
    data["national_recipients"] = _normalize_recipients(
        raw.get("national_recipients", data["national_recipients"])
    )
    default_oids = {
        p["name"]: p.get("open_id") or ""
        for p in DEFAULT_SETTINGS["national_recipients"]
        if p.get("name")
    }
    for item in data["national_recipients"]:
        if not item.get("open_id") and item.get("name"):
            item["open_id"] = default_oids.get(item["name"], "")
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
    keywords = data.get("skip_store_keywords") or DEFAULT_SETTINGS["skip_store_keywords"]
    if isinstance(keywords, str):
        keywords = [keywords]
    data["skip_store_keywords"] = [str(x).strip() for x in keywords if str(x).strip()]
    data["exclusions"] = _normalize_exclusions(raw.get("exclusions") or data["exclusions"])
    return data


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    merged = load_settings()
    if "national_recipients" in data:
        merged["national_recipients"] = _normalize_recipients(data["national_recipients"])
    for key in ("offset_days", "remind_hour", "remind_minute"):
        if key in data:
            merged[key] = int(data[key])
    if "scheduler_enabled" in data:
        merged["scheduler_enabled"] = bool(data["scheduler_enabled"])
    if "skip_store_keywords" in data:
        merged["skip_store_keywords"] = data["skip_store_keywords"]
    if "exclusions" in data:
        merged["exclusions"] = _normalize_exclusions(data["exclusions"])
    save_json(SETTINGS_PATH, merged)
    return load_settings()
