"""提醒资格规则：仅「全新M817」车系，试驾车除外。纯函数，不碰网络与数据文件。"""

from __future__ import annotations

import unicodedata
from typing import Any

DEFAULT_SERIES_NAMES = ["全新M817"]
DEFAULT_EXCLUDED_DATA_TYPES = ["试驾车"]


def normalize_text(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def mask_vin(vin: Any) -> str:
    text = str(vin or "")
    if len(text) <= 7:
        return text[:3] + "***" if text else ""
    return f"{text[:3]}***{text[-4:]}"


def _settings_lists(settings: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    cfg = (settings or {}).get("eligibility")
    cfg = cfg if isinstance(cfg, dict) else {}

    def _str_list(raw: Any, fallback: list[str]) -> list[str]:
        if isinstance(raw, str):
            raw = [raw]
        if not raw:
            raw = fallback
        return [normalize_text(x) for x in raw if normalize_text(x)]

    return (
        _str_list(cfg.get("series_names"), DEFAULT_SERIES_NAMES),
        _str_list(cfg.get("excluded_data_types"), DEFAULT_EXCLUDED_DATA_TYPES),
    )


def ineligible_reason(vehicle: dict[str, Any], settings: dict[str, Any] | None = None) -> str | None:
    """命中排除规则返回原因字符串，符合条件返回 None。"""
    series_names, excluded_types = _settings_lists(settings)
    series = normalize_text(vehicle.get("series_name"))
    if series_names and series not in series_names:
        return f"车系非{series_names[0]}"
    data_type = normalize_text(vehicle.get("data_type"))
    if data_type and data_type in excluded_types:
        return data_type
    return None
