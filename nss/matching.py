"""交付门店 ↔ 门店清单 / 督导表。"""

from __future__ import annotations

import re
from typing import Any

from nss.bitable import load_stores, load_supervisors
from nss.settings import load_settings

_PREFIXES = ("猛士汽车", "猛士")
_SUFFIXES = (
    "授权用户中心",
    "交付服务中心",
    "授权服务中心",
    "销售服务店",
    "体验中心",
    "用户中心",
    "零售中心",
    "服务中心",
    "交付中心",
)


def normalize_store(name: str) -> str:
    text = str(name or "").strip()
    text = re.sub(r"[（(][^）)]*[）)]", "", text)
    for prefix in _PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :]
            break
    for suffix in _SUFFIXES:
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return re.sub(r"[\s\-—_]", "", text)


def _score(left: str, right: str) -> int:
    if not left or not right:
        return 0
    if left == right:
        return 100
    a, b = normalize_store(left), normalize_store(right)
    if not a or not b:
        return 0
    if a == b:
        return 90
    if a in b or b in a:
        return 70
    return 0


def match_store(store_name: str, stores: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    stores = stores if stores is not None else load_stores()
    best: dict[str, Any] | None = None
    best_score = 0
    for store in stores:
        names = [str(store.get("name") or "")] + [str(a) for a in (store.get("aliases") or [])]
        score = max(_score(store_name, candidate) for candidate in names)
        if score > best_score:
            best, best_score = store, score
    return best if best_score >= 70 else None


def supervisors_for_store(store: dict[str, Any] | None, delivery_store: str) -> list[dict[str, str]]:
    people: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(items: list[dict[str, str]] | None) -> None:
        for person in items or []:
            name = str(person.get("name") or "").strip()
            open_id = str(person.get("open_id") or "").strip()
            key = open_id or name
            if not key or key in seen:
                continue
            seen.add(key)
            people.append({"name": name, "open_id": open_id})

    if store:
        _add(store.get("supervisors") or [])
    for row in load_supervisors():
        linked = [str(x) for x in (row.get("stores") or [])]
        region = str(row.get("region") or "")
        hit = False
        if linked:
            hit = any(_score(delivery_store, name) >= 70 or (store and _score(str(store.get("name") or ""), name) >= 70) for name in linked)
        elif region and store and _score(region, str(store.get("region") or "")) >= 70:
            hit = True
        if hit:
            _add(row.get("people") or [])
    return people


def enrich_vehicle(vehicle: dict[str, Any], stores: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    stores = stores if stores is not None else load_stores()
    delivery_store = str(vehicle.get("store") or "")
    skip_reason = ""
    for keyword in load_settings().get("skip_store_keywords") or []:
        if keyword and keyword in delivery_store:
            skip_reason = f"跳过（{keyword}）"
            break
    store = None if skip_reason else match_store(delivery_store, stores)
    managers = list((store or {}).get("managers") or [])
    manager_names = "、".join(p.get("name") or "" for p in managers if p.get("name"))
    return {
        **vehicle,
        "matched_store": (store or {}).get("name") or "",
        "region": (store or {}).get("region") or "",
        "manager_name": manager_names,
        "managers": managers,
        "supervisors": supervisors_for_store(store, str(vehicle.get("store") or "")),
        "unmatched": store is None and not skip_reason,
        "skipped": bool(skip_reason),
        "skip_reason": skip_reason,
    }
