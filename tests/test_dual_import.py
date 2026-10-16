"""双文件导入测试：客户车辆关系（DMS）+ 车辆交付明细（数据门户），按 VIN 关联。"""

import io
import json
import sys
import types
from datetime import date, datetime, timedelta

import pytest
from openpyxl import Workbook

import nss.bitable as bitable
import nss.reminder as reminder
import nss.vehicles as vehicles_mod
from nss.vehicles import (
    import_dual,
    parse_delivery_file,
    parse_portal_datetime,
    parse_relation_file,
)

RELATION_HEADERS = [
    "VIN", "车辆品牌", "售后车系", "车系名称", "车型名称", "销售车型", "车牌号",
    "用车人姓名", "所属门店编码", "所属门店名称", "交付门店编码", "交付门店名称",
    "数据类型", "VIP属性", "VIP等级", "创建时间",
]
DELIVERY_HEADERS = ["序号", "VIN码", "订单状态", "交付时间", "交付城市"]


def rel_row(vin, owner_code="SS001", owner_store="猛士汽车北京朝阳用户中心",
            created="2020-01-01", plate="京A12345", series="全新M817", **extra):
    cells = {h: "" for h in RELATION_HEADERS}
    cells.update(
        {
            "VIN": vin,
            "车系名称": series,
            "车型名称": "全新M817 HERO",
            "售后车系": "M817",
            "车牌号": plate,
            "数据类型": "客户",
            "所属门店编码": owner_code,
            "所属门店名称": owner_store,
            "交付门店编码": "S001",
            "交付门店名称": "猛士汽车北京交付中心",
            "创建时间": created,
        }
    )
    cells.update(extra)
    return [cells[h] for h in RELATION_HEADERS]


def del_row(vin, delivered="2026年7月18日 10:28:54", status="已交付"):
    cells = dict.fromkeys(DELIVERY_HEADERS, "")
    cells.update({"VIN码": vin, "订单状态": status, "交付时间": delivered})
    return [cells[h] for h in DELIVERY_HEADERS]


def make_xlsx(path, rows, headers, sheet):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for item in rows:
        ws.append(list(item))
    wb.save(path)
    return path


def relation_xlsx(tmp_path, rows, headers=RELATION_HEADERS, name="客户车辆关系20261013.xlsx"):
    return make_xlsx(tmp_path / name, rows, headers, "客户车辆关系20261013")


def delivery_xlsx(tmp_path, rows, headers=DELIVERY_HEADERS, name="预订订单_改版_明细.xlsx"):
    return make_xlsx(tmp_path / name, rows, headers, "预订订单数据明细")


STORES = [
    {"name": "猛士汽车北京朝阳用户中心", "code": "SS001", "region": "华北", "aliases": [], "managers": [], "supervisors": []},
    {"name": "猛士汽车上海用户中心", "code": "SS002", "region": "华东", "aliases": [], "managers": [], "supervisors": []},
]


@pytest.fixture(autouse=True)
def patched(monkeypatch, tmp_path):
    monkeypatch.setattr(vehicles_mod, "load_settings", lambda: {"offset_days": 89})
    monkeypatch.setattr(vehicles_mod, "VEHICLES_PATH", tmp_path / "vehicles.json")
    monkeypatch.setattr(reminder, "SENT_PATH", tmp_path / "sent_log.json")
    monkeypatch.setattr(bitable, "load_stores", lambda: STORES)


def test_portal_datetime_formats():
    assert parse_portal_datetime("2026年7月18日 10:28:54") == date(2026, 7, 18)
    assert parse_portal_datetime("2026年07月18日") == date(2026, 7, 18)
    assert parse_portal_datetime("2026-07-18 10:28:54") == date(2026, 7, 18)
    assert parse_portal_datetime("2026/07/18") == date(2026, 7, 18)
    assert parse_portal_datetime("2026.7.18") == date(2026, 7, 18)
    assert parse_portal_datetime(datetime(2026, 7, 18, 10, 28, 54)) == date(2026, 7, 18)
    assert parse_portal_datetime(date(2026, 7, 18)) == date(2026, 7, 18)
    assert parse_portal_datetime("") is None
    assert parse_portal_datetime(None) is None
    assert parse_portal_datetime("待交付") is None


def test_join_only_vehicles_in_both_with_date(tmp_path):
    relation = relation_xlsx(tmp_path, [
        rel_row("LSVBOTH00000001"),
        rel_row("LSVRELOnLY00001"),
        rel_row("LSVNODATE0000001"),
    ])
    delivery = delivery_xlsx(tmp_path, [
        del_row("LSVBOTH00000001"),
        del_row("LSVNODATE0000001", delivered=""),      # 未交付：忽略
        del_row("LSVRELOnLY00001", delivered="", status="已取消"),
        del_row("LSVDLvONLY000001", delivered="2026-07-01"),
    ])
    result = import_dual(relation, delivery)
    assert result["count"] == 1
    stats = result["stats"]
    assert stats["relation_total"] == 3
    assert stats["delivery_total"] == 2
    assert stats["matched"] == 1
    assert stats["only_in_relation"] == 2
    assert stats["only_in_delivery"] == 1
    assert [v["vin"] for v in vehicles_mod.load_vehicles()] == ["LSVBOTH00000001"]
    assert result["source"].startswith("relation=客户车辆关系")
    assert "delivery=预订订单" in result["source"]


