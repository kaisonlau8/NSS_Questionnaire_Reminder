#!/usr/bin/env python3
"""NSS 问卷提醒控制台。"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from werkzeug.utils import secure_filename

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from nss.bitable import known_people, load_stores, load_supervisors, load_sync_state, sync_all  # noqa: E402
from nss.matching import enrich_vehicle  # noqa: E402
from nss.paths import UPLOAD_DIR, ensure_dirs  # noqa: E402
from nss.reminder import recent_logs, recipients_for, run_reminders, sent_today_count  # noqa: E402
from nss.scheduler import scheduler_status, start_scheduler, stop_scheduler  # noqa: E402
from nss.settings import load_settings, save_settings  # noqa: E402
from nss.time_utils import beijing_strftime, beijing_today, ensure_beijing_tz  # noqa: E402
from nss.vehicles import (  # noqa: E402
    find_seed_excel,
    import_excel,
    load_vehicles,
    next_due_date,
    vehicles_meta,
)

ensure_beijing_tz()
ensure_dirs()

app = Flask(__name__, template_folder=str(ROOT / "templates"))
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024


def _resolve_recipients(items: list) -> list[dict[str, str]]:
    known = {p["name"]: p.get("open_id") or "" for p in known_people() if p.get("name")}
    current = {p["name"]: p.get("open_id") or "" for p in load_settings().get("national_recipients") or []}
    out: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, str):
            name = item.strip()
            open_id = ""
        elif isinstance(item, dict):
            name = str(item.get("name") or "").strip()
            open_id = str(item.get("open_id") or "").strip()
        else:
            continue
        if not name:
            continue
        if not open_id:
            open_id = current.get(name) or known.get(name) or ""
        out.append({"name": name, "open_id": open_id})
    return out


def _status_payload() -> dict:
    settings = load_settings()
    meta = vehicles_meta()
    due = [enrich_vehicle(v) for v in load_vehicles() if v.get("due_date") == beijing_today().isoformat()]
    unresolved = [p for p in settings.get("national_recipients") or [] if not p.get("open_id")]
    return {
        "now": beijing_strftime("%Y-%m-%d %H:%M:%S"),
        "vehicles": meta,
        "store_count": len(load_stores()),
        "supervisor_count": len(load_supervisors()),
        "sync": load_sync_state(),
        "due_today": len(due),
        "due_unmatched": sum(1 for v in due if v.get("unmatched")),
        "sent_today": sent_today_count(),
        "next_due_date": next_due_date(),
        "settings": settings,
        "unresolved_nationals": unresolved,
        "scheduler": scheduler_status(),
        "app_id": os.getenv("APP_ID", ""),
    }


@app.get("/")
def index():
    return render_template("dashboard.html", status=_status_payload())


@app.get("/api/status")
def api_status():
    return jsonify(_status_payload())


@app.get("/api/due")
def api_due():
    raw = (request.args.get("date") or beijing_today().isoformat())[:10]
    try:
        day = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"ok": False, "error": "日期格式应为 YYYY-MM-DD"}), 400
    items = []
    for vehicle in load_vehicles():
        if vehicle.get("due_date") != day.isoformat():
            continue
        enriched = enrich_vehicle(vehicle)
        items.append(
            {
                **enriched,
                "recipients": recipients_for(enriched),
            }
        )
    return jsonify({"ok": True, "date": day.isoformat(), "count": len(items), "items": items})


@app.post("/api/upload")
def api_upload():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"ok": False, "error": "请选择 Excel 文件"}), 400
    name = secure_filename(upload.filename)
    if not name.lower().endswith(".xlsx"):
        return jsonify({"ok": False, "error": "只接受 .xlsx"}), 400
    dest = UPLOAD_DIR / f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{name}"
    upload.save(dest)
    try:
        result = import_excel(dest)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, **result, "path": dest.name})


@app.post("/api/sync")
def api_sync():
    try:
        result = sync_all()
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(result)


@app.post("/api/settings")
def api_settings():
    body = request.get_json(silent=True) or {}
    if "national_names" in body:
        names = body.get("national_names")
        if isinstance(names, str):
            names = [line.strip() for line in names.splitlines() if line.strip()]
        body["national_recipients"] = _resolve_recipients(names)
    elif "national_recipients" in body:
        body["national_recipients"] = _resolve_recipients(body.get("national_recipients") or [])
    settings = save_settings(body)
    return jsonify({"ok": True, "settings": settings})


@app.post("/api/run")
def api_run():
    body = request.get_json(silent=True) or {}
    try:
        result = run_reminders(
            day=body.get("date"),
            dry_run=bool(body.get("dry_run")),
            force=bool(body.get("force")),
        )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify(result)


@app.post("/api/scheduler/start")
def api_scheduler_start():
    start_scheduler()
    return jsonify({"ok": True, "scheduler": scheduler_status()})


@app.post("/api/scheduler/stop")
def api_scheduler_stop():
    stop_scheduler()
    return jsonify({"ok": True, "scheduler": scheduler_status()})


@app.get("/api/logs")
def api_logs():
    return jsonify({"ok": True, "items": recent_logs()})


def _bootstrap() -> None:
    if not load_vehicles():
        seed = find_seed_excel()
        if seed:
            try:
                import_excel(seed)
                print(f"[nss] 已导入种子档案 {seed.name}")
            except Exception as exc:  # noqa: BLE001
                print(f"[nss] 种子档案导入失败: {exc}")
    if load_settings().get("scheduler_enabled"):
        start_scheduler()
        print("[nss] 定时已启动（00:00 同步 / 09:00 提醒）")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("CONSOLE_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CONSOLE_PORT", "9005")))
    args = parser.parse_args()
    _bootstrap()
    print(f"NSS 问卷提醒控制台 http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
