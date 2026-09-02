"""同步门店清单与督导表。"""

from __future__ import annotations

import os
from typing import Any

import requests
from dotenv import load_dotenv

from nss.feishu_client import BASE_URL, app_id, auth_headers, resolve_phone_to_open_id
from nss.jsonutil import load_json, save_json
from nss.paths import ROOT, STORES_PATH, SUPERVISORS_PATH, SYNC_STATE_PATH
from nss.time_utils import beijing_strftime, ensure_beijing_tz

ensure_beijing_tz()
load_dotenv(ROOT / ".env")

STORE_NAME_KEYS = ("门店名称", "交付门店", "门店", "店名", "用户中心")
MANAGER_KEYS = ("门店服务经理", "服务经理", "售后服务经理", "服务顾问经理")
SUPERVISOR_KEYS = ("服务督导", "督导", "区域督导", "售后督导")
REGION_KEYS = ("区域", "战区", "大区")
CODE_KEYS = ("门店编码", "店代码", "编码")
ALIAS_KEYS = ("门店全称", "原门店名称")
PERSON_KEYS = ("督导", "督导姓名", "姓名", "提醒人", "人员")
STORE_LINK_KEYS = ("门店", "负责门店", "门店名称", "交付门店")
MANAGER_PHONE_KEYS = ("服务经理电话", "经理电话")
SUPERVISOR_PHONE_KEYS = ("督导飞书电话号", "飞书电话号", "督导电话", "电话")


def _bitable_ids() -> dict[str, str]:
    cfg = {
        "app_token": os.getenv("BITABLE_APP_TOKEN", "").strip(),
        "store_table_id": os.getenv("BITABLE_STORE_TABLE_ID", "").strip(),
        "store_view_id": os.getenv("BITABLE_STORE_VIEW_ID", "").strip(),
        "supervisor_table_id": os.getenv("BITABLE_SUPERVISOR_TABLE_ID", "").strip(),
        "supervisor_view_id": os.getenv("BITABLE_SUPERVISOR_VIEW_ID", "").strip(),
    }
    missing = [k for k, v in cfg.items() if not v and not k.endswith("view_id")]
    if missing:
        raise RuntimeError("缺少多维表配置: " + ", ".join(missing))
    return cfg


def field_text(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value)
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            text = field_text(item)
            if text:
                parts.append(text)
        return "、".join(parts)
    if isinstance(value, dict):
        for key in ("text", "name", "en_name"):
            if key in value and value.get(key) not in (None, ""):
                return str(value.get(key)).strip()
    return str(value).strip()


def field_list(value: Any) -> list[str]:
    if value is None or value is False:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = field_text(item)
            if text and text not in out:
                out.append(text)
        return out
    text = field_text(value)
    return [text] if text else []


def parse_users(value: Any) -> list[dict[str, str]]:
    items = value if isinstance(value, list) else [value]
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("en_name") or "").strip()
        open_id = str(item.get("id") or item.get("open_id") or "").strip()
        key = open_id or name
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "open_id": open_id})
    return out


