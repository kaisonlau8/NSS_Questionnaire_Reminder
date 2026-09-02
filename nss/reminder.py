"""按交付日 +90 天发送 NSS 问卷私聊。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from nss.bitable import known_people
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
        f"车系：{vehicle.get('series') or ''}",
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


def resolve_national() -> list[dict[str, str]]:
    known = {p["name"]: p for p in known_people() if p.get("name")}
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in load_settings().get("national_recipients") or []:
        name = str(item.get("name") or "").strip()
        open_id = str(item.get("open_id") or "").strip()
        if not open_id and name in known:
            open_id = known[name].get("open_id") or ""
        key = open_id or name
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "open_id": open_id, "role": "national"})
    return out


def recipients_for(vehicle: dict[str, Any]) -> list[dict[str, str]]:
    people: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(items: list[dict[str, str]], role: str) -> None:
        for item in items:
            name = str(item.get("name") or "").strip()
            open_id = str(item.get("open_id") or "").strip()
            key = open_id or f"{role}:{name}"
            if not key or key in seen:
                continue
            seen.add(key)
            people.append({"name": name, "open_id": open_id, "role": role})

    _add(vehicle.get("managers") or [], "manager")
    _add(vehicle.get("supervisors") or [], "supervisor")
    _add(resolve_national(), "national")
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
    due = [enrich_vehicle(v) for v in due_on(target)]
    results: list[dict[str, Any]] = []
    sent = 0
    skipped = 0
    failed = 0
    unmatched = 0

    for vehicle in due:
        if vehicle.get("skipped"):
            item = {
                "vin": vehicle.get("vin"),
                "store": vehicle.get("store"),
                "unmatched": False,
                "recipients": [],
                "message": "",
                "actions": [],
                "status": "skipped_store",
                "skip_reason": vehicle.get("skip_reason") or "",
            }
            skipped += 1
            results.append(item)
            continue
        if vehicle.get("unmatched"):
            unmatched += 1
        recs = recipients_for(vehicle)
        text = build_message(vehicle)
        item = {
            "vin": vehicle.get("vin"),
            "store": vehicle.get("store"),
            "unmatched": bool(vehicle.get("unmatched")),
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
                errors.append("没有可发送的收件人")
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
