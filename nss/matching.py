"""所属门店 ↔ 门店清单：只按 DMS 所属门店编码匹配；区域只从 reportdb 读取。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

# load_supervisors 仅保留兼容导入，不再用于按名称/区域回退找督导
from nss.bitable import load_stores, load_supervisors

DEFAULT_DMS_REGION_DB = "/home/ubuntu/m-hero-run/data/reportdb/reportdb.sqlite3"
NO_REGION = "无区域"


def _norm_code(value: Any) -> str:
    return str(value or "").strip().upper()


def match_store(
    store_name: str,
    stores: list[dict[str, Any]] | None = None,
    store_code: str = "",
) -> dict[str, Any] | None:
    """只按店代码匹配；store_name 参数保留兼容，不参与匹配。"""
    code = _norm_code(store_code)
    if not code:
        return None
    stores = stores if stores is not None else load_stores()
    for store in stores:
        if _norm_code(store.get("code")) == code:
            return store
    return None


def supervisors_for_store(
    store: dict[str, Any] | None,
    delivery_store: str = "",
    region: str = "",
) -> list[dict[str, str]]:
    """只返回已匹配门店自身配置的督导，不再按名称/区域查督导表。"""
    people: list[dict[str, str]] = []
    seen: set[str] = set()
    for person in (store or {}).get("supervisors") or []:
        name = str(person.get("name") or "").strip()
        open_id = str(person.get("open_id") or "").strip()
        key = open_id or name
        if not key or key in seen:
            continue
        seen.add(key)
        people.append({"name": name, "open_id": open_id})
    return people


def _region_db_path(db_path: str | Path | None = None) -> Path:
    raw = str(db_path or os.getenv("NSS_DMS_REGION_DB") or DEFAULT_DMS_REGION_DB).strip()
    return Path(raw).expanduser()


def _read_region_rows(path: str) -> dict[str, str]:
    """只读打开 reportdb，读取 stores.code → stores.region；失败返回空表。"""
    regions: dict[str, str] = {}
    try:
        conn = sqlite3.connect("file:" + quote(path) + "?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT code, region FROM stores").fetchall()
        finally:
            conn.close()
    except (sqlite3.Error, OSError):
        return regions
    for code, region in rows:
        key = _norm_code(code)
        value = str(region or "").strip()
        if key and value and key not in regions:
            regions[key] = value
    return regions


def load_dms_regions(db_path: str | Path | None = None) -> dict[str, str]:
    """加载 DMS 门店区域映射（每次调用只读打开一次；批量场景用 enrich_vehicles 只加载一次）。"""
    path = _region_db_path(db_path)
    try:
        if not path.is_file():
            return {}
    except OSError:
        return {}
    return _read_region_rows(str(path.resolve()))


def dms_region(
    store_code: Any,
    regions: dict[str, str] | None = None,
    db_path: str | Path | None = None,
) -> str:
    """按店代码取 DMS 区域；无代码、无记录或区域为空时返回「无区域」。"""
    code = _norm_code(store_code)
    if not code:
        return NO_REGION
    if regions is None:
        regions = load_dms_regions(db_path)
    return str(regions.get(code) or "").strip() or NO_REGION


def enrich_vehicle(
    vehicle: dict[str, Any],
    stores: list[dict[str, Any]] | None = None,
    *,
    regions: dict[str, str] | None = None,
    region_db: str | Path | None = None,
) -> dict[str, Any]:
    stores = stores if stores is not None else load_stores()
    store = match_store("", stores, str(vehicle.get("store_code") or ""))
    if store is None:
        managers: list[dict[str, Any]] = []
        supervisors: list[dict[str, str]] = []
    else:
        managers = list(store.get("managers") or [])
        supervisors = supervisors_for_store(store)
    if regions is None:
        regions = load_dms_regions(region_db)
    manager_names = "、".join(p.get("name") or "" for p in managers if p.get("name"))
    return {
        **vehicle,
        "matched_store": (store or {}).get("name") or "",
        "region": dms_region(vehicle.get("store_code"), regions),
        "manager_name": manager_names,
        "managers": managers,
        "supervisors": supervisors,
        "match_method": "code" if store is not None else "none",
        "unmatched": store is None,
    }


def enrich_vehicles(
    vehicles: list[dict[str, Any]],
    stores: list[dict[str, Any]] | None = None,
    *,
    region_db: str | Path | None = None,
) -> list[dict[str, Any]]:
    """批量匹配：门店清单与区域表各加载一次。"""
    stores = stores if stores is not None else load_stores()
    regions = load_dms_regions(region_db)
    return [enrich_vehicle(vehicle, stores, regions=regions) for vehicle in vehicles]
