"""run_reminders 排除逻辑测试：monkeypatch 后不发请求、不写数据文件。"""

import pytest

import nss.reminder as reminder
from nss.settings import DEFAULT_SETTINGS


def make_vehicle(vin: str, due_date: str = "2026-01-01", **extra) -> dict:
    return {
        "vin": vin,
        "delivery_date": "2025-10-03",
        "due_date": due_date,
        "store": "猛士汽车北京交付中心",
        "plate": "",
        "series": "",
        "series_name": "",
        "model": "",
        "aftersales_series": "",
        "data_type": "",
        **extra,
    }


@pytest.fixture
def patched(monkeypatch):
    def _setup(vehicles, settings=None):
        settings = settings or {"exclusions": DEFAULT_SETTINGS["exclusions"]}
        sent: list[tuple[str, str]] = []
        monkeypatch.setattr(reminder, "due_on", lambda day=None: [dict(v) for v in vehicles])
        monkeypatch.setattr(reminder, "enrich_vehicle", lambda v, stores=None: dict(v))
        monkeypatch.setattr(reminder, "load_settings", lambda: settings)
        monkeypatch.setattr(reminder, "recipients_for", lambda vehicle: [])
        monkeypatch.setattr(reminder, "already_sent", lambda vin, due_date: False)
        monkeypatch.setattr(reminder, "_append_job_log", lambda entry: None)
        monkeypatch.setattr(reminder, "_mark_sent", lambda vin, due_date, recipients: None)
        monkeypatch.setattr(
            reminder, "send_text_message", lambda open_id, text: sent.append((open_id, text))
        )
        return sent

    return _setup


def test_dry_run_counts(patched):
    vehicles = [
        make_vehicle("LSVEXCLUDE00001", series="917"),
        make_vehicle("LSVEXCLUDE00002", data_type="试驾车"),
        make_vehicle("LSVTESTDRIVE0003", model="猛士M817 HERO（试驾车）(2025款)"),
        make_vehicle("LSVNORMAL000004", series="M817"),
    ]
    sent = patched(vehicles)
    result = reminder.run_reminders(day="2026-01-01", dry_run=True)

    assert result["due_count"] == 4
    assert result["excluded"] == 3
    assert result["excluded_by"] == {"车系917": 1, "试驾车": 2}
    assert result["sent"] == 0
    assert result["skipped"] == 0
    assert sent == []

    statuses = {item["vin"]: item["status"] for item in result["items"]}
    assert statuses["LSVEXCLUDE00001"] == "excluded"
    assert statuses["LSVTESTDRIVE0003"] == "excluded"
    assert statuses["LSVNORMAL000004"] == "dry_run"

    excluded_items = [i for i in result["items"] if i["status"] == "excluded"]
    assert all(i["recipients"] == [] for i in excluded_items)
    reasons = {i["vin"]: i["skip_reason"] for i in excluded_items}
    assert reasons["LSVEXCLUDE00001"] == "车系917"
    assert reasons["LSVEXCLUDE00002"] == "试驾车"


def test_disabled_exclusions_send_nothing_but_not_excluded(patched):
    settings = {"exclusions": {**DEFAULT_SETTINGS["exclusions"], "enabled": False}}
    vehicles = [make_vehicle("LSVEXCLUDE00001", series="917")]
    sent = patched(vehicles, settings)
    result = reminder.run_reminders(day="2026-01-01", dry_run=True)

    assert result["excluded"] == 0
    assert result["excluded_by"] == {}
    assert result["items"][0]["status"] == "dry_run"
    assert sent == []


def test_excluded_not_marked_sent(patched, capsys):
    vehicles = [make_vehicle("LSVEXCLUDE00001", series="917")]
    patched(vehicles)
    result = reminder.run_reminders(day="2026-01-01", dry_run=False)

    assert result["excluded"] == 1
    assert result["sent"] == 0
    out = capsys.readouterr().out
    assert "LSV***0001" in out
    assert "车系917" in out


def test_store_skip_still_wins(patched):
    vehicles = [
        make_vehicle("LSVSKIP00000001", series="917", skipped=True, skip_reason="跳过（虚拟店）"),
    ]
    patched(vehicles)
    result = reminder.run_reminders(day="2026-01-01", dry_run=True)
    assert result["skipped"] == 1
    assert result["excluded"] == 0
