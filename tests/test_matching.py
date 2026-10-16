"""门店匹配与督导关联测试：先编码后名称、区域回退，全部 monkeypatch，不读本地数据文件。"""

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


def test_code_match_beats_name(monkeypatch):
    stores = [
        make_store("猛士汽车北京朝阳交付中心", code="MSCSDS001", managers=[{"name": "经理甲", "open_id": "ou_a"}]),
        make_store("猛士汽车北京海淀用户中心", code="MSCSDS002", managers=[{"name": "经理乙", "open_id": "ou_b"}]),
    ]
    patch_lists(monkeypatch, stores)
    vehicle = {"store": "猛士汽车北京海淀用户中心", "store_code": "mscsds001"}
    enriched = matching.enrich_vehicle(vehicle, stores)
    assert enriched["matched_store"] == "猛士汽车北京朝阳交付中心"
    assert enriched["match_method"] == "code"
    assert not enriched["unmatched"]
    assert [p["name"] for p in enriched["managers"]] == ["经理甲"]


def test_name_match_when_no_code(monkeypatch):
    stores = [
        make_store("猛士汽车北京海淀用户中心", code="MSCSDS002", managers=[{"name": "经理乙", "open_id": "ou_b"}]),
    ]
    patch_lists(monkeypatch, stores)
    vehicle = {"store": "猛士北京海淀用户中心", "store_code": ""}
    enriched = matching.enrich_vehicle(vehicle, stores)
    assert enriched["matched_store"] == "猛士汽车北京海淀用户中心"
    assert enriched["match_method"] == "name"


def test_region_fallback_for_supervisors(monkeypatch):
    supervisors = [
        {
            "people": [{"name": "华中督导", "open_id": "ou_sup_huazhong"}],
            "stores": [],
            "region": "华中",
        },
        {
            "people": [{"name": "华北督导", "open_id": "ou_sup_huabei"}],
            "stores": [],
            "region": "华北",
        },
    ]
    patch_lists(monkeypatch, stores=[], supervisors=supervisors)
    vehicle = {"store": "未知门店", "store_code": "", "region": "华中 1"}
    enriched = matching.enrich_vehicle(vehicle)
    assert enriched["match_method"] == "region"
    assert enriched["unmatched"]
    assert [p["name"] for p in enriched["supervisors"]] == ["华中督导"]
    recs = reminder.recipients_for(enriched)
    assert [(r["name"], r["role"]) for r in recs] == [("华中督导", "supervisor")]


def test_unmatched_no_recipients_nothing_sent(monkeypatch):
    patch_lists(monkeypatch, stores=[], supervisors=[])
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(reminder, "load_settings", lambda: {"eligibility": {"series_names": ["全新M817"], "excluded_data_types": ["试驾车"]}})
    monkeypatch.setattr(reminder, "already_sent", lambda vin, due_date: False)
    monkeypatch.setattr(reminder, "_append_job_log", lambda entry: None)
    monkeypatch.setattr(reminder, "_mark_sent", lambda vin, due_date, recipients: sent.append(vin))
    monkeypatch.setattr(reminder, "send_text_message", lambda open_id, text: sent.append((open_id, text)))

    vehicle = {"vin": "LSVNOMATCH0000001", "due_date": "2026-01-01", "series_name": "全新M817", "store": "未知门店", "store_code": ""}
    monkeypatch.setattr(reminder, "due_on", lambda day=None: [dict(vehicle)])
    monkeypatch.setattr(reminder, "enrich_vehicle", lambda v, stores=None: matching.enrich_vehicle(v))
    result = reminder.run_reminders(day="2026-01-01", dry_run=False)

    assert result["unmatched"] == 1
    item = result["items"][0]
    assert item["match_method"] == "none"
    assert item["recipients"] == []
    assert item["status"] == "failed"
    assert sent == []
