"""飞书 HeroClaw：tenant token、私聊与群聊文本。"""

from __future__ import annotations

import json
import os
import time

import requests
from dotenv import load_dotenv

from nss.jsonutil import load_json, save_json
from nss.paths import DATA_DIR, ROOT
from nss.time_utils import beijing_strftime, ensure_beijing_tz

ensure_beijing_tz()
load_dotenv(ROOT / ".env")

BASE_URL = "https://open.feishu.cn/open-apis"
_token_cache: dict = {"token": None, "expires_at": 0}


def _get_app_credentials() -> tuple[str, str]:
    app_id = os.getenv("APP_ID", "").strip()
    app_secret = os.getenv("APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("缺少 APP_ID 或 APP_SECRET，请在 .env 中配置")
    return app_id, app_secret


def get_tenant_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    app_id, app_secret = _get_app_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 token 失败: {data.get('msg') or data}")
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expire", 7200) - 300
    return _token_cache["token"]


def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_tenant_token()}"}


def send_text_message(open_id: str, text: str) -> dict:
    resp = requests.post(
        f"{BASE_URL}/im/v1/messages?receive_id_type=open_id",
        headers={**auth_headers(), "Content-Type": "application/json"},
        json={"receive_id": open_id, "msg_type": "text", "content": json.dumps({"text": text})},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(data.get("msg") or f"发送失败: {data}")
    return data.get("data") or {}


def send_chat_text(chat_id: str, text: str) -> dict:
    if not chat_id or not chat_id.strip():
        raise ValueError("缺少飞书群 chat_id")
    resp = requests.post(
        f"{BASE_URL}/im/v1/messages?receive_id_type=chat_id",
        headers={**auth_headers(), "Content-Type": "application/json"},
        json={"receive_id": chat_id.strip(), "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(data.get("msg") or "群消息发送失败")
    return data.get("data") or {}


def app_id() -> str:
    return os.getenv("APP_ID", "").strip()


_PHONE_CACHE = DATA_DIR / "phone_open_ids.json"


def _load_phone_cache() -> dict[str, str]:
    data = load_json(_PHONE_CACHE, {})
    return data.get("by_phone") or {}


def _save_phone_cache(cache: dict[str, str]) -> None:
    save_json(
        _PHONE_CACHE,
        {
            "updated_at": beijing_strftime("%Y-%m-%d %H:%M:%S"),
            "by_phone": cache,
        },
    )


def normalize_phone(phone: str) -> str:
    digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
    if digits.startswith("86") and len(digits) == 13:
        digits = digits[2:]
    return digits


def resolve_phone_to_open_id(phone: str) -> str | None:
    phone = normalize_phone(phone)
    if len(phone) != 11:
        return None
    cache = _load_phone_cache()
    if phone in cache:
        return cache[phone]
    resp = requests.post(
        f"{BASE_URL}/contact/v3/users/batch_get_id?user_id_type=open_id",
        headers=auth_headers(),
        json={"mobiles": [phone], "emails": [], "include_resigned": False},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        return None
    user_list = data.get("data", {}).get("user_list") or []
    if not user_list:
        return None
    open_id = user_list[0].get("user_id") or user_list[0].get("open_id") or ""
    if open_id:
        cache[phone] = open_id
        _save_phone_cache(cache)
    return open_id or None
