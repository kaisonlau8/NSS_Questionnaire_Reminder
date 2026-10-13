"""车辆档案 Excel 导入（新版「客户车辆关系」导出，兼容旧交付档案格式）。"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from nss.jsonutil import load_json, save_json
from nss.paths import DATASOURCE_DIR, ROOT, UPLOAD_DIR, VEHICLES_PATH
from nss.settings import load_settings
from nss.time_utils import beijing_strftime, beijing_today

# 新版「客户车辆关系」导出：创建时间即交付日期
NEW_FORMAT_MARKERS = ("创建时间", "交付门店名称")
NEW_REQUIRED_HEADERS = ("VIN", "车系名称", "创建时间", "交付门店名称")
# 旧版「车辆交付档案」
OLD_REQUIRED_HEADERS = ("VIN", "交付日期", "交付门店")
OLD_OPTIONAL_MAP = {
    "车牌号": "plate",
    "车系": "series",
    "车系名称": "series_name",
    "车型": "model",
    "售后车系": "aftersales_series",
    "数据类型": "data_type",
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


def _header_map(headers: list[Any]) -> dict[str, int]:
    idx: dict[str, int] = {}
    for i, raw in enumerate(headers):
        name = str(raw or "").strip()
        if name and name not in idx:
            idx[name] = i
    return idx


def _cell(row: tuple[Any, ...], idx: dict[str, int], header: str) -> str:
    if header not in idx:
        return ""
    return str(row[idx[header]] or "").strip()


def _sheet(wb):
    for ws in wb.worksheets:
        if str(ws.title).startswith("客户车辆关系"):
            return ws
    return wb.active


def parse_excel(path: Path) -> dict[str, Any]:
    """解析 Excel，返回 {"vehicles": [...], "stats": {total, imported, skipped_no_date, duplicates}}。

    新旧格式都只保留非个人信息字段；资格规则（车系/数据类型）不在导入时过滤，
    到期发送时再判定（见 nss/eligibility.py）。
    """
    wb = load_workbook(path, data_only=True)
    try:
        ws = _sheet(wb)
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()
    if not rows:
        raise ValueError("Excel 为空")
    idx = _header_map(list(rows[0]))
    new_format = any(marker in idx for marker in NEW_FORMAT_MARKERS)
    required = NEW_REQUIRED_HEADERS if new_format else OLD_REQUIRED_HEADERS
    missing = [h for h in required if h not in idx]
    if missing:
        raise ValueError("Excel 缺少列: " + "、".join(missing) + f"。当前表头: {list(idx)}")
    date_header = "创建时间" if new_format else "交付日期"
    offset_days = int(load_settings()["offset_days"])
    vehicles: list[dict[str, Any]] = []
    stats = {"total": 0, "imported": 0, "skipped_no_date": 0, "duplicates": 0}
    seen: set[str] = set()
    for row in rows[1:]:
        if not row or not any(str(c or "").strip() for c in row):
            continue
        stats["total"] += 1
        vin = str(row[idx["VIN"]] or "").strip().upper()
        if not vin:
            continue
        delivery = parse_delivery_date(row[idx[date_header]])
        if not delivery:
            stats["skipped_no_date"] += 1
            continue
        if vin in seen:
            stats["duplicates"] += 1
            continue
        seen.add(vin)
        item: dict[str, Any] = {
            "vin": vin,
            "delivery_date": delivery.isoformat(),
            "due_date": due_date_for(delivery, offset_days).isoformat(),
            "store": "",
            "store_code": "",
            "plate": "",
            "series": "",
            "series_name": "",
            "model": "",
            "aftersales_series": "",
            "data_type": "",
        }
        if new_format:
            item.update(
                {
                    "store": _cell(row, idx, "交付门店名称") or _cell(row, idx, "所属门店名称"),
                    "store_code": _cell(row, idx, "交付门店编码"),
                    "plate": _cell(row, idx, "车牌号"),
                    "series_name": _cell(row, idx, "车系名称"),
                    "aftersales_series": _cell(row, idx, "售后车系"),
                    "model": _cell(row, idx, "车型名称"),
                    "data_type": _cell(row, idx, "数据类型"),
                }
            )
        else:
            item["store"] = _cell(row, idx, "交付门店")
            for header, key in OLD_OPTIONAL_MAP.items():
                if header in idx:
                    item[key] = _cell(row, idx, header)
        vehicles.append(item)
        stats["imported"] += 1
    return {"vehicles": vehicles, "stats": stats}


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
    parsed = parse_excel(path)
    payload = save_vehicles(parsed["vehicles"], source=str(path))
    payload["stats"] = parsed["stats"]
    return payload
