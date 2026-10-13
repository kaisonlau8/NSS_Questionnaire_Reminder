"""parse_excel 新版「客户车辆关系」导出测试（openpyxl 造表，无网络）。"""

import json
from datetime import date, timedelta

import pytest
from openpyxl import Workbook

import nss.vehicles as vehicles_mod
from nss.vehicles import due_date_for, parse_excel

HEADERS = [
    "VIN", "车辆品牌", "售后车系", "车系名称", "车型名称", "销售车型", "车牌号",
    "用车人ID", "用车人姓名", "用车人电话", "所属门店编码", "所属门店名称",
    "交付门店编码", "交付门店名称", "车主姓名/企业名称", "车主电话", "车主ID",
    "数据类型", "VIP属性", "VIP等级", "创建时间",
]


def row(vin, series="全新M817", data_type="客户", created="2026-07-17",
        delivery_store="猛士汽车北京交付中心", delivery_code="S001",
        owner_store="", plate="京A12345", **extra):
    cells = {h: "" for h in HEADERS}
    cells.update(
        {
            "VIN": vin,
            "车系名称": series,
            "数据类型": data_type,
            "创建时间": created,
            "交付门店名称": delivery_store,
            "交付门店编码": delivery_code,
            "车牌号": plate,
            "售后车系": "M817",
            "车型名称": "全新M817 HERO",
            "所属门店名称": owner_store,
        }
    )
    cells.update(extra)
    return [cells[h] for h in HEADERS]


@pytest.fixture(autouse=True)
def patch_settings(monkeypatch):
    monkeypatch.setattr(vehicles_mod, "load_settings", lambda: {"offset_days": 90})


def make_xlsx(path, rows, sheet="客户车辆关系20261013", headers=HEADERS):
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.append(headers)
    for item in rows:
        ws.append(item)
    wb.save(path)
    return path


def test_due_date_is_created_plus_90(tmp_path):
    path = make_xlsx(tmp_path / "cars.xlsx", [row("LSVNEW000000001", created="2026-07-17")])
    parsed = parse_excel(path)
    assert parsed["stats"] == {"total": 1, "imported": 1, "skipped_no_date": 0, "duplicates": 0}
    vehicle = parsed["vehicles"][0]
    assert vehicle["vin"] == "LSVNEW000000001"
    assert vehicle["delivery_date"] == "2026-07-17"
    assert vehicle["due_date"] == (date(2026, 7, 17) + timedelta(days=90)).isoformat()
    assert vehicle["store"] == "猛士汽车北京交付中心"
    assert vehicle["store_code"] == "S001"
    assert vehicle["plate"] == "京A12345"
    assert vehicle["series_name"] == "全新M817"
    assert vehicle["aftersales_series"] == "M817"
    assert vehicle["model"] == "全新M817 HERO"
    assert vehicle["data_type"] == "客户"


def test_empty_created_skipped(tmp_path):
    path = make_xlsx(
        tmp_path / "cars.xlsx",
        [row("LSVOK00000000001", created="2026-07-17"), row("LSVNODATE0000001", created="")],
    )
    parsed = parse_excel(path)
    assert parsed["stats"]["total"] == 2
    assert parsed["stats"]["imported"] == 1
    assert parsed["stats"]["skipped_no_date"] == 1
    assert [v["vin"] for v in parsed["vehicles"]] == ["LSVOK00000000001"]


def test_unparseable_created_skipped(tmp_path):
    path = make_xlsx(tmp_path / "cars.xlsx", [row("LSVBAD0000000001", created="不是日期")])
    parsed = parse_excel(path)
    assert parsed["stats"]["skipped_no_date"] == 1
    assert parsed["vehicles"] == []


def test_vin_dedup_first_wins(tmp_path):
    path = make_xlsx(
        tmp_path / "cars.xlsx",
        [
            row("LSVDUP0000000001", delivery_store="猛士汽车北京交付中心"),
            row("LSVDUP0000000001", delivery_store="猛士汽车上海交付中心"),
        ],
    )
    parsed = parse_excel(path)
    assert parsed["stats"]["imported"] == 1
    assert parsed["stats"]["duplicates"] == 1
    assert parsed["vehicles"][0]["store"] == "猛士汽车北京交付中心"


def test_pii_not_stored(tmp_path):
    path = make_xlsx(
        tmp_path / "cars.xlsx",
        [row("LSVPII0000000001", **{
            "用车人ID": "U001", "用车人姓名": "张三", "用车人电话": "13800000001",
            "车主姓名/企业名称": "李四", "车主电话": "13900000002", "车主ID": "O001",
        })],
    )
    parsed = parse_excel(path)
    dumped = json.dumps(parsed["vehicles"], ensure_ascii=False)
    for pii in ("张三", "13800000001", "李四", "13900000002", "U001", "O001"):
        assert pii not in dumped
    for key in ("用车人", "车主"):
        assert key not in parsed["vehicles"][0]


def test_store_fallback_to_owner_store(tmp_path):
    path = make_xlsx(
        tmp_path / "cars.xlsx",
        [row("LSVFALLBACK00001", delivery_store="", owner_store="猛士汽车武汉用户中心")],
    )
    parsed = parse_excel(path)
    assert parsed["vehicles"][0]["store"] == "猛士汽车武汉用户中心"


def test_eligibility_not_applied_at_import(tmp_path):
    path = make_xlsx(
        tmp_path / "cars.xlsx",
        [
            row("LSVS917000000001", series="917"),
            row("LSVTEST0000000002", series="全新M817", data_type="试驾车"),
        ],
    )
    parsed = parse_excel(path)
    assert parsed["stats"]["imported"] == 2
    assert {v["series_name"] for v in parsed["vehicles"]} == {"917", "全新M817"}
    assert {v["data_type"] for v in parsed["vehicles"]} == {"客户", "试驾车"}


def test_missing_required_headers(tmp_path):
    path = make_xlsx(tmp_path / "cars.xlsx", [row("LSVMISSING0000001")], headers=[h for h in HEADERS if h != "创建时间"])
    with pytest.raises(ValueError) as exc:
        parse_excel(path)
    assert "创建时间" in str(exc.value)


def test_old_format_still_accepted(tmp_path):
    headers = ["VIN", "车系", "车型", "车牌号", "交付日期", "交付门店"]
    cells = {
        "VIN": "LSVOLD0000000001", "车系": "M817", "车型": "M817", "车牌号": "京B11111",
        "交付日期": "2026-01-01", "交付门店": "猛士汽车北京交付中心",
    }
    path = make_xlsx(tmp_path / "old.xlsx", [[cells[h] for h in headers]], sheet="车辆档案", headers=headers)
    parsed = parse_excel(path)
    vehicle = parsed["vehicles"][0]
    assert vehicle["vin"] == "LSVOLD0000000001"
    assert vehicle["delivery_date"] == "2026-01-01"
    assert vehicle["due_date"] == due_date_for(date(2026, 1, 1), 90).isoformat()
    assert vehicle["store"] == "猛士汽车北京交付中心"
    assert vehicle["series"] == "M817"
    assert vehicle["store_code"] == ""
