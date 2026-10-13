"""exclusion_reason 纯函数测试（无网络、无数据文件）。"""

from nss.exclusions import exclusion_reason, mask_vin, normalize_series, series_matches
from nss.settings import DEFAULT_SETTINGS

SETTINGS = {"exclusions": DEFAULT_SETTINGS["exclusions"]}


def reason(vehicle: dict) -> str | None:
    return exclusion_reason(vehicle, SETTINGS)


def test_series_917():
    assert reason({"series": "917"}) == "车系917"


def test_series_917_l():
    assert reason({"series": "917-L"}) == "车系917"


def test_series_fullwidth_with_spaces():
    assert reason({"series": " ９１７ "}) == "车系917"


def test_series_with_prefix_and_suffix():
    assert reason({"series_name": "猛士917"}) == "车系917"
    assert reason({"series": "917（联名改装）"}) == "车系917"
    assert reason({"series": "猛士 917-L"}) == "车系917"


def test_aftersales_series_917():
    assert reason({"aftersales_series": "917"}) == "车系917"


def test_series_name_917():
    assert reason({"series_name": "猛士917"}) == "车系917"


def test_m817_not_excluded():
    assert reason({"series": "M817"}) is None
    assert reason({"series": "全新M817"}) is None
    assert reason({"series_name": "X700", "series": "M817", "aftersales_series": "X700"}) is None
    assert reason({"series": "联名改装"}) is None
    assert reason({"series": "M917"}) is None


def test_data_type_test_drive():
    assert reason({"data_type": "试驾车"}) == "试驾车"
    assert reason({"data_type": " 试驾车 "}) == "试驾车"


def test_model_keyword_test_drive():
    assert reason({"model": "猛士M817 HERO（试驾车）(2025款)"}) == "试驾车"


def test_model_keyword_disabled():
    settings = {"exclusions": {**DEFAULT_SETTINGS["exclusions"], "model_keyword_test_drive": False}}
    vehicle = {"model": "猛士M817 HERO（试驾车）(2025款)"}
    assert exclusion_reason(vehicle, settings) is None


def test_exclusions_disabled():
    settings = {"exclusions": {**DEFAULT_SETTINGS["exclusions"], "enabled": False}}
    vehicle = {"series": "917", "data_type": "试驾车", "model": "（试驾车）"}
    assert exclusion_reason(vehicle, settings) is None


def test_series_priority_over_test_drive():
    assert reason({"series": "917", "data_type": "试驾车"}) == "车系917"


def test_series_matches_rules():
    assert series_matches("917", "917")
    assert series_matches("917-L", "917")
    assert series_matches("917（限量）", "917")
    assert not series_matches("M917", "917")
    assert not series_matches("917x", "917")


def test_normalize_series():
    assert normalize_series(" 猛士９１７ ") == "917"
    assert normalize_series("全新M817") == "全新M817"


def test_mask_vin():
    assert mask_vin("LSVAA1234BC56789") == "LSV***6789"
    assert mask_vin("ABC") == "ABC***"
    assert mask_vin("") == ""
