"""门店匹配与区域测试：只认 DMS 店代码，区域只读 reportdb；不读本地数据文件、不联网。"""

import sqlite3

import nss.matching as matching
import nss.reminder as reminder


def make_store(name, code="", region="", managers=None, supervisors=None, aliases=None):
    return {
        "name": name,
        "aliases": aliases or [],
        "code": code,
        "region": region,
        "managers": managers or [],
        "supervisors": supervisors or [],
    }


def patch_lists(monkeypatch, stores=None, supervisors=None):
    monkeypatch.setattr(matching, "load_stores", lambda: stores or [])
    monkeypatch.setattr(matching, "load_supervisors", lambda: supervisors or [])


def make_region_db(path, rows):
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE stores (code TEXT, region TEXT)")
        conn.executemany("INSERT INTO stores (code, region) VALUES (?, ?)", rows)
        conn.commit()
    finally:
        conn.close()
    return path


def test_code_match_is_trimmed_and_case_insensitive(monkeypatch):
    stores = [
        make_store(
            "猛士汽车北京朝阳交付中心",
            code="MSCSDS001",
            region="飞书区域",
            managers=[
                {"name": "经理甲", "open_id": "ou_a", "phone": "13800000001"},
                {"name": "经理乙", "open_id": "ou_b", "phone": "13800000002"},
            ],
            supervisors=[{"name": "督导甲", "open_id": "ou_sup"}],
        ),
        make_store("猛士汽车北京海淀用户中心", code="MSCSDS002"),
    ]
    patch_lists(monkeypatch, stores)
    vehicle = {"store": "名称完全不同的店", "store_code": " mscsds001 "}
    enriched = matching.enrich_vehicle(vehicle, stores)
    assert enriched["matched_store"] == "猛士汽车北京朝阳交付中心"
    assert enriched["match_method"] == "code"
    assert not enriched["unmatched"]
    assert [p["name"] for p in enriched["managers"]] == ["经理甲", "经理乙"]
    assert [p["name"] for p in enriched["supervisors"]] == ["督导甲"]


def test_match_store_never_falls_back_to_name_or_alias(monkeypatch):
    stores = [
        make_store(
            "猛士汽车北京海淀用户中心",
            code="MSCSDS002",
            aliases=["北京海淀店"],
            managers=[{"name": "经理乙", "open_id": "ou_b"}],
        )
    ]
    patch_lists(monkeypatch, stores)
    assert matching.match_store("猛士汽车北京海淀用户中心", stores) is None
    assert matching.match_store("北京海淀店", stores, "") is None
    assert matching.match_store("猛士汽车北京海淀用户中心", stores, "MSCSDS002") is stores[0]


def test_no_code_or_no_match_clears_managers_supervisors_and_region(monkeypatch, tmp_path):
    stores = [
        make_store(
            "猛士汽车北京海淀用户中心",
            code="MSCSDS002",
            region="华中1区",
            managers=[{"name": "经理乙", "open_id": "ou_b"}],
            supervisors=[{"name": "门店督导", "open_id": "ou_store_sup"}],
        )
    ]

    def _unexpected_supervisors():
        raise AssertionError("不应再查督导表做名称/区域回退")

    monkeypatch.setattr(matching, "load_supervisors", _unexpected_supervisors)
    monkeypatch.setenv("NSS_DMS_REGION_DB", str(tmp_path / "missing.sqlite3"))
    for vehicle in (
        {"store": "猛士汽车北京海淀用户中心", "store_code": ""},
        {"store": "猛士汽车北京海淀用户中心", "store_code": "UNKNOWN", "region": "华中1区"},
    ):
        enriched = matching.enrich_vehicle(vehicle, stores)
        assert enriched["unmatched"]
        assert enriched["match_method"] == "none"
        assert enriched["matched_store"] == ""
        assert enriched["managers"] == []
        assert enriched["supervisors"] == []
        assert enriched["region"] == "无区域"


def test_supervisors_only_from_matched_store(monkeypatch):
    stores = [
        make_store(
            "门店A",
            code="S001",
            supervisors=[],
        )
    ]
    supervisors = [
        {"people": [{"name": "区域督导", "open_id": "ou_region"}], "stores": ["门店A"], "region": "华中1区"}
    ]
    patch_lists(monkeypatch, stores, supervisors)
    enriched = matching.enrich_vehicle({"store": "门店A", "store_code": "S001"}, stores)
    assert enriched["matched_store"] == "门店A"
    assert enriched["supervisors"] == []