def test_delivery_date_from_delivery_file_not_created_time(tmp_path):
    relation = relation_xlsx(tmp_path, [rel_row("LSVDATE000000001", created="2020-01-01")])
    delivery = delivery_xlsx(tmp_path, [del_row("LSVDATE000000001", delivered="2026年7月18日 10:28:54")])
    import_dual(relation, delivery)
    vehicle = vehicles_mod.load_vehicles()[0]
    assert vehicle["delivery_date"] == "2026-07-18"
    assert vehicle["due_date"] == (date(2026, 7, 18) + timedelta(days=89)).isoformat()
    # 归属/展示字段来自关系表
    assert vehicle["store"] == "猛士汽车北京朝阳用户中心"
    assert vehicle["store_code"] == "SS001"
    assert vehicle["delivery_store"] == "猛士汽车北京交付中心"
    assert vehicle["delivery_store_code"] == "S001"
    assert vehicle["plate"] == "京A12345"
    assert vehicle["series_name"] == "全新M817"
    assert vehicle["model"] == "全新M817 HERO"
    assert vehicle["aftersales_series"] == "M817"
    assert vehicle["data_type"] == "客户"


def test_vin_join_case_and_space_insensitive(tmp_path):
    relation = relation_xlsx(tmp_path, [rel_row(" lsvjoin000000001 ")])
    delivery = delivery_xlsx(tmp_path, [del_row("LSVJOIN000000001", delivered="2026-07-18")])
    import_dual(relation, delivery)
    assert [v["vin"] for v in vehicles_mod.load_vehicles()] == ["LSVJOIN000000001"]


def test_missing_headers_name_the_right_file(tmp_path):
    headers = [h for h in RELATION_HEADERS if h != "所属门店编码"]
    relation = relation_xlsx(tmp_path, [rel_row("LSVMISSING0000001", headers=headers)], headers=headers)
    with pytest.raises(ValueError) as exc:
        parse_relation_file(relation)
    assert "客户车辆关系（DMS 导出）" in str(exc.value)
    assert "所属门店编码" in str(exc.value)

    dheaders = [h for h in DELIVERY_HEADERS if h != "交付时间"]
    delivery = delivery_xlsx(tmp_path, [["1", "LSVMISSING0000001", "已交付", "", "北京"]], headers=dheaders)
    with pytest.raises(ValueError) as exc:
        parse_delivery_file(delivery)
    assert "车辆交付明细（数据门户导出）" in str(exc.value)
    assert "交付时间" in str(exc.value)


def test_swapped_files_detected(tmp_path):
    delivery_as_relation = delivery_xlsx(tmp_path, [del_row("LSVSWAP0000000001")])
    with pytest.raises(ValueError) as exc:
        parse_relation_file(delivery_as_relation)
    assert "放反" in str(exc.value)

    relation_as_delivery = relation_xlsx(tmp_path, [rel_row("LSVSWAP0000000002")])
    with pytest.raises(ValueError) as exc:
        parse_delivery_file(relation_as_delivery)
    assert "放反" in str(exc.value)

    with pytest.raises(ValueError):
        import_dual(delivery_as_relation, relation_as_delivery)


def test_duplicates_and_unknown_store_codes(tmp_path):
    relation = relation_xlsx(tmp_path, [
        rel_row("LSVDUP0000000001", owner_code="SS001"),
        rel_row("LSVDUP0000000001", owner_code="SS002"),  # 关系表重复
        rel_row("LSVUNK00000000001", owner_code="SSX99"),
        rel_row("LSVSH000000000001", owner_code="ss002"),  # 编码忽略大小写可匹配
    ])
    delivery = delivery_xlsx(tmp_path, [
        del_row("LSVDUP0000000001", delivered="2026-07-18"),
        del_row("LSVDUP0000000001", delivered="2026-07-19"),  # 明细重复
        del_row("LSVUNK00000000001", delivered="2026-07-18"),
        del_row("LSVSH000000000001", delivered="2026-07-18"),
    ])
    result = import_dual(relation, delivery)
    stats = result["stats"]
    assert stats["duplicates"] == 2
    assert stats["unknown_store_codes"]["count"] == 1
    assert stats["unknown_store_codes"]["examples"] == ["SSX99"]


