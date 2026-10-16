"""run_reminders 新规则测试：monkeypatch 后不发请求、不写数据文件。"""

import pytest

import nss.reminder as reminder
from nss.settings import DEFAULT_SETTINGS


def make_vehicle(vin: str, due_date: str = "2026-01-01", series_name: str = "全新M817",
                 data_type: str = "客户", **extra) -> dict:
    return {
        "vin": vin,
        "delivery_date": "2025-10-03",
        "due_date": due_date,
        "store": "猛士汽车北京交付中心",
        "store_code": "S001",
        "plate": "",
        "series": "",
        "series_name": series_name,
        "model": "",
        "aftersales_series": "",
        "data_type": data_type,
        **extra,
    }


@pytest.fixture
def patched(monkeypatch):
    def _setup(vehicles, settings=None, patch_recipients=True):
        settings = settings or {"eligibility": DEFAULT_SETTINGS["eligibility"], "offset_days": 90}
        sent: list[tuple[str, str]] = []
        marked: list[str] = []
        logs: list[dict] = []
        monkeypatch.setattr(reminder, "due_on", lambda day=None: [dict(v) for v in vehicles])
        monkeypatch.setattr(reminder, "enrich_vehicle", lambda v, stores=None: dict(v))
        monkeypatch.setattr(reminder, "load_settings", lambda: settings)
        if patch_recipients:
            monkeypatch.setattr(reminder, "recipients_for", lambda vehicle: [])
        monkeypatch.setattr(reminder, "already_sent", lambda vin, due_date: False)
        monkeypatch.setattr(reminder, "_append_job_log", lambda entry: logs.append(entry))
        monkeypatch.setattr(reminder, "_mark_sent", lambda vin, due_date, recipients: marked.append(vin))
        monkeypatch.setattr(
            reminder, "send_text_message", lambda open_id, text: sent.append((open_id, text))
        )
        return sent, marked, logs

    return _setup


def test_dry_run_counts(patched):
    vehicles = [
        make_vehicle("LSVOTHERSERIES01", series_name="917"),
        make_vehicle("LSVOTHERSERIES02", series_name="M817"),
        make_vehicle("LSVTESTDRIVE0003", data_type="试驾车"),
        make_vehicle("LSVNORMAL0000004"),
    ]
    sent, marked, logs = patched(vehicles)
    result = reminder.run_reminders(day="2026-01-01", dry_run=True)

    assert result["due_count"] == 4
    assert result["excluded"] == 3
    assert result["excluded_by"] == {"车系非全新M817": 2, "试驾车": 1}
    assert result["sent"] == 0
    assert result["skipped"] == 0
    assert sent == []
    assert marked == []

    statuses = {item["vin"]: item["status"] for item in result["items"]}
    assert statuses["LSVOTHERSERIES01"] == "excluded"
    assert statuses["LSVOTHERSERIES02"] == "excluded"
    assert statuses["LSVTESTDRIVE0003"] == "excluded"
    assert statuses["LSVNORMAL0000004"] == "dry_run"

    excluded_items = [i for i in result["items"] if i["status"] == "excluded"]
    assert all(i["recipients"] == [] for i in excluded_items)
    reasons = {i["vin"]: i["skip_reason"] for i in excluded_items}
    assert reasons["LSVOTHERSERIES01"] == "车系非全新M817"
    assert reasons["LSVTESTDRIVE0003"] == "试驾车"

    assert logs[0]["excluded_by"] == {"车系非全新M817": 2, "试驾车": 1}


def test_excluded_not_marked_sent(patched, capsys):
    vehicles = [make_vehicle("LSVEXCLUDE00001", series_name="917")]
    sent, marked, _ = patched(vehicles)
    result = reminder.run_reminders(day="2026-01-01", dry_run=False)

    assert result["excluded"] == 1
    assert result["sent"] == 0
    assert sent == []
    assert marked == []
    out = capsys.readouterr().out
    assert "LSV***0001" in out
    assert "车系非全新M817" in out


def test_eligible_data_types_pass(patched):
    vehicles = [
        make_vehicle("LSVKEHU000000001", data_type="客户"),
        make_vehicle("LSVZHIJIAN0000002", data_type="质检"),
        make_vehicle("LSVEMPTY000000003", data_type=""),
    ]
    patched(vehicles)
    result = reminder.run_reminders(day="2026-01-01", dry_run=True)
    assert result["excluded"] == 0
    assert all(i["status"] == "dry_run" for i in result["items"])


def test_recipients_managers_and_supervisors():
    vehicle = make_vehicle(
        "LSVRECIPS0000001",
        managers=[{"name": "经理A", "open_id": "ou_manager_a"}, {"name": "经理B", "open_id": ""}],
        supervisors=[{"name": "督导C", "open_id": "ou_supervisor_c"}, {"name": "督导D", "open_id": ""}],
    )
    recs = reminder.recipients_for(vehicle)
    assert [(r["name"], r["role"]) for r in recs] == [
        ("经理A", "manager"),
        ("经理B", "manager"),
        ("督导C", "supervisor"),
        ("督导D", "supervisor"),
    ]
    assert all(r["role"] != "national" for r in recs)
    assert not hasattr(reminder, "resolve_national")


