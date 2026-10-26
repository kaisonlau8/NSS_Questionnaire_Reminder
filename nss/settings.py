"""控制台可改配置：资格规则、偏移天数、调度开关。"""

from __future__ import annotations

import copy
import os
import re
from typing import Any

from nss.jsonutil import load_json, save_json
from nss.paths import SETTINGS_EXAMPLE_PATH, SETTINGS_PATH

DEFAULT_SETTINGS: dict[str, Any] = {
    "offset_days": 89,
    "remind_hour": 9,
    "remind_minute": 0,
    "scheduler_enabled": True,
    "eligibility": {
        "series_names": ["全新M817"],
        "excluded_data_types": ["试驾车"],
    },
    "public_base_url": "",
    "weekly_report": {
        "enabled": False,
        "weekday": 0,
        "hour": 9,
        "minute": 30,
        "chat_id": "oc_ba8af247db2e2dc4955b1d01652add82",
        "dry_run": True,
        "link_base": "",
        "source": {
            "app_token": "J0BBb0z2ua4bzEs7gumc0YQXn80",
            "table_id": "tblc8vCaxiWyi64Y",
            "view_id": "vewRnrIcmG",
        },
        "filters": {
            "type_field": "问卷类型",
            "type_value": "NPS调研",
            "period_field": "调研时间",
            "period_value": "90天",
            "combined_value": "NPS调研-90天",
            "combined_fields": ["问卷类型", "调研时间", "问卷名称"],
        },
        "nps_field": "",
    },
}


def validate_weekly_report_schedule(config: dict[str, Any]) -> None:
    """周一为 0；每天固定任务前后 5 分钟（含端点、跨午夜）禁止运行周报。"""
    values = {}
    for key, upper in (("weekday", 6), ("hour", 23), ("minute", 59)):
        raw = config.get(key, DEFAULT_SETTINGS["weekly_report"][key])
        if isinstance(raw, bool) or not isinstance(raw, (int, str)) or not re.fullmatch(r"\d+", str(raw)):
            raise ValueError(f"weekly_report.{key} 必须是 0~{upper} 的整数")
        value = int(raw)
        if not 0 <= value <= upper:
            raise ValueError(f"weekly_report.{key} 必须是 0~{upper} 的整数")
        values[key] = value
    minute_of_day = values["hour"] * 60 + values["minute"]
    for reserved in (0, 8 * 60 + 30, 9 * 60, 12 * 60):
        distance = abs(minute_of_day - reserved)
        if min(distance, 1440 - distance) <= 5:
            raise ValueError("周报时间必须避开 00:00、08:30、09:00、12:00 前后 5 分钟（含端点）")


def normalize_weekly_report_settings(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("weekly_report 必须是配置对象")
    cfg = copy.deepcopy(DEFAULT_SETTINGS["weekly_report"])
    for key in cfg:
        if key not in raw:
            continue
        if key in ("source", "filters"):
            if not isinstance(raw[key], dict):
                raise ValueError(f"weekly_report.{key} 必须是配置对象")
            cfg[key].update({k: v for k, v in raw[key].items() if k in cfg[key]})
        else:
            cfg[key] = raw[key]
    for key in ("enabled", "dry_run"):
        if not isinstance(cfg[key], bool):
            raise ValueError(f"weekly_report.{key} 必须是 true 或 false")
    validate_weekly_report_schedule(cfg)
    for key in ("weekday", "hour", "minute"):
        cfg[key] = int(cfg[key])
    for key in ("chat_id", "link_base", "nps_field"):
        cfg[key] = str(cfg[key] or "").strip()
    for key, value in cfg["source"].items():
        cfg["source"][key] = str(value or "").strip()
        if key != "view_id" and not cfg["source"][key]:
            raise ValueError(f"weekly_report.source.{key} 不能为空")
    for key, value in cfg["filters"].items():
        if key == "combined_fields":
            if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ValueError("weekly_report.filters.combined_fields 必须是字段名列表")
            cfg["filters"][key] = [v.strip() for v in value]
        elif not isinstance(value, str) or not value.strip():
            raise ValueError(f"weekly_report.filters.{key} 必须是非空文本")
        else:
            cfg["filters"][key] = value.strip()
    return cfg


def _weekly_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    cfg = copy.deepcopy(config)
    for key in ("app_token", "table_id", "view_id"):
        value = os.getenv(f"NSS_WEEKLY_BITABLE_{key.upper()}")
        if value is not None:
            cfg["source"][key] = value.strip()
    for key in ("chat_id", "link_base"):
        value = os.getenv(f"NSS_WEEKLY_{key.upper()}")
        if value is not None:
            cfg[key] = value.strip()
    return normalize_weekly_report_settings(cfg)


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
        data["offset_days"] = max(1, int(data.get("offset_days") or 89))
    except (TypeError, ValueError):
        data["offset_days"] = 89
    try:
        data["remind_hour"] = min(23, max(0, int(data.get("remind_hour") or 9)))
        data["remind_minute"] = min(59, max(0, int(data.get("remind_minute") or 0)))
    except (TypeError, ValueError):
        data["remind_hour"] = 9
        data["remind_minute"] = 0
    data["scheduler_enabled"] = bool(data.get("scheduler_enabled", True))
    data["eligibility"] = _normalize_eligibility(raw.get("eligibility") or data["eligibility"])
    data["public_base_url"] = str(os.getenv("NSS_PUBLIC_BASE_URL", data["public_base_url"]) or "").strip()
    data["weekly_report"] = _weekly_env_overrides(normalize_weekly_report_settings(data["weekly_report"]))
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
    if "public_base_url" in data:
        merged["public_base_url"] = str(data["public_base_url"] or "").strip()
    if "weekly_report" in data:
        raw = data["weekly_report"]
        if not isinstance(raw, dict):
            raise ValueError("weekly_report 必须是配置对象")
        weekly = copy.deepcopy(merged["weekly_report"])
        for key, value in raw.items():
            if key in ("source", "filters") and isinstance(value, dict):
                weekly[key].update(value)
            else:
                weekly[key] = value
        merged["weekly_report"] = normalize_weekly_report_settings(weekly)
    save_json(SETTINGS_PATH, merged)
    return load_settings()