def test_region_comes_from_temp_reportdb_not_feishu(monkeypatch, tmp_path):
    db = make_region_db(tmp_path / "reportdb.sqlite3", [("s001", " 西北区 ")])
    monkeypatch.setenv("NSS_DMS_REGION_DB", str(db))
    stores = [make_store("门店A", code="S001", region="飞书区域")]
    enriched = matching.enrich_vehicle(
        {"store": "门店A", "store_code": "s001", "region": "飞书区域"}, stores
    )
    assert enriched["region"] == "西北区"


def test_region_missing_db_or_empty_region_is_no_region(monkeypatch, tmp_path):
    monkeypatch.setenv("NSS_DMS_REGION_DB", str(tmp_path / "missing.sqlite3"))
    stores = [make_store("门店A", code="S001", region="华中1区")]
    assert matching.enrich_vehicle({"store_code": "S001"}, stores)["region"] == "无区域"

    db = make_region_db(tmp_path / "reportdb2.sqlite3", [("S002", "")])
    monkeypatch.setenv("NSS_DMS_REGION_DB", str(db))
    assert matching.enrich_vehicle({"store_code": "S002"}, stores)["region"] == "无区域"


def test_region_lookup_reads_fresh_each_call(monkeypatch, tmp_path):
    """不做进程级缓存：reportdb 更新（含 WAL）后下一批立即生效。"""
    db = make_region_db(tmp_path / "reportdb3.sqlite3", [("S001", "华东区")])
    monkeypatch.setenv("NSS_DMS_REGION_DB", str(db))
    assert matching.load_dms_regions() == {"S001": "华东区"}
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE stores SET region='华南区' WHERE code='S001'")
    conn.commit()
    conn.close()
    assert matching.load_dms_regions() == {"S001": "华南区"}


def test_enrich_vehicles_loads_region_once(monkeypatch, tmp_path):
    db = make_region_db(tmp_path / "reportdb4.sqlite3", [("S001", "华南区")])
    monkeypatch.setenv("NSS_DMS_REGION_DB", str(db))
    stores = [make_store("门店A", code="S001")]
    calls = []
    real_load = matching.load_dms_regions

    def counting_load(*args, **kwargs):
        calls.append(args)
        return real_load(*args, **kwargs)

    monkeypatch.setattr(matching, "load_dms_regions", counting_load)
    enriched = matching.enrich_vehicles(
        [{"store_code": "S001"}, {"store_code": "S001"}], stores
    )
    assert [item["region"] for item in enriched] == ["华南区", "华南区"]
    assert len(calls) == 1


def test_unmatched_no_recipients_nothing_sent(monkeypatch, tmp_path):
    patch_lists(monkeypatch, stores=[], supervisors=[])
    monkeypatch.setenv("NSS_DMS_REGION_DB", str(tmp_path / "missing.sqlite3"))
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(reminder, "load_settings", lambda: {"eligibility": {"series_names": ["全新M817"], "excluded_data_types": ["试驾车"]}})
    monkeypatch.setattr(reminder, "already_sent", lambda vin, due_date: False)
    monkeypatch.setattr(reminder, "_append_job_log", lambda entry: None)
    monkeypatch.setattr(reminder, "_mark_sent", lambda vin, due_date, recipients: sent.append(vin))
    monkeypatch.setattr(reminder, "send_text_message", lambda open_id, text: sent.append((open_id, text)))

    vehicle = {"vin": "LSVNOMATCH0000001", "due_date": "2026-01-01", "series_name": "全新M817", "store": "未知门店", "store_code": ""}
    monkeypatch.setattr(reminder, "due_on", lambda day=None: [dict(vehicle)])
    monkeypatch.setattr(reminder, "enrich_vehicles", lambda vs, stores=None: [matching.enrich_vehicle(v) for v in vs])
    result = reminder.run_reminders(day="2026-01-01", dry_run=False)

    assert result["unmatched"] == 1
    item = result["items"][0]
    assert item["match_method"] == "none"
    assert item["recipients"] == []
    assert item["status"] == "failed"
    assert any("未匹配" in error for error in item["errors"])
    assert sent == []