def _pick_field(fields: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in fields and fields[key] not in (None, "", False, []):
            return fields[key]
    return None


def fetch_fields(table_id: str) -> list[dict[str, Any]]:
    cfg = _bitable_ids()
    resp = requests.get(
        f"{BASE_URL}/bitable/v1/apps/{cfg['app_token']}/tables/{table_id}/fields",
        headers=auth_headers(),
        timeout=20,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise RuntimeError(_friendly_error(payload))
    return (payload.get("data") or {}).get("items") or []


def fetch_records(table_id: str, view_id: str = "") -> list[dict[str, Any]]:
    cfg = _bitable_ids()
    records: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params: dict[str, Any] = {"page_size": 500, "user_id_type": "open_id"}
        if view_id:
            params["view_id"] = view_id
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{BASE_URL}/bitable/v1/apps/{cfg['app_token']}/tables/{table_id}/records",
            headers=auth_headers(),
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("code") != 0:
            raise RuntimeError(_friendly_error(payload))
        data = payload.get("data") or {}
        for item in data.get("items") or []:
            records.append(item.get("fields") or {})
        if not data.get("has_more"):
            break
        page_token = data.get("page_token") or ""
        if not page_token:
            break
    return records


def _friendly_error(payload: dict[str, Any]) -> str:
    code = payload.get("code")
    msg = payload.get("msg") or str(payload)
    if code == 91403:
        return (
            f"HeroClaw（{app_id() or 'cli_a9574044cca9dbc9'}）还没有这张多维表的权限。"
            "请在飞书打开该 Base → 右上角「…」→ 添加文档应用 → 搜索 HeroClaw。"
        )
    return f"多维表接口失败 ({code}): {msg}"


def _people_from_text(value: Any) -> list[dict[str, str]]:
    users = parse_users(value)
    if users:
        return users
    text = field_text(value)
    if not text:
        return []
    return [{"name": part.strip(), "open_id": ""} for part in text.replace("，", "、").replace(",", "、").split("、") if part.strip()]


def _attach_phone(people: list[dict[str, str]], phone: str) -> list[dict[str, str]]:
    phone = str(phone or "").strip()
    if not phone or not people:
        return people
    people[0] = {**people[0], "phone": phone}
    return people


def records_to_stores(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stores: list[dict[str, Any]] = []
    for fields in records:
        name = field_text(_pick_field(fields, STORE_NAME_KEYS))
        if not name:
            continue
        aliases: list[str] = []
        for key in ALIAS_KEYS:
            alias = field_text(fields.get(key))
            if alias and alias not in aliases and alias != name:
                aliases.append(alias)
        managers = _attach_phone(
            _people_from_text(_pick_field(fields, MANAGER_KEYS)),
            field_text(_pick_field(fields, MANAGER_PHONE_KEYS)),
        )
        supervisors = _people_from_text(_pick_field(fields, SUPERVISOR_KEYS))
        stores.append(
            {
                "name": name,
                "aliases": aliases,
                "code": field_text(_pick_field(fields, CODE_KEYS)),
                "region": field_text(_pick_field(fields, REGION_KEYS)),
                "managers": managers,
                "supervisors": supervisors,
                "raw_fields": sorted(fields.keys()),
            }
        )
    return stores


def records_to_supervisors(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fields in records:
        people = parse_users(_pick_field(fields, PERSON_KEYS + SUPERVISOR_KEYS))
        if not people:
            people = _people_from_text(_pick_field(fields, PERSON_KEYS + SUPERVISOR_KEYS))
        people = _attach_phone(people, field_text(_pick_field(fields, SUPERVISOR_PHONE_KEYS)))
        stores = field_list(_pick_field(fields, STORE_LINK_KEYS))
        region = field_text(_pick_field(fields, REGION_KEYS))
        if not people and not stores and not region:
            continue
        rows.append(
            {
                "people": people,
                "stores": stores,
                "region": region,
                "raw_fields": sorted(fields.keys()),
            }
        )
    return rows


def load_stores() -> list[dict[str, Any]]:
    data = load_json(STORES_PATH, {})
    return data.get("stores") or []


def load_supervisors() -> list[dict[str, Any]]:
    data = load_json(SUPERVISORS_PATH, {})
    return data.get("supervisors") or []


def load_sync_state() -> dict[str, Any]:
    data = load_json(SYNC_STATE_PATH, {})
    return data if isinstance(data, dict) else {}


def _iter_people(stores: list[dict[str, Any]], supervisors: list[dict[str, Any]]):
    for store in stores:
        for person in (store.get("managers") or []) + (store.get("supervisors") or []):
            yield person
    for row in supervisors:
        for person in row.get("people") or []:
            yield person


def resolve_people_open_ids(stores: list[dict[str, Any]], supervisors: list[dict[str, Any]]) -> int:
    resolved = 0
    by_name: dict[str, str] = {}
    for person in _iter_people(stores, supervisors):
        phone = str(person.get("phone") or "")
        if phone and not person.get("open_id"):
            open_id = resolve_phone_to_open_id(phone) or ""
            if open_id:
                person["open_id"] = open_id
                resolved += 1
        if person.get("name") and person.get("open_id"):
            by_name[str(person["name"])] = str(person["open_id"])
    for person in _iter_people(stores, supervisors):
        name = str(person.get("name") or "")
        if name and not person.get("open_id") and name in by_name:
            person["open_id"] = by_name[name]
            resolved += 1
    return resolved


def known_people() -> list[dict[str, str]]:
    """从已同步的门店/督导表收集姓名 → open_id。"""
    by_name: dict[str, dict[str, str]] = {}
    for store in load_stores():
        for person in (store.get("managers") or []) + (store.get("supervisors") or []):
            name = str(person.get("name") or "").strip()
            open_id = str(person.get("open_id") or "").strip()
            if name and (name not in by_name or (open_id and not by_name[name].get("open_id"))):
                by_name[name] = {"name": name, "open_id": open_id}
    for row in load_supervisors():
        for person in row.get("people") or []:
            name = str(person.get("name") or "").strip()
            open_id = str(person.get("open_id") or "").strip()
            if name and (name not in by_name or (open_id and not by_name[name].get("open_id"))):
                by_name[name] = {"name": name, "open_id": open_id}
    return list(by_name.values())


def sync_all() -> dict[str, Any]:
    cfg = _bitable_ids()
    store_fields = [f.get("field_name") for f in fetch_fields(cfg["store_table_id"])]
    supervisor_fields = [f.get("field_name") for f in fetch_fields(cfg["supervisor_table_id"])]
    store_records = fetch_records(cfg["store_table_id"], cfg["store_view_id"])
    supervisor_records = fetch_records(cfg["supervisor_table_id"], cfg["supervisor_view_id"])
    stores = records_to_stores(store_records)
    supervisors = records_to_supervisors(supervisor_records)
    resolved = resolve_people_open_ids(stores, supervisors)
    synced_at = beijing_strftime("%Y-%m-%d %H:%M:%S")
    save_json(
        STORES_PATH,
        {"synced_at": synced_at, "count": len(stores), "fields": store_fields, "stores": stores},
    )
    save_json(
        SUPERVISORS_PATH,
        {
            "synced_at": synced_at,
            "count": len(supervisors),
            "fields": supervisor_fields,
            "supervisors": supervisors,
        },
    )
    result = {
        "ok": True,
        "synced_at": synced_at,
        "store_count": len(stores),
        "supervisor_count": len(supervisors),
        "store_fields": store_fields,
        "supervisor_fields": supervisor_fields,
        "resolved_open_ids": resolved,
    }
    save_json(SYNC_STATE_PATH, result)
    return result
