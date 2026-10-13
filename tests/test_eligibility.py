"""ineligible_reason 纯函数测试（无网络、无数据文件）。"""

from nss.eligibility import ineligible_reason, mask_vin
from nss.settings import DEFAULT_SETTINGS

SETTINGS = {"eligibility": DEFAULT_SETTINGS["eligibility"]}


def reason(vehicle: dict) -> str | None:
    return ineligible_reason(vehicle, SETTINGS)


def test_series_exact_new_m817_ok():
    assert reason({"series_name": "全新M817"}) is None


def test_series_other_names_ineligible():
    for name in ("M817", "917", "917-L", "联名改装", "X700", "Ultimate", "M182G系列", "M182长轴版本", "全新M817-L", ""):
        assert reason({"series_name": name}) == "车系非全新M817", name


def test_series_strip_and_nfkc():
    assert reason({"series_name": " 全新M817 "}) is None
    assert reason({"series_name": "全新Ｍ８１７"}) is None


def test_data_type_test_drive_ineligible():
    assert reason({"series_name": "全新M817", "data_type": "试驾车"}) == "试驾车"
    assert reason({"series_name": "全新M817", "data_type": " 试驾车 "}) == "试驾车"


def test_data_type_ok_values():
    for data_type in ("客户", "质检", "", None):
        assert reason({"series_name": "全新M817", "data_type": data_type}) is None, data_type


def test_series_reason_first():
    assert reason({"series_name": "917", "data_type": "试驾车"}) == "车系非全新M817"


def test_custom_settings():
    settings = {"eligibility": {"series_names": ["M817"], "excluded_data_types": ["质检"]}}
    assert ineligible_reason({"series_name": "M817"}, settings) is None
    assert ineligible_reason({"series_name": "全新M817"}, settings) == "车系非M817"
    assert ineligible_reason({"series_name": "M817", "data_type": "质检"}, settings) == "质检"


def test_defaults_without_settings():
    assert ineligible_reason({"series_name": "全新M817"}) is None
    assert ineligible_reason({"series_name": "917"}) == "车系非全新M817"
    assert ineligible_reason({"series_name": "全新M817", "data_type": "试驾车"}) == "试驾车"


def test_mask_vin():
    assert mask_vin("LSVAA1234BC56789") == "LSV***6789"
    assert mask_vin("ABC") == "ABC***"
    assert mask_vin("") == ""