def test_date_changed_vs_previous(tmp_path):
    relation = relation_xlsx(tmp_path, [
        rel_row("LSVCHG0000000001"),
        rel_row("LSVSAME0000000001"),
        rel_row("LSVNEW00000000001"),
    ])
    delivery = delivery_xlsx(tmp_path, [
        del_row("LSVCHG0000000001", delivered="2026-07-18"),
        del_row("LSVSAME0000000001", delivered="2026-07-10"),
        del_row("LSVNEW00000000001", delivered="2026-07-10"),
    ])
    previous = [
        {"vin": "LSVCHG0000000001", "delivery_date": "2026-01-01", "due_date": "2026-03-31"},
        {"vin": "LSVSAME0000000001", "delivery_date": "2026-07-10", "due_date": "2026-10-07"},
        {"vin": "LSVGONE0000000001", "delivery_date": "2025-12-01", "due_date": "2026-02-28"},
    ]
    vehicles_mod.save_vehicles(previous, source="旧档案")
    result = import_dual(relation, delivery)
    changed = result["stats"]["date_changed"]
    assert changed["count"] == 1
    assert changed["examples"] == [{"vin": "LSVCHG0000000001", "old": "2026-01-01", "new": "2026-07-18"}]


def test_past_due_unsent(tmp_path):
    today = date.today()
    old_delivery = (today - timedelta(days=200)).isoformat()          # 到期日已过
    fresh_delivery = today.isoformat()                                 # 到期日在未来
    old_due = (today - timedelta(days=200 - 89)).isoformat()
    relation = relation_xlsx(tmp_path, [
        rel_row("LSVPASTDUE0000001"),
        rel_row("LSVSENTDUE0000001"),
        rel_row("LSVFUTURE0000001"),
    ])
    delivery = delivery_xlsx(tmp_path, [
        del_row("LSVPASTDUE0000001", delivered=old_delivery),
        del_row("LSVSENTDUE0000001", delivered=old_delivery),
        del_row("LSVFUTURE0000001", delivered=fresh_delivery),
    ])
    sent_vin = "LSVSENTDUE0000001"
    with reminder.SENT_PATH.open("w", encoding="utf-8") as fh:
        json.dump({"items": [{"key": f"{sent_vin}:{old_due}", "vin": sent_vin, "due_date": old_due}]}, fh)
    result = import_dual(relation, delivery)
    past = result["stats"]["past_due_unsent"]
    assert past["count"] == 1
    assert past["examples"] == [{"vin": "LSVPASTDUE0000001", "due_date": old_due}]
    # 已发送的未来车不计数
    vehicles = {v["vin"]: v for v in vehicles_mod.load_vehicles()}
    assert vehicles["LSVFUTURE0000001"]["due_date"] == (today + timedelta(days=89)).isoformat()


def test_dry_run_does_not_save(tmp_path):
    relation = relation_xlsx(tmp_path, [rel_row("LSVDRY0000000001")])
    delivery = delivery_xlsx(tmp_path, [del_row("LSVDRY0000000001")])
    result = import_dual(relation, delivery, dry_run=True)
    assert result["dry_run"] is True
    assert result["stats"]["matched"] == 1
    assert not vehicles_mod.VEHICLES_PATH.exists()


@pytest.fixture()
def flask_client(monkeypatch, tmp_path):
    mhero = types.ModuleType("mhero_auth")
    adapter = types.ModuleType("mhero_auth.flask_adapter")
    adapter.init_app = lambda *a, **k: None
    mhero.flask_adapter = adapter
    monkeypatch.setitem(sys.modules, "mhero_auth", mhero)
    monkeypatch.setitem(sys.modules, "mhero_auth.flask_adapter", adapter)
    import app as app_mod

    monkeypatch.setattr(app_mod, "UPLOAD_DIR", tmp_path / "uploads")
    app_mod.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    app_mod.app.config.update(TESTING=True)
    return app_mod.app.test_client()


def _file_field(path):
    return (io.BytesIO(path.read_bytes()), path.name,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def test_endpoint_requires_both_files(flask_client, tmp_path):
    resp = flask_client.post("/api/upload-dual")
    assert resp.status_code == 400
    assert "客户车辆关系" in resp.get_json()["error"]

    relation = relation_xlsx(tmp_path, [rel_row("LSVEP00000000001")])
    resp = flask_client.post("/api/upload-dual", data={"relation": _file_field(relation)})
    assert resp.status_code == 400
    assert "车辆交付明细" in resp.get_json()["error"]

    delivery = delivery_xlsx(tmp_path, [del_row("LSVEP00000000001")])
    resp = flask_client.post("/api/upload-dual", data={"delivery": _file_field(delivery)})
    assert resp.status_code == 400
    assert "客户车辆关系" in resp.get_json()["error"]


def test_endpoint_imports_and_keeps_chinese_names(flask_client, tmp_path):
    relation = relation_xlsx(tmp_path, [rel_row("LSVEP00000000001")])
    delivery = delivery_xlsx(tmp_path, [del_row("LSVEP00000000001")])
    resp = flask_client.post(
        "/api/upload-dual",
        data={"relation": _file_field(relation), "delivery": _file_field(delivery)},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["stats"]["matched"] == 1
    assert data["meta"]["count"] == 1
    assert "客户车辆关系20261013.xlsx" in data["paths"]["relation"]
    saved = list((tmp_path / "uploads").glob("*客户车辆关系20261013.xlsx"))
    assert len(saved) == 1
