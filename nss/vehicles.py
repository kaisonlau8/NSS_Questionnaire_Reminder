"""车辆档案 Excel 导入。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from nss.jsonutil import load_json, save_json
from nss.paths import DATASOURCE_DIR, ROOT, UPLOAD_DIR, VEHICLES_PATH
from nss.settings import load_settings
from nss.time_utils import beijing_strftime, beijing_today

REQUIRED_HEADERS = ("VIN", "交付日期", "交付门店")
OPTIONAL_MAP = {
    "车牌号": "plate",
    "车系": "series",
    "车型": "model",
    "售后车系": "aftersales_series",
}


def parse_delivery_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.split()[0][:10]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def due_date_for(delivery: date, offset_days: int | None = None) -> date:
    days = offset_days if offset_days is not None else int(load_settings()["offset_days"])
    return delivery + timedelta(days=days)


def _header_index(headers: list[Any]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for i, raw in enumerate(headers):
        name = str(raw or "").strip()
        if name:
            idx[name] = i
    missing = [h for h in REQUIRED_HEADERS if h not in idx]
    if missing:
        raise ValueError("Excel 缺少列: " + "、".join(missing) + f"。当前表头: {list(idx)}")
    return idx


def parse_excel(path: Path) -> list[dict[str, Any]]:
    wb = load_workbook(path, data_only=True)
    try:
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        raise ValueError("Excel 为空")
    idx = _header_index(list(rows[0]))
    offset_days = int(load_settings()["offset_days"])
    vehicles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows[1:]:
        if not row:
            continue
        vin = str(row[idx["VIN"]] or "").strip().upper()
        if not vin or vin in seen:
            continue
        delivery = parse_delivery_date(row[idx["交付日期"]])
        if not delivery:
            continue
        seen.add(vin)
        item = {
            "vin": vin,
            "delivery_date": delivery.isoformat(),
            "due_date": due_date_for(delivery, offset_days).isoformat(),
            "store": str(row[idx["交付门店"]] or "").strip(),
            "plate": "",
            "series": "",
            "model": "",
        }
        for header, key in OPTIONAL_MAP.items():
            if header in idx:
                item[key] = str(row[idx[header]] or "").strip()
        vehicles.append(item)
    return vehicles


def save_vehicles(vehicles: list[dict[str, Any]], *, source: str) -> dict[str, Any]:
    payload = {
        "imported_at": beijing_strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "count": len(vehicles),
        "vehicles": vehicles,
    }
    save_json(VEHICLES_PATH, payload)
    return payload


def load_vehicles() -> list[dict[str, Any]]:
    data = load_json(VEHICLES_PATH, {})
    return data.get("vehicles") or []


def vehicles_meta() -> dict[str, Any]:
    data = load_json(VEHICLES_PATH, {})
    return {
        "imported_at": data.get("imported_at") or "",
        "source": data.get("source") or "",
        "count": int(data.get("count") or len(data.get("vehicles") or [])),
    }


def due_on(day: date | None = None) -> list[dict[str, Any]]:
    target = (day or beijing_today()).isoformat()
    return [v for v in load_vehicles() if v.get("due_date") == target]


def next_due_date() -> str:
    today = beijing_today().isoformat()
    dates = sorted({v.get("due_date") or "" for v in load_vehicles() if (v.get("due_date") or "") >= today})
    return dates[0] if dates else ""


def find_seed_excel() -> Path | None:
    candidates: list[Path] = []
    for folder in (UPLOAD_DIR, DATASOURCE_DIR, ROOT):
        if not folder.exists():
            continue
        candidates.extend(sorted(folder.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True))
    return candidates[0] if candidates else None


def import_excel(path: Path) -> dict[str, Any]:
    vehicles = parse_excel(path)
    return save_vehicles(vehicles, source=str(path))
