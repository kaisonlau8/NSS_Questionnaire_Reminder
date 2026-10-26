"""同步门店清单与督导表。"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

import requests
from dotenv import load_dotenv

from nss.feishu_client import BASE_URL, app_id, auth_headers, resolve_phone_to_open_id
from nss.jsonutil import load_json, save_json
from nss.paths import ROOT, STORES_PATH, SUPERVISORS_PATH, SYNC_STATE_PATH
from nss.time_utils import beijing_strftime, ensure_beijing_tz

ensure_beijing_tz()
load_dotenv(ROOT / ".env")

STORE_NAME_KEYS = ("店名称", "门店名称", "交付门店", "门店", "店名", "用户中心")
MANAGER_FIELD = "门店售后业务负责人"
MANAGER_PHONE_FIELD = "售后业务负责人手机号"
MANAGER_ALIAS_KEYS = ("门店服务经理", "服务经理", "售后服务经理", "服务顾问经理")
MANAGER_PHONE_ALIAS_KEYS = ("服务经理电话", "经理电话")
MANAGER_SLOT_KEYS = {
    1: (f"{MANAGER_FIELD} 1", f"{MANAGER_FIELD}1", MANAGER_FIELD, *MANAGER_ALIAS_KEYS),
    2: (f"{MANAGER_FIELD} 2", f"{MANAGER_FIELD}2"),
    3: (f"{MANAGER_FIELD} 3", f"{MANAGER_FIELD}3"),
    4: (f"{MANAGER_FIELD} 4", f"{MANAGER_FIELD}4"),
}
MANAGER_PHONE_SLOT_KEYS = {
    1: (f"{MANAGER_PHONE_FIELD} 1", f"{MANAGER_PHONE_FIELD}1", MANAGER_PHONE_FIELD, *MANAGER_PHONE_ALIAS_KEYS),
    2: (f"{MANAGER_PHONE_FIELD} 2", f"{MANAGER_PHONE_FIELD}2"),
    3: (f"{MANAGER_PHONE_FIELD} 3", f"{MANAGER_PHONE_FIELD}3"),
    4: (f"{MANAGER_PHONE_FIELD} 4", f"{MANAGER_PHONE_FIELD}4"),
}
MANAGER_KEYS = tuple(dict.fromkeys(key for slot in range(1, 5) for key in MANAGER_SLOT_KEYS[slot]))
MANAGER_PHONE_KEYS = tuple(
    dict.fromkeys(key for slot in range(1, 5) for key in MANAGER_PHONE_SLOT_KEYS[slot])
)
SUPERVISOR_KEYS = ("督导", "服务督导", "督导姓名", "区域督导", "售后督导")
REGION_KEYS = ("区域", "战区", "大区")
CODE_KEYS = ("店代码", "门店编码", "店代码", "编码")
ALIAS_KEYS = ("门店全称", "原门店名称")
PERSON_KEYS = ("督导", "督导姓名", "姓名", "提醒人", "人员")
STORE_LINK_KEYS = ("门店", "负责门店", "门店名称", "交付门店")
SUPERVISOR_PHONE_KEYS = ("督导手机号", "督导飞书电话号", "飞书电话号", "督导电话", "电话")


def _bitable_ids() -> dict[str, str]:
    cfg = {
        "app_token": os.getenv("BITABLE_APP_TOKEN", "").strip(),
        "table_id": (
            os.getenv("BITABLE_TABLE_ID", "").strip()
            or os.getenv("BITABLE_STORE_TABLE_ID", "").strip()
        ),
        "view_id": (
            os.getenv("BITABLE_VIEW_ID", "").strip()
            or os.getenv("BITABLE_STORE_VIEW_ID", "").strip()
        ),
    }
    missing = [k for k in ("app_token", "table_id") if not cfg[k]]
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


def fetch_records(
    table_id: str,
    view_id: str = "",
    *,
    app_token: str | None = None,
    raw_items: bool = False,
) -> list[dict[str, Any]]:
    """只读分页；显式 app_token 可读取独立的数据源，不使用门店表配置。"""
    token = app_token if app_token is not None else _bitable_ids()["app_token"]
    records: list[dict[str, Any]] = []
    page_token = ""
    seen_tokens: set[str] = set()
    while True:
        params: dict[str, Any] = {"page_size": 500, "user_id_type": "open_id"}
        if view_id:
            params["view_id"] = view_id
        if page_token:
            params["page_token"] = page_token
        resp = requests.get(
            f"{BASE_URL}/bitable/v1/apps/{token}/tables/{table_id}/records",
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
            records.append(item if raw_items else item.get("fields") or {})
        if not data.get("has_more"):
            break
        page_token = data.get("page_token") or ""
        if not page_token or page_token in seen_tokens:
            raise RuntimeError("多维表分页异常：has_more=true 但 page_token 缺失或重复，拒绝返回不完整数据")
        seen_tokens.add(page_token)
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


def _norm_field_name(value: Any) -> str:
    """字段名去掉所有空白，兼容「负责人 1」「负责人1」等写法。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")))


def _has_field_value(value: Any) -> bool:
    if value is None or value is False or value == "" or value == [] or value == {}:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_has_field_value(item) for item in value)
    if isinstance(value, dict):
        return any(
            _has_field_value(value.get(key))
            for key in ("text", "name", "en_name", "id", "open_id")
        )
    return True


