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

from nss.bitable import load_stores, load_supervisors, load_sync_state, sync_all  # noqa: E402
from nss.eligibility import ineligible_reason  # noqa: E402
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

# --- 设计系统（antd-lite.css / sprite.svg，由 design-system/sync.sh 同步到 ds/）---
_ds_cache: dict[str, str] = {}


def _ds(name: str) -> str:
    if name not in _ds_cache:
        _ds_cache[name] = (ROOT / "ds" / name).read_text(encoding="utf-8")
    return _ds_cache[name]


app.jinja_env.globals["ds_css"] = lambda: _ds("antd-lite.css")
app.jinja_env.globals["ds_sprite"] = lambda: _ds("sprite.svg")
app.jinja_env.globals["ds_cards"] = lambda: _ds("cards.js")


# --- 品牌静态资源（logo / favicon，design-system/sync.sh 同步到 ds/brand/）---
@app.get("/ds/brand/<path:name>")
def ds_brand(name: str):
    from flask import send_from_directory
    return send_from_directory(str(ROOT / "ds" / "brand"), name)

# --- m-hero SSO (Casdoor): inert unless MHERO_AUTH[_NSS]=audit|on is set (see docs/SSO_CASDOOR.md) ---
from mhero_auth.flask_adapter import init_app as _mhero_auth_init
_mhero_auth_init(app, "nss", default_mode="off", public_get_paths=["/ds/brand/*"])
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024


def _directory_rows() -> list[dict]:
    rows = []
    for store in load_stores():
        managers = store.get("managers") or []
        supervisors = store.get("supervisors") or []
        manager = managers[0] if managers else {}
        supervisor = supervisors[0] if supervisors else {}
        rows.append({
            "code": store.get("code") or "",
            "name": store.get("name") or "",
            "region": store.get("region") or "",
            "supervisor": supervisor.get("name") or "",
            "manager": manager.get("name") or "",
            "manager_ok": bool(manager.get("open_id") or manager.get("phone")),
        })
    rows.sort(key=lambda item: (item["region"], item["code"], item["name"]))
    return rows


def _status_payload() -> dict:
    settings = load_settings()
    meta = vehicles_meta()
    due = [enrich_vehicle(v) for v in load_vehicles() if v.get("due_date") == beijing_today().isoformat()]
    return {
        "now": beijing_strftime("%Y-%m-%d %H:%M:%S"),
        "vehicles": meta,
        "store_count": len(load_stores()),
        "supervisor_count": len(load_supervisors()),
        "stores": _directory_rows(),
        "sync": load_sync_state(),
        "due_today": len(due),
        "due_unmatched": sum(1 for v in due if v.get("unmatched")),
        "due_excluded": sum(1 for v in due if ineligible_reason(v, settings)),
        "sent_today": sent_today_count(),
        "next_due_date": next_due_date(),
        "settings": settings,
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
    settings = load_settings()
    items = []
    for vehicle in load_vehicles():
        if vehicle.get("due_date") != day.isoformat():
            continue
        enriched = enrich_vehicle(vehicle)
        items.append(
            {
                **enriched,
                "recipients": recipients_for(enriched),
                "excluded_reason": ineligible_reason(enriched, settings),
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
