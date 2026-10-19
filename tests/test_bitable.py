"""飞书门店表解析测试：售后负责人 1..4 槽位、手机号配对与缺失统计；不联网。"""

import nss.bitable as bitable


def make_records():
    return [
        {
            "店代码": "S001",
            "店名称": "门店A",
            "区域": "华中1区",
            "督导": [{"id": "ou_sup", "name": "督导A"}],
            "督导手机号": "13900000001",
            "门店售后业务负责人 1": [{"id": "ou_m1", "name": "经理一"}],
            "售后业务负责人手机号 1": "13800000001",
            "门店售后业务负责人2": [{"id": "ou_m2", "name": "经理二"}],
            "售后业务负责人手机号2": "13800000002",
            "门店售后业务负责人 3": [],
            "售后业务负责人手机号 3": "13800000003",
            "门店售后业务负责人 4": [{"id": "ou_m4", "name": "经理四"}],
            "售后业务负责人手机号 4": "13800000004",
        },
        {
            "店代码": "S002",
            "店名称": "门店B",
            "门店售后业务负责人": {"id": "ou_legacy", "name": "旧版经理"},
            "售后业务负责人手机号": "13800000005",
        },
        {
            "店代码": "S003",
            "店名称": "门店C",
            "服务经理": {"id": "ou_alias", "name": "别名经理"},
            "经理电话": "13800000006",
        },
        {
            "店代码": "S004",
            "店名称": "门店D",
            "门店售后业务负责人 1": [{"id": "ou_dup", "name": "重复甲"}],
            "门店售后业务负责人 2": [{"id": "ou_dup", "name": "重复甲2"}],
            "门店售后业务负责人 3": [{"name": "同名乙"}],
            "门店售后业务负责人 4": [{"name": "同名乙"}],
        },
        {
            "店代码": "S005",
            "店名称": "门店E",
        },
    ]


def test_records_collect_all_manager_slots_with_phones_and_primary():
    stores = {store["code"]: store for store in bitable.records_to_stores(make_records())}
    store = stores["S001"]
    # 3 号只有手机号：保留，同步时按手机号解析 open_id
    assert [p["name"] for p in store["managers"]] == ["经理一", "经理二", "", "经理四"]
    assert [p["open_id"] for p in store["managers"]] == ["ou_m1", "ou_m2", "", "ou_m4"]
    assert [p["phone"] for p in store["managers"]] == [
        "13800000001",
        "13800000002",
        "13800000003",
        "13800000004",
    ]
    assert store["primary_manager"] == store["managers"][0]
    assert store["region"] == "华中1区"
    assert store["code"] == "S001"
    assert store["name"] == "门店A"
    assert [p["name"] for p in store["supervisors"]] == ["督导A"]
    assert store["supervisors"][0]["phone"] == "13900000001"


def test_legacy_and_alias_manager_fields_map_to_slot_one():
    stores = {store["code"]: store for store in bitable.records_to_stores(make_records())}
    legacy = stores["S002"]
    assert [(p["name"], p["open_id"], p["phone"]) for p in legacy["managers"]] == [
        ("旧版经理", "ou_legacy", "13800000005")
    ]
    assert legacy["primary_manager"]["name"] == "旧版经理"

    alias = stores["S003"]
    assert [(p["name"], p["open_id"], p["phone"]) for p in alias["managers"]] == [
        ("别名经理", "ou_alias", "13800000006")
    ]


def test_managers_dedupe_by_open_id_then_name():
    stores = {store["code"]: store for store in bitable.records_to_stores(make_records())}
    managers = stores["S004"]["managers"]
    assert [(p["name"], p["open_id"]) for p in managers] == [
        ("重复甲", "ou_dup"),
        ("同名乙", ""),
    ]


def test_blank_numbered_slot_falls_back_to_legacy_manager_and_phone():
    records = [
        {
            "店代码": "S006",
            "店名称": "门店F",
            "门店售后业务负责人 1": "   ",
            "售后业务负责人手机号 1": "",
            "门店售后业务负责人": {"id": "ou_old", "name": "旧版经理"},
            "售后业务负责人手机号": "13800000007",
        }
    ]
    store = bitable.records_to_stores(records)[0]
    assert [(p["name"], p["open_id"], p["phone"]) for p in store["managers"]] == [
        ("旧版经理", "ou_old", "13800000007")
    ]
    assert store["primary_manager"]["name"] == "旧版经理"


def test_sync_all_counts_stores_with_zero_managers(monkeypatch):
    saved: dict[str, dict] = {}

    monkeypatch.setattr(bitable, "_bitable_ids", lambda: {"app_token": "app", "table_id": "tbl", "view_id": "vew"})
    monkeypatch.setattr(bitable, "fetch_fields", lambda table_id: [])
    monkeypatch.setattr(bitable, "fetch_records", lambda table_id, view_id="": make_records())
    monkeypatch.setattr(bitable, "resolve_people_open_ids", lambda stores, supervisors: 0)
    monkeypatch.setattr(
        bitable,
        "save_json",
        lambda path, payload: saved.setdefault(str(path), payload),
    )

    result = bitable.sync_all()
    assert result["store_count"] == 5
    assert result["missing_manager_count"] == 1
    saved_stores = next(payload for path, payload in saved.items() if path.endswith("stores.json"))
    assert [store["code"] for store in saved_stores["stores"] if not store["managers"]] == ["S005"]


def test_slot1_numbered_and_legacy_not_mixed():
    from nss.bitable import _managers_from_fields
    fields = {
        "门店售后业务负责人 1": [{"name": "新经理", "id": "ou_new"}],
        "门店售后业务负责人": [{"name": "旧经理", "id": "ou_old"}],
        "售后业务负责人手机号": "13900000000",
    }
    managers = _managers_from_fields(fields)
    assert [m["open_id"] for m in managers] == ["ou_new"]
    assert managers[0]["phone"] == ""  # 不借用旧负责人的手机号


def test_duplicate_manager_merges_missing_phone():
    from nss.bitable import _managers_from_fields
    fields = {
        "门店售后业务负责人 1": "张三",
        "门店售后业务负责人 2": "张三",
        "售后业务负责人手机号 2": "13800000000",
    }
    managers = _managers_from_fields(fields)
    assert len(managers) == 1 and managers[0]["phone"] == "13800000000"


def test_code_only_row_kept():
    from nss.bitable import records_to_stores
    stores = records_to_stores([{"店代码": "S009", "区域": "华东区"}])
    assert stores and stores[0]["code"] == "S009"


def test_phone_only_manager_kept_for_open_id_resolution():
    from nss.bitable import _managers_from_fields
    managers = _managers_from_fields({"售后业务负责人手机号 1": "13700000000"})
    assert managers == [{"name": "", "open_id": "", "phone": "13700000000"}]