def _slot_field(fields: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """按候选字段顺序取值，字段名忽略空白；空值继续尝试下一个候选。"""
    for key in keys:
        if key in fields and _has_field_value(fields[key]):
            return fields[key]
    normalized = {
        _norm_field_name(key): raw
        for key, raw in fields.items()
        if _has_field_value(raw)
    }
    for key in keys:
        normalized_key = _norm_field_name(key)
        if normalized_key in normalized:
            return normalized[normalized_key]
    return None


def _managers_from_fields(fields: dict[str, Any]) -> list[dict[str, str]]:
    """按 1..4 槽位收集售后负责人，并按 open_id（缺失时姓名）跨槽去重。

    1 号槽位：编号字段（人或手机号任一非空）整体优先，全空时才整体使用旧字段/别名，
    不把两个人的姓名、open_id、手机号拼在一起。重复的人把缺的手机号/open_id 补到先出现的那条上。
    """
    managers: list[dict[str, str]] = []
    index: dict[str, dict[str, str]] = {}
    for slot in range(1, 5):
        name_keys = MANAGER_SLOT_KEYS[slot]
        phone_keys = MANAGER_PHONE_SLOT_KEYS[slot]
        if slot == 1:
            numbered_names, legacy_names = name_keys[:2], name_keys[2:]
            numbered_phones, legacy_phones = phone_keys[:2], phone_keys[2:]
            if _slot_field(fields, numbered_names) is not None or _slot_field(fields, numbered_phones) is not None:
                name_keys, phone_keys = numbered_names, numbered_phones
            else:
                name_keys, phone_keys = legacy_names, legacy_phones
        value = _slot_field(fields, name_keys)
        phone = field_text(_slot_field(fields, phone_keys))
        if value is None and not phone:
            continue
        people = _attach_phone(_people_from_text(value), phone) if value is not None else [{"name": "", "open_id": "", "phone": phone}]
        for person in people:
            name = str(person.get("name") or "").strip()
            open_id = str(person.get("open_id") or "").strip()
            person_phone = str(person.get("phone") or "").strip()
            key = open_id or name or person_phone  # 只有手机号也保留，后续按手机号解析 open_id
            if not key:
                continue
            if key in index:
                kept = index[key]
                kept["open_id"] = kept["open_id"] or open_id
                kept["phone"] = kept["phone"] or person_phone
                continue
            item = {"name": name, "open_id": open_id, "phone": person_phone}
            index[key] = item
            managers.append(item)
    return managers


def records_to_stores(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stores: list[dict[str, Any]] = []
    for fields in records:
        code = field_text(_pick_field(fields, CODE_KEYS))
        name = field_text(_pick_field(fields, STORE_NAME_KEYS)) or code
        if not name:
            continue
        aliases: list[str] = []
        for key in ALIAS_KEYS:
            alias = field_text(fields.get(key))
            if alias and alias not in aliases and alias != name:
                aliases.append(alias)
        managers = _managers_from_fields(fields)
        primary_manager = dict(managers[0]) if managers else {}
        supervisors = _attach_phone(
            _people_from_text(_pick_field(fields, SUPERVISOR_KEYS)),
            field_text(_pick_field(fields, SUPERVISOR_PHONE_KEYS)),
        )
        stores.append(
            {
                "name": name,
                "aliases": aliases,
                "code": code,
                "region": field_text(_pick_field(fields, REGION_KEYS)),
                "managers": managers,
                "primary_manager": primary_manager,
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


def _supervisors_from_stores(stores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """督导不再单独一张表，从门店行的督导联系人汇总。"""
    by_key: dict[str, dict[str, Any]] = {}
    for store in stores:
        for person in store.get("supervisors") or []:
            key = str(person.get("open_id") or person.get("name") or "").strip()
            if not key:
                continue
            row = by_key.get(key)
            if row is None:
                row = {
                    "people": [person],
                    "stores": [],
                    "region": str(store.get("region") or ""),
                }
                by_key[key] = row
            name = str(store.get("name") or "").strip()
            if name and name not in row["stores"]:
                row["stores"].append(name)
    return list(by_key.values())


def sync_all() -> dict[str, Any]:
    cfg = _bitable_ids()
    store_fields = [f.get("field_name") for f in fetch_fields(cfg["table_id"])]
    store_records = fetch_records(cfg["table_id"], cfg["view_id"])
    stores = records_to_stores(store_records)
    supervisors = _supervisors_from_stores(stores)
    resolved = resolve_people_open_ids(stores, supervisors)
    for store in stores:  # 解析 open_id 后主负责人与 managers[0] 保持一致
        store["primary_manager"] = dict(store["managers"][0]) if store.get("managers") else {}
    missing_managers = [
        f"{store.get('code') or ''} {store.get('name') or ''}".strip()
        for store in stores
        if not store.get("managers")
    ]
    for label in missing_managers:
        print(f"[nss-sync] 无售后负责人，该店到期车不发给服务经理: {label}")
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
            "source": "store-rows",
            "supervisors": supervisors,
        },
    )
    result = {
        "ok": True,
        "synced_at": synced_at,
        "store_count": len(stores),
        "supervisor_count": len(supervisors),
        "missing_manager_count": len(missing_managers),
        "store_fields": store_fields,
        "resolved_open_ids": resolved,
    }
    save_json(SYNC_STATE_PATH, result)
    return result