def test_recipients_dedupe_same_open_id():
    vehicle = make_vehicle(
        "LSVDEDUPE0000001",
        managers=[{"name": "王五", "open_id": "ou_same"}],
        supervisors=[{"name": "王五", "open_id": "ou_same"}, {"name": "督导E", "open_id": "ou_same"}],
    )
    recs = reminder.recipients_for(vehicle)
    assert [(r["name"], r["role"]) for r in recs] == [("王五", "manager")]


def test_recipients_dedupe_same_name_without_open_id():
    vehicle = make_vehicle(
        "LSVDEDUPNAME0001",
        managers=[{"name": "赵六", "open_id": "ou_manager_zhao"}],
        supervisors=[{"name": "赵六", "open_id": ""}, {"name": "督导F", "open_id": "ou_supervisor_f"}],
    )
    recs = reminder.recipients_for(vehicle)
    assert [(r["name"], r["role"]) for r in recs] == [
        ("赵六", "manager"),
        ("督导F", "supervisor"),
    ]


def test_national_recipients_excluded(patched):
    vehicle = make_vehicle(
        "LSVNATION0000001",
        managers=[{"name": "经理A", "open_id": "ou_manager_a"}],
        supervisors=[{"name": "督导C", "open_id": "ou_supervisor_c"}],
    )
    settings = {
        "eligibility": DEFAULT_SETTINGS["eligibility"],
        "offset_days": 90,
        "national_recipients": [{"name": "刘明轩"}, {"name": "胡进"}],
    }
    sent, _, _ = patched([vehicle], settings=settings, patch_recipients=False)
    result = reminder.run_reminders(day="2026-01-01", dry_run=False)

    names = [r["name"] for r in result["items"][0]["recipients"]]
    assert "刘明轩" not in names and "胡进" not in names
    assert names == ["经理A", "督导C"]
    assert sorted(open_id for open_id, _ in sent) == ["ou_manager_a", "ou_supervisor_c"]


def test_recipients_managers_and_supervisors_in_run(patched, monkeypatch):
    vehicle = make_vehicle(
        "LSVSEND000000001",
        managers=[{"name": "经理A", "open_id": "ou_manager_a"}],
        supervisors=[{"name": "督导C", "open_id": "ou_supervisor_c"}],
    )
    sent, marked, _ = patched([vehicle], patch_recipients=False)
    result = reminder.run_reminders(day="2026-01-01", dry_run=False)

    assert result["sent"] == 1
    assert result["items"][0]["status"] == "sent"
    assert [(r["name"], r["role"]) for r in result["items"][0]["recipients"]] == [
        ("经理A", "manager"),
        ("督导C", "supervisor"),
    ]
    assert sorted(open_id for open_id, _ in sent) == ["ou_manager_a", "ou_supervisor_c"]
    assert all(text == result["items"][0]["message"] for _, text in sent)
    assert marked == ["LSVSEND000000001"]


def test_unmatched_store_sends_nothing(patched, monkeypatch):
    vehicle = make_vehicle("LSVNOMATCH0000001", unmatched=True)
    sent, marked, _ = patched([vehicle], patch_recipients=False)
    result = reminder.run_reminders(day="2026-01-01", dry_run=False)

    assert sent == []
    assert marked == []
    assert result["unmatched"] == 1
    item = result["items"][0]
    assert item["status"] == "failed"
    assert item["recipients"] == []
    assert any("未匹配" in e for e in item["errors"])


def test_manager_without_open_id_fails(patched):
    vehicle = make_vehicle(
        "LSVNOOPENID000001",
        unmatched=False,
        managers=[{"name": "经理A", "open_id": ""}],
    )
    sent, _, _ = patched([vehicle], patch_recipients=False)
    result = reminder.run_reminders(day="2026-01-01", dry_run=False)

    assert sent == []
    assert result["sent"] == 0
    item = result["items"][0]
    assert item["status"] == "failed"
    assert any("无 open_id" in e for e in item["errors"])


def test_dedup_skip_and_force(patched, monkeypatch):
    vehicles = [make_vehicle("LSVDUP0000000001")]
    sent, marked, _ = patched(vehicles)
    monkeypatch.setattr(reminder, "already_sent", lambda vin, due_date: True)

    result = reminder.run_reminders(day="2026-01-01", dry_run=False)
    assert result["skipped"] == 1
    assert result["items"][0]["status"] == "skipped"
    assert sent == []

    result_force = reminder.run_reminders(day="2026-01-01", dry_run=False, force=True)
    assert result_force["skipped"] == 0
    assert result_force["items"][0]["status"] == "failed"  # 无收件人（recipients 已 patch 为空）
