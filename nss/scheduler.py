"""北京时间 00:00 同步多维表，09:00 发送 NSS 提醒。"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from nss.bitable import sync_all
from nss.reminder import run_reminders
from nss.settings import load_settings, save_settings
from nss.time_utils import beijing_now, beijing_strftime, ensure_beijing_tz

ensure_beijing_tz()

_state: dict[str, Any] = {
    "running": False,
    "stop": False,
    "thread": None,
    "last_sync": "",
    "last_send": "",
    "last_error": "",
}


def scheduler_status() -> dict[str, Any]:
    return {
        "running": bool(_state["running"]),
        "last_sync": _state.get("last_sync") or "",
        "last_send": _state.get("last_send") or "",
        "last_error": _state.get("last_error") or "",
        "enabled": bool(load_settings().get("scheduler_enabled")),
    }


def _safe_call(label: str, fn: Callable[[], Any]) -> None:
    try:
        fn()
        _state["last_error"] = ""
    except Exception as exc:  # noqa: BLE001
        _state["last_error"] = f"{label}: {exc}"
        print(f"[nss-scheduler] {label} 失败: {exc}")


def _loop() -> None:
    fired = {"00:00": False, "remind": False}
    print("[nss-scheduler] 已启动：00:00 同步 · 09:00 提醒")
    while not _state["stop"]:
        now = beijing_now()
        hm = now.strftime("%H:%M")
        settings = load_settings()
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
        time.sleep(1)
    _state["running"] = False


def start_scheduler() -> bool:
    if _state["running"]:
        return False
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
