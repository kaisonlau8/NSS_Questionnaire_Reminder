"""settings 中 eligibility 归一化与旧配置兼容测试。"""

import json

import nss.settings as settings_mod
from nss.settings import load_settings


def _isolate(tmp_path, monkeypatch, raw=None):
    path = tmp_path / "settings.json"
    if raw is not None:
        path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(settings_mod, "SETTINGS_PATH", path)
    monkeypatch.setattr(settings_mod, "SETTINGS_EXAMPLE_PATH", tmp_path / "settings.example.json")


def test_defaults(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    data = load_settings()
    assert data["eligibility"] == settings_mod.DEFAULT_SETTINGS["eligibility"]
    assert data["offset_days"] == 89


def test_normalize_raw(tmp_path, monkeypatch):
    raw = {
        "eligibility": {
            "series_names": " 全新M817 ",
            "excluded_data_types": ["试驾车", " ", None],
        }
    }
    _isolate(tmp_path, monkeypatch, raw)
    data = load_settings()
    assert data["eligibility"] == {"series_names": ["全新M817"], "excluded_data_types": ["试驾车"]}


def test_invalid_eligibility_fall_back_to_defaults(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch, {"eligibility": "oops"})
    data = load_settings()
    assert data["eligibility"] == settings_mod.DEFAULT_SETTINGS["eligibility"]


def test_legacy_keys_ignored(tmp_path, monkeypatch):
    raw = {
        "national_recipients": [{"name": "刘明轩"}],
        "skip_store_keywords": ["虚拟店"],
        "exclusions": {"enabled": True, "series": ["917"]},
        "offset_days": 30,
    }
    _isolate(tmp_path, monkeypatch, raw)
    data = load_settings()
    assert "national_recipients" not in data
    assert "skip_store_keywords" not in data
    assert "exclusions" not in data
    assert data["offset_days"] == 30
    assert data["eligibility"]["series_names"] == ["全新M817"]
