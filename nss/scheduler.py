"""北京时间 00:00 同步、09:00 提醒，以及默认关闭的周一 09:30 周报。"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any, Callable

from nss.bitable import sync_all
from nss.reminder import run_reminders
from nss.settings import load_settings, save_settings, validate_weekly_report_schedule
from nss.time_utils import beijing_now, beijing_strftime, ensure_beijing_tz
from nss.weekly_report import previous_week_start, run_weekly_report

ensure_beijing_tz()

_state: dict[str, Any] = {
    "running": False,
    "stop": False,
    "thread": None,
    "last_sync": "",
    "last_send": "",
    "last_weekly_report": "",
    "last_error": "",
}


def scheduler_status() -> dict[str, Any]:
    settings = load_settings()
    return {
        "running": bool(_state["running"]),
        "last_sync": _state.get("last_sync") or "",
        "last_send": _state.get("last_send") or "",
        "last_weekly_report": _state.get("last_weekly_report") or "",
        "last_error": _state.get("last_error") or "",
        "enabled": bool(settings.get("scheduler_enabled")),
        "weekly_report_enabled": settings["weekly_report"]["enabled"],
    }


def _safe_call(label: str, fn: Callable[[], Any]) -> bool:
    try:
        fn()
        _state["last_error"] = ""
        return True
    except Exception as exc:  # noqa: BLE001
        _state["last_error"] = f"{label}: {exc}"
        print(f"[nss-scheduler] {label} 失败: {exc}")
        return False


def _run_weekly_if_due(now: datetime, settings: dict[str, Any], fired: dict[str, Any]) -> None:
    cfg = settings["weekly_report"]
    validate_weekly_report_schedule(cfg)
    today = now.date().isoformat()
    if (not cfg["enabled"] or now.weekday() != cfg["weekday"]
            or (now.hour, now.minute) != (cfg["hour"], cfg["minute"])
            or fired.get("weekly_report") == today):
        return
    fired["weekly_report"] = today
    if _safe_call("weekly-report", lambda: run_weekly_report(previous_week_start(now.date()), dry_run=cfg["dry_run"])):
        _state["last_weekly_report"] = beijing_strftime("%Y-%m-%d %H:%M:%S")


def _loop() -> None:
    fired = {"00:00": False, "remind": False}
    print("[nss-scheduler] 已启动：00:00 同步 · 09:00 提醒 · 周报按配置（默认关闭）")
    while not _state["stop"]:
        now = beijing_now()
        hm = now.strftime("%H:%M")
        try:
            settings = load_settings()
        except ValueError as exc:
            _state["last_error"] = f"settings: {exc}"
            time.sleep(1)
            continue
        remind_hm = f"{int(settings['remind_hour']):02d}:{int(settings['remind_minute']):02d}"
        if hm == "00:00" and not fired["00:00"]:
            fired["00:00"] = True
            _safe_call("sync", sync_all)
            _state["last_sync"] = beijing_strftime("%Y-%m-%d %H:%M:%S")
        elif hm != "00:00":
            fired["00:00"] = False
        if hm == remind_hm and not fired["remind"]:
            fired["remind"] = True
            _safe_call("send", lambda: run_reminders(dry_run=False))
            _state["last_send"] = beijing_strftime("%Y-%m-%d %H:%M:%S")
        elif hm != remind_hm:
            fired["remind"] = False
        _run_weekly_if_due(now, settings, fired)
        time.sleep(1)
    _state["running"] = False


def start_scheduler() -> bool:
    if _state["running"]:
        return False
    load_settings()  # 非法周报时间在启动线程之前拒绝。
    _state["stop"] = False
    _state["running"] = True
    thread = threading.Thread(target=_loop, daemon=True, name="nss-scheduler")
    _state["thread"] = thread
    thread.start()
    save_settings({"scheduler_enabled": True})
    return True


def stop_scheduler() -> None:
    _state["stop"] = True
    _state["running"] = False
    save_settings({"scheduler_enabled": False})
