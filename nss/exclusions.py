"""提醒排除规则：917 车系、试驾车。纯函数，不碰网络与数据文件。"""

from __future__ import annotations

import unicodedata
from typing import Any

SERIES_FIELDS = ("series_name", "series", "aftersales_series")


def normalize_series(value: Any) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKC", text)
    text = "".join(text.split()).upper()
    if text.startswith("猛士"):
        text = text[2:]
    return text


def series_matches(value: Any, target: Any) -> bool:
    normalized = normalize_series(value)
    want = normalize_series(target)
    if not normalized or not want:
        return False
    return normalized == want or normalized.startswith((f"{want}-", f"{want} ", f"{want}("))


def mask_vin(vin: Any) -> str:
    text = str(vin or "")
    if len(text) <= 7:
        return text[:3] + "***" if text else ""
    return f"{text[:3]}***{text[-4:]}"


def exclusion_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    cfg = (settings or {}).get("exclusions")
    return cfg if isinstance(cfg, dict) else {}


def _data_types(cfg: dict[str, Any]) -> list[str]:
    return [str(x).strip() for x in cfg.get("data_types") or [] if str(x).strip()]


def exclusion_reason(vehicle: dict[str, Any], settings: dict[str, Any] | None) -> str | None:
    cfg = exclusion_settings(settings)
    if not cfg.get("enabled", True):
        return None
    for field in SERIES_FIELDS:
        raw = str(vehicle.get(field) or "").strip()
        if not raw:
            continue
        for target in cfg.get("series") or []:
            if series_matches(raw, target):
                return f"车系{normalize_series(target)}"
    data_type = str(vehicle.get("data_type") or "").strip()
    for want in _data_types(cfg):
        if data_type == want:
            return want
    if cfg.get("model_keyword_test_drive", True):
        model = str(vehicle.get("model") or "")
        for want in _data_types(cfg):
            if want and want in model:
                return want
    return None
