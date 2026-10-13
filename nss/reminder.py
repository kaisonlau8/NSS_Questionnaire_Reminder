"""按创建时间（交付日）+90 天发送 NSS 问卷私聊，发给门店服务经理与对应督导。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from nss.eligibility import ineligible_reason, mask_vin
from nss.feishu_client import send_text_message
from nss.jsonutil import load_json, save_json
from nss.matching import enrich_vehicle
from nss.paths import JOB_LOG_PATH, SENT_PATH
from nss.settings import load_settings
from nss.time_utils import beijing_iso, beijing_strftime, beijing_today
from nss.vehicles import due_on


def build_message(vehicle: dict[str, Any]) -> str:
    lines = [
        f"VIN：{vehicle.get('vin') or ''}",
        f"交付日期：{vehicle.get('delivery_date') or ''}",
        f"车牌号：{vehicle.get('plate') or ''}",
        f"车系：{vehicle.get('series_name') or vehicle.get('series') or ''}",
        f"车型：{vehicle.get('model') or ''}",
        f"交付门店：{vehicle.get('store') or ''}",
        f"门店服务经理：{vehicle.get('manager_name') or ''}",
        "该车辆会在今日收到 NSS 问卷，请及时跟进！",
    ]
    return "\n".join(lines)


def load_sent() -> dict[str, Any]:
    data = load_json(SENT_PATH, {})
    if not isinstance(data, dict):
        return {"items": []}
    if "items" not in data:
        data["items"] = []
    return data


def _sent_key(vin: str, due_date: str) -> str:
    return f"{vin}:{due_date}"


def already_sent(vin: str, due_date: str) -> bool:
    keys = {str(item.get("key") or "") for item in load_sent().get("items") or []}
    return _sent_key(vin, due_date) in keys


def recipients_for(vehicle: dict[str, Any]) -> list[dict[str, str]]:
    """收件人 = 门店服务经理 + 该门店/区域督导；先经理后督导，按 open_id（缺失时按姓名）去重。

    同一人既是经理又是督导只发一条（role 记为 manager）；不含全国收件人。
    """
    people: list[dict[str, str]] = []
    seen_open_ids: set[str] = set()
    seen_names: set[str] = set()
    for role, field in (("manager", "managers"), ("supervisor", "supervisors")):
        for item in vehicle.get(field) or []:
            name = str(item.get("name") or "").strip()
            open_id = str(item.get("open_id") or "").strip()
            if not name and not open_id:
                continue
            if open_id and open_id in seen_open_ids:
                continue
            if name and name in seen_names:
                continue
            if open_id:
                seen_open_ids.add(open_id)
            if name:
                seen_names.add(name)
            people.append({"name": name, "open_id": open_id, "role": role})
    return people


def _append_job_log(entry: dict[str, Any]) -> None:
    JOB_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOB_LOG_PATH.open("a", encoding="utf-8") as fh:
        import json

        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _mark_sent(vin: str, due_date: str, recipients: list[dict[str, str]]) -> None:
    data = load_sent()
    data["items"].append(
        {
            "key": _sent_key(vin, due_date),
            "vin": vin,
            "due_date": due_date,
            "sent_at": beijing_iso(),
            "recipients": recipients,
        }
    )
    data["updated_at"] = beijing_iso()
    save_json(SENT_PATH, data)


def parse_day(value: str | None) -> date:
    if not value:
        return beijing_today()
    return datetime.strptime(value[:10], "%Y-%m-%d").date()


def run_reminders(*, day: str | None = None, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    target = parse_day(day)
    settings = load_settings()
    due = [enrich_vehicle(v) for v in due_on(target)]
    results: list[dict[str, Any]] = []
    sent = 0
    skipped = 0
    failed = 0
    unmatched = 0
    excluded = 0
    excluded_by: dict[str, int] = {}

    for vehicle in due:
        reason = ineligible_reason(vehicle, settings)
        if reason:
            excluded += 1
            excluded_by[reason] = excluded_by.get(reason, 0) + 1
            results.append(
                {
                    "vin": vehicle.get("vin"),
                    "store": vehicle.get("store"),
                    "unmatched": False,
                    "recipients": [],
                    "message": "",
                    "actions": [],
                    "status": "excluded",
                    "skip_reason": reason,
                }
            )
            print(f"[nss] 已排除 {mask_vin(vehicle.get('vin'))}：{reason}")
            continue
        if vehicle.get("unmatched"):
            unmatched += 1
        recs = recipients_for(vehicle)
        text = build_message(vehicle)
        item = {
            "vin": vehicle.get("vin"),
            "store": vehicle.get("store"),
            "unmatched": bool(vehicle.get("unmatched")),
            "match_method": vehicle.get("match_method") or ("none" if vehicle.get("unmatched") else ""),
            "recipients": recs,
            "message": text,
            "actions": [],
        }
        if already_sent(str(vehicle.get("vin") or ""), str(vehicle.get("due_date") or "")) and not force:
            item["status"] = "skipped"
            skipped += 1
            results.append(item)
            continue
        if dry_run:
            item["status"] = "dry_run"
            results.append(item)
            continue

        delivered: list[dict[str, str]] = []
        errors: list[str] = []
        for rec in recs:
            if not rec.get("open_id"):
                errors.append(f"{rec.get('name') or '未命名'} 无 open_id")
                continue
            try:
                send_text_message(rec["open_id"], text)
                delivered.append(rec)
                item["actions"].append({"name": rec["name"], "ok": True})
            except Exception as exc:  # noqa: BLE001
                failed += 1
                errors.append(f"{rec.get('name')}: {exc}")
                item["actions"].append({"name": rec.get("name"), "ok": False, "error": str(exc)})
        if delivered:
            _mark_sent(str(vehicle.get("vin") or ""), str(vehicle.get("due_date") or ""), delivered)
            sent += 1
            item["status"] = "sent" if not errors else "partial"
        else:
            item["status"] = "failed"
            if not errors:
                errors.append("门店未匹配，无服务经理/督导" if vehicle.get("unmatched") else "没有可发送的收件人")
        item["errors"] = errors
        results.append(item)

    summary = {
        "ok": True,
        "dry_run": dry_run,
        "date": target.isoformat(),
        "due_count": len(due),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
        "unmatched": unmatched,
        "excluded": excluded,
        "excluded_by": excluded_by,
        "at": beijing_strftime("%Y-%m-%d %H:%M:%S"),
        "items": results,
    }
    _append_job_log(
        {
            "at": summary["at"],
            "dry_run": dry_run,
            "date": summary["date"],
            "due_count": summary["due_count"],
            "sent": sent,
            "skipped": skipped,
            "failed": failed,
            "unmatched": unmatched,
            "excluded": excluded,
            "excluded_by": excluded_by,
        }
    )
    return summary


def recent_logs(limit: int = 30) -> list[dict[str, Any]]:
    if not JOB_LOG_PATH.exists():
        return []
    lines = JOB_LOG_PATH.read_text(encoding="utf-8").splitlines()
    rows: list[dict[str, Any]] = []
    import json

    for line in lines[-limit:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    rows.reverse()
    return rows


def sent_today_count() -> int:
    today = beijing_today().isoformat()
    n = 0
    for item in load_sent().get("items") or []:
        sent_at = str(item.get("sent_at") or "")
        if sent_at.startswith(today) or str(item.get("due_date") or "") == today:
            n += 1
    return n
