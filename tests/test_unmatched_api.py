"""GET /api/unmatched：未匹配车辆列表、VIN 脱敏与按店代码计数。"""

import app as app_module
import nss.matching as matching


def make_store(name, code):
    return {
        "name": name,
        "aliases": [],
        "code": code,
        "region": "飞书区域",
        "managers": [{"name": "经理", "open_id": "ou_m"}],
        "supervisors": [{"name": "督导", "open_id": "ou_s"}],
    }


def test_api_unmatched_lists_masked_vehicles_and_counts(monkeypatch, tmp_path):
    vehicles = [
        {
            "vin": "LSVUNMATCH0000001",
            "store": "DMS门店甲",
            "store_code": "UNK1",
            "delivery_date": "2026-01-01",
            "due_date": "2026-03-31",
            "series_name": "全新M817",
        },
        {
            "vin": "LSVUNMATCH0000002",
            "store": "DMS门店甲",
            "store_code": "unk1",
            "delivery_date": "2026-01-02",
            "due_date": "2026-04-01",
            "series_name": "全新M817",
        },
        {
            "vin": "LSVUNMATCH0000003",
            "store": "DMS门店乙",
            "store_code": "",
            "delivery_date": "2026-01-03",
            "due_date": "",
            "series_name": "全新M817",
        },
        {
            "vin": "LSVMATCHED0000004",
            "store": "DMS门店丙",
            "store_code": "S001",
            "delivery_date": "2026-01-04",
            "due_date": "2026-04-03",
            "series_name": "全新M817",
        },
    ]
    monkeypatch.setattr(app_module, "load_vehicles", lambda: vehicles)
    monkeypatch.setattr(matching, "load_stores", lambda: [make_store("门店丙", "S001")])
    monkeypatch.setenv("NSS_DMS_REGION_DB", str(tmp_path / "missing.sqlite3"))

    response = app_module.app.test_client().get("/api/unmatched")
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["count"] == 3
    assert data["by_store_code"] == {"UNK1": 2, "": 1}
    assert [item["vin"] for item in data["items"]] == [
        "LSV***0001",
        "LSV***0002",
        "LSV***0003",
    ]
    assert all("LSVUNMATCH" not in item["vin"] for item in data["items"])
    first = data["items"][0]
    assert first["store_code"] == "UNK1"
    assert first["store"] == "DMS门店甲"
    assert first["store_name"] == "DMS门店甲"
    assert first["delivery_date"] == "2026-01-01"
    assert first["due_date"] == "2026-03-31"
    assert {group["store_code"]: group["count"] for group in data["groups"]} == {
        "UNK1": 2,
        "": 1,
    }


def test_api_unmatched_empty_when_all_matched(monkeypatch, tmp_path):
    vehicles = [
        {
            "vin": "LSVMATCHED0000001",
            "store": "门店甲",
            "store_code": "S001",
            "delivery_date": "2026-01-01",
            "due_date": "2026-03-31",
        }
    ]
    monkeypatch.setattr(app_module, "load_vehicles", lambda: vehicles)
    monkeypatch.setattr(matching, "load_stores", lambda: [make_store("门店甲", "s001")])
    monkeypatch.setenv("NSS_DMS_REGION_DB", str(tmp_path / "missing.sqlite3"))

    data = app_module.app.test_client().get("/api/unmatched").get_json()
    assert data["count"] == 0
    assert data["items"] == []
    assert data["by_store_code"] == {}
    assert data["groups"] == []
